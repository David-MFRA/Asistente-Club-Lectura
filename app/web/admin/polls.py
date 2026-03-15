import json
import logging
from html import escape as hesc

from flask import flash, redirect, url_for

import ai_features
import db
from app.messages import get_text

logger = logging.getLogger(__name__)


# ─── helpers ──────────────────────────────────────────────────────────────────

def _set_phase(phase):
    db.set_config("cycle_phase", phase)


# ─── Book polls ───────────────────────────────────────────────────────────────

async def create_book_poll(require_admin, telegram_app, telegram_chat_id, logger):
    auth = require_admin()
    if auth:
        return auth
    try:
        books = db.get_book_proposals()
        logger.info("Admin: crear encuesta libros (%d propuestas)", len(books))
        if len(books) < 2:
            flash("Necesitas al menos 2 propuestas para crear una encuesta", "danger")
            return redirect(url_for("admin_dashboard"))
        if not telegram_chat_id:
            flash("TELEGRAM_CHAT_ID no configurado en variables de entorno", "danger")
            return redirect(url_for("admin_dashboard"))

        cycle = db.get_current_cycle_key()
        # Lock proposals
        locked_now = db.get_config("proposals_locked_for") or ""
        locked_set = {v.strip() for v in locked_now.split(",") if v.strip()}
        locked_set.add(cycle)
        db.set_config("proposals_locked_for", ",".join(sorted(locked_set)))

        # Split into at most 2 polls if > 10 proposals
        chunks = [books[:10]] if len(books) <= 10 else [books[:10], books[10:20]]
        for i, chunk in enumerate(chunks):
            options = []
            for book in chunk:
                label = book["title"]
                if book.get("author"):
                    label = f"{book['title']} - {book['author']}"
                options.append(label[:100])
            question = get_text("poll_books_question")
            if len(chunks) > 1:
                question = get_text("poll_books_question") + f" (parte {i+1}/{len(chunks)})"
            msg = await telegram_app.bot.send_poll(
                chat_id=telegram_chat_id,
                question=question,
                options=options,
                is_anonymous=False,
                allows_multiple_answers=False,
            )
            db.save_poll(chat_id=msg.chat_id, message_id=msg.message_id, poll_id=msg.poll.id,
                         poll_type="books", cycle_key=cycle)
            # Store option→proposal_id mapping for real-time vote tracking
            db.set_config(f"poll_options_{msg.poll.id}", json.dumps([b["proposal_id"] for b in chunk]))

        _set_phase("book_voting")
        suffix = f" (en {len(chunks)} partes)" if len(chunks) > 1 else ""
        logger.info("Admin: encuesta libros lanzada (%d partes, ciclo=%s)", len(chunks), cycle)
        flash(f"Propuestas bloqueadas. Encuesta de libros lanzada{suffix}.", "success")
    except Exception:
        logger.exception("Error creando encuesta libros")
        flash("Error creando la encuesta de libros", "danger")
    return redirect(url_for("admin_dashboard"))


async def close_poll(require_admin, poll_db_id, telegram_app, telegram_chat_id, send_to_group, announce_winner, logger):
    auth = require_admin()
    if auth:
        return auth
    logger.info("Admin: cerrar encuesta db_id=%d", poll_db_id)
    try:
        poll = db.get_poll_by_id(poll_db_id)
        if not poll:
            flash("Encuesta no encontrada", "danger")
            return redirect(url_for("admin_dashboard"))

        await telegram_app.bot.stop_poll(chat_id=poll["chat_id"], message_id=poll["message_id"])
        db.close_poll(poll_db_id)

        if poll.get("poll_type") == "books" and telegram_chat_id:
            cycle_key = poll.get("cycle_key") or db.get_current_cycle_key()

            # Check if there are still open book polls for this cycle
            remaining_open = db.get_open_polls(poll_type="books", cycle_key=cycle_key)
            all_cycle_polls = db.get_all_polls_for_cycle(poll_type="books", cycle_key=cycle_key)
            total = len(all_cycle_polls)
            closed = sum(1 for p in all_cycle_polls if p["is_closed"])

            if remaining_open:
                logger.info("Admin: encuesta cerrada (%d/%d), quedan %d abiertas en ciclo=%s",
                            closed, total, len(remaining_open), cycle_key)
                # Still more polls to close — don't determine winner yet
                flash(
                    f"Encuesta cerrada ({closed}/{total}). "
                    f"Quedan {len(remaining_open)} encuesta(s) abiertas del mismo ciclo. "
                    f"Ciérralas todas antes de determinar el ganador.",
                    "warning",
                )
                return redirect(url_for("admin_dashboard"))

            # All polls closed — now determine winner from accumulated book_votes
            tied = db.get_tied_books()
            if len(tied) > 1:
                books_list = "\n".join(
                    f"  • <b>{hesc(b['title'])}</b>" + (f" — {hesc(b['author'])}" if b.get("author") else "")
                    for b in tied
                )
                tie_text = (
                    f"⚖️ <b>¡Empate en la votación de libros!</b>\n\n"
                    f"Estos libros han quedado empatados con <b>{tied[0]['votes']} votos</b>:\n"
                    f"{books_list}\n\n"
                    f"🔁 El admin decidirá el siguiente paso."
                )
                await send_to_group(tie_text, parse_mode="HTML", message_type="tie_notification")

                options = []
                for book in tied[:10]:
                    label = book["title"]
                    if book.get("author"):
                        label = f"{book['title']} - {book['author']}"
                    options.append(label[:100])
                tie_poll = await telegram_app.bot.send_poll(
                    chat_id=telegram_chat_id,
                    question=f"⚖️ Desempate: ¿cuál de estos {len(tied)} libros leemos?",
                    options=options,
                    is_anonymous=False,
                    allows_multiple_answers=False,
                )
                db.save_poll(
                    chat_id=tie_poll.chat_id,
                    message_id=tie_poll.message_id,
                    poll_id=tie_poll.poll.id,
                    poll_type="books",
                    cycle_key=cycle_key,
                )
                # Guardar mapeo opción→proposal_id para seguimiento de votos en tiempo real
                db.set_config(f"poll_options_{tie_poll.poll.id}", json.dumps([b["proposal_id"] for b in tied[:10]]))
                flash(f"Todas las encuestas cerradas. Empate entre {len(tied)} libros. Encuesta de desempate lanzada.", "warning")
                return redirect(url_for("admin_dashboard"))

            winner = db.get_winner_book()
            if winner:
                logger.info("Admin: ganador encuesta libros → «%s» (%d votos)", winner["title"], winner.get("votes", 0))
                await announce_winner(winner)
                next_meeting = db.get_latest_scheduled_meeting()
                if next_meeting and not next_meeting.get("book_id"):
                    db.update_meeting(meeting_id=next_meeting["id"], book_id=winner["id"])
                _set_phase("date_voting")
                flash(f"¡Ganador: «{winner['title']}»! Ahora añade fechas para la reunión.", "success")
            else:
                flash("Todas las encuestas cerradas. Sin ganador claro aún.", "warning")
        else:
            flash("Encuesta cerrada correctamente", "success")
    except Exception:
        logger.exception("Error cerrando encuesta")
        flash("Error cerrando la encuesta", "danger")
    return redirect(url_for("admin_dashboard"))


async def pick_book_winner(require_admin, proposal_id, announce_winner_fn, logger):
    """Admin elige manualmente el libro ganador (desempate manual)."""
    auth = require_admin()
    if auth:
        return auth
    book = db.get_proposal_by_id(proposal_id)
    if not book:
        flash("Propuesta no encontrada", "danger")
        return redirect(url_for("admin_ciclo"))
    await announce_winner_fn(book)
    next_meeting = db.get_latest_scheduled_meeting()
    if next_meeting and not next_meeting.get("book_id"):
        db.update_meeting(meeting_id=next_meeting["id"], book_id=book["id"])
    _set_phase("date_voting")
    flash(f"«{book['title']}» elegido como ganador. Anuncio enviado.", "success")
    return redirect(url_for("admin_ciclo"))


# ─── Theme polls ──────────────────────────────────────────────────────────────

async def create_theme_poll(require_admin, telegram_app, telegram_chat_id, logger):
    auth = require_admin()
    if auth:
        return auth
    try:
        themes = db.get_themes()
        logger.info("Admin: crear encuesta temáticas (%d temáticas)", len(themes))
        if len(themes) < 2:
            flash("Necesitas al menos 2 temáticas para crear una encuesta", "danger")
            return redirect(url_for("admin_ciclo"))
        if not telegram_chat_id:
            flash("TELEGRAM_CHAT_ID no configurado", "danger")
            return redirect(url_for("admin_ciclo"))

        options = [theme["name"][:100] for theme in themes[:10]]
        msg = await telegram_app.bot.send_poll(
            chat_id=telegram_chat_id,
            question=get_text("poll_themes_question"),
            options=options,
            is_anonymous=False,
            allows_multiple_answers=False,
        )
        db.save_poll(chat_id=msg.chat_id, message_id=msg.message_id, poll_id=msg.poll.id, poll_type="themes")
        # Store option→theme_id mapping for real-time vote tracking
        db.set_config(f"poll_options_{msg.poll.id}", json.dumps([t["id"] for t in themes[:10]]))
        _set_phase("theme_voting")
        flash("Encuesta de temáticas lanzada en el grupo", "success")
    except Exception:
        logger.exception("Error creando encuesta temas")
        flash("Error creando la encuesta de temáticas", "danger")
    return redirect(url_for("admin_ciclo"))


async def close_theme_poll(require_admin, poll_db_id, telegram_app, telegram_chat_id, send_to_group, logger):
    """Cierra encuesta de temática. Si hay empate → desempate. Si hay ganador → fase books."""
    auth = require_admin()
    if auth:
        return auth
    logger.info("Admin: cerrar encuesta temáticas db_id=%d", poll_db_id)
    try:
        poll = db.get_poll_by_id(poll_db_id)
        if not poll:
            flash("Encuesta no encontrada", "danger")
            return redirect(url_for("admin_ciclo"))

        cycle_key = poll.get("cycle_key") or db.get_current_cycle_key()
        tg_poll = await telegram_app.bot.stop_poll(chat_id=poll["chat_id"], message_id=poll["message_id"])
        db.close_poll(poll_db_id)

        # Determine winner directly from Telegram poll data (authoritative vote counts)
        options_map_raw = db.get_config(f"poll_options_{poll['poll_id']}") or "[]"
        try:
            theme_ids = json.loads(options_map_raw)
        except Exception:
            theme_ids = []

        # Build ranked list: [{id, name, votes}] from tg_poll.options + theme_ids mapping
        all_themes_db = {t["id"]: t for t in db.get_themes()}
        ranked = []
        if tg_poll and tg_poll.options and theme_ids:
            for i, opt in enumerate(tg_poll.options):
                if i < len(theme_ids):
                    tid = theme_ids[i]
                    name_str = all_themes_db.get(tid, {}).get("name") or opt.text
                    ranked.append({"id": tid, "name": name_str, "votes": opt.voter_count})
            ranked.sort(key=lambda x: x["votes"], reverse=True)
        # Fallback to DB counts if mapping unavailable
        if not ranked:
            ranked = db.get_themes()

        total_votes = sum(r["votes"] for r in ranked)
        logger.info("Admin: encuesta temáticas cerrada — %d votos totales, %d opciones", total_votes, len(ranked))
        if total_votes == 0:
            flash("Encuesta de temáticas cerrada, pero no se registró ningún voto.", "warning")
            return redirect(url_for("admin_ciclo"))

        max_votes = ranked[0]["votes"]
        tied = [t for t in ranked if t["votes"] == max_votes]

        if len(tied) > 1:
            themes_list = "\n".join(f"  • <b>{hesc(t['name'])}</b>" for t in tied)
            tie_text = (
                f"⚖️ <b>¡Empate en la votación de temática!</b>\n\n"
                f"Estas temáticas han quedado empatadas con <b>{max_votes} votos</b>:\n"
                f"{themes_list}\n\n"
                f"🔁 El admin decidirá el siguiente paso."
            )
            await send_to_group(tie_text, parse_mode="HTML", message_type="theme_tie")

            if telegram_chat_id:
                options = [t["name"][:100] for t in tied[:10]]
                tie_poll = await telegram_app.bot.send_poll(
                    chat_id=telegram_chat_id,
                    question="⚖️ Desempate temática: ¿cuál elegimos?",
                    options=options,
                    is_anonymous=False,
                    allows_multiple_answers=False,
                )
                db.save_poll(
                    chat_id=tie_poll.chat_id,
                    message_id=tie_poll.message_id,
                    poll_id=tie_poll.poll.id,
                    poll_type="themes",
                )
                # Guardar mapeo opción→theme_id para seguimiento de votos en tiempo real
                db.set_config(f"poll_options_{tie_poll.poll.id}", json.dumps([t["id"] for t in tied[:10]]))
            flash(f"Empate entre {len(tied)} temáticas. Encuesta de desempate lanzada.", "warning")
            return redirect(url_for("admin_ciclo"))

        # No tie → winner is ranked[0]
        top = ranked[0] if ranked else None
        if top:
            logger.info("Admin: temática ganadora → «%s» (%d votos)", top["name"], top["votes"])
            db.set_config("active_theme", top["name"])
            db.set_config(f"active_theme:{cycle_key}", top["name"])
            _set_phase("books")
            db.set_config("proposals_locked_for", "")
            # Try to get AI book suggestion
            ai_suggestion = ""
            try:
                suggestion = ai_features.suggest_book_for_theme(top["name"])
                if suggestion:
                    ai_suggestion = f"\n\n💡 <b>Sugerencia IA:</b> {hesc(suggestion)}"
            except Exception:
                pass
            theme_text = (
                f"🏷️ <b>Temática elegida: {hesc(top['name'])}</b>\n\n"
                f"¡Es hora de proponer libros para este ciclo!\n\n"
                f"📝 Propón con el comando /proponer"
                + ai_suggestion
                + f"\n\n💡 Cuantas más propuestas tengamos, mejor será la votación."
            )
            await send_to_group(theme_text, parse_mode="HTML", message_type="theme_chosen")
            flash(f"Temática «{top['name']}» ganadora. Fase de propuestas abierta.", "success")
        else:
            flash("Encuesta de temáticas cerrada, pero no hay votaciones.", "warning")
    except Exception:
        logger.exception("Error cerrando encuesta temas")
        flash("Error cerrando la encuesta de temáticas", "danger")
    return redirect(url_for("admin_ciclo"))


# ─── Date polls ───────────────────────────────────────────────────────────────

async def create_dates_poll(require_admin, meeting_id, telegram_app, telegram_chat_id, logger):
    auth = require_admin()
    if auth:
        return auth
    logger.info("Admin: crear encuesta fechas meeting_id=%d", meeting_id)
    try:
        meeting = db.get_meeting(meeting_id)
        if not meeting:
            flash("Reunión no encontrada", "danger")
            return redirect(url_for("meetings_admin"))

        date_options = db.get_meeting_date_options(meeting_id)
        if len(date_options) < 2:
            flash("Añade al menos 2 opciones de fecha primero", "warning")
            return redirect(url_for("meeting_detail_admin", meeting_id=meeting_id))
        if not telegram_chat_id:
            flash("TELEGRAM_CHAT_ID no configurado", "danger")
            return redirect(url_for("meeting_detail_admin", meeting_id=meeting_id))

        poll_options = [str(option["option_date"])[:20] for option in date_options[:10]]
        msg = await telegram_app.bot.send_poll(
            chat_id=telegram_chat_id,
            question=get_text("poll_dates_question", meeting_name=meeting["name"])[:300],
            options=poll_options,
            is_anonymous=False,
            allows_multiple_answers=False,
        )
        db.save_poll(
            chat_id=msg.chat_id,
            message_id=msg.message_id,
            poll_id=msg.poll.id,
            poll_type="dates",
            meeting_id=meeting_id,
        )
        flash("Encuesta de fechas lanzada en el grupo", "success")
    except Exception:
        logger.exception("Error creando encuesta fechas")
        flash("Error creando la encuesta de fechas", "danger")
    return redirect(url_for("meeting_detail_admin", meeting_id=meeting_id))


async def close_dates_poll(require_admin, meeting_id, poll_db_id, telegram_app, send_to_group, formatting, logger):
    del formatting
    auth = require_admin()
    if auth:
        return auth
    logger.info("Admin: cerrar encuesta fechas db_id=%d meeting_id=%d", poll_db_id, meeting_id)
    try:
        poll = db.get_poll_by_id(poll_db_id)
        if not poll:
            flash("Encuesta no encontrada", "danger")
            return redirect(url_for("meeting_detail_admin", meeting_id=meeting_id))

        tg_poll = await telegram_app.bot.stop_poll(chat_id=poll["chat_id"], message_id=poll["message_id"])
        db.close_poll(poll_db_id)

        if tg_poll.options:
            # Check tie on dates
            max_votes = max(o.voter_count for o in tg_poll.options)
            if max_votes == 0:
                flash("Encuesta de fechas cerrada sin votos. Selecciona la fecha manualmente.", "warning")
                return redirect(url_for("meeting_detail_admin", meeting_id=meeting_id))
            tied_opts = [o for o in tg_poll.options if o.voter_count == max_votes]
            if len(tied_opts) > 1:
                opts = [o.text for o in tied_opts[:10]]
                tie_poll = await telegram_app.bot.send_poll(
                    chat_id=poll["chat_id"],
                    question="⚖️ Desempate de fechas: ¿cuándo quedamos?",
                    options=opts,
                    is_anonymous=False,
                    allows_multiple_answers=False,
                )
                db.save_poll(
                    chat_id=tie_poll.chat_id,
                    message_id=tie_poll.message_id,
                    poll_id=tie_poll.poll.id,
                    poll_type="dates",
                    meeting_id=meeting_id,
                )
                flash(f"Empate entre {len(tied_opts)} fechas. Encuesta de desempate lanzada.", "warning")
                return redirect(url_for("meeting_detail_admin", meeting_id=meeting_id))

            winner_text = tg_poll.options[0].text if not tied_opts else max(tg_poll.options, key=lambda o: o.voter_count).text
            date_opts = db.get_meeting_date_options(meeting_id)
            for option in date_opts:
                opt_str = str(option["option_date"])
                if winner_text[:16] in opt_str[:20] or opt_str[:16] in winner_text[:20]:
                    db.set_meeting_final_date(meeting_id, option["option_date"])
                    meeting_obj = db.get_meeting(meeting_id)
                    meeting_name = meeting_obj["name"] if meeting_obj else "la reunión"

                    # Build reading pace info
                    from datetime import datetime as _dt, timezone as _tz
                    pace_line = ""
                    book = None
                    if meeting_obj and meeting_obj.get("book_id"):
                        book = db.get_book_by_id(meeting_obj["book_id"])
                    if not book:
                        book = db.get_winner_book()
                    if book and book.get("pages"):
                        try:
                            final_dt = option["option_date"]
                            if isinstance(final_dt, str):
                                final_dt = _dt.fromisoformat(final_dt)
                            if hasattr(final_dt, 'tzinfo') and final_dt.tzinfo is None:
                                final_dt = final_dt.replace(tzinfo=_tz.utc)
                            days_left = max(1, (_dt.now(_tz.utc) - final_dt).days * -1)
                            pages = book["pages"]
                            daily = max(1, round(pages / days_left))
                            pace_line = (
                                f"\n\n📊 <b>Ritmo de lectura</b>\n"
                                f"Tienes <b>{days_left} días</b> para leer <b>{pages} páginas</b>.\n"
                                f"<i>Unas {daily} páginas al día y llega al día. ¡Tú puedes!</i>"
                            )
                        except Exception:
                            pass

                    msg_text = (
                        f"📅 <b>¡Fecha confirmada!</b>\n\n"
                        f"<b>{hesc(meeting_name)}</b>\n"
                        f"🗓 <b>{hesc(opt_str[:16])}</b>"
                        + (f"\n📍 <b>{hesc(meeting_obj['location'])}</b>" if meeting_obj and meeting_obj.get("location") else "")
                        + pace_line
                        + f"\n\n✅ Confirma asistencia con /asistir\n❌ Si no puedes: /noasistir"
                    )
                    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                    keyboard = [[
                        InlineKeyboardButton("✅ Asistir", callback_data=f"attend:{meeting_id}"),
                        InlineKeyboardButton("❌ No voy", callback_data=f"noattend:{meeting_id}"),
                    ]]
                    await send_to_group(
                        msg_text, parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        message_type="meeting_date_closed",
                    )
                    logger.info("Admin: fecha ganadora → %s para reunión «%s»", opt_str[:16], meeting_name)
                    _set_phase("reading")
                    flash(f"Fecha confirmada: {opt_str[:16]}. Fase de lectura iniciada.", "success")
                    break
            else:
                flash("Encuesta cerrada, pero no se pudo hacer matching de la fecha ganadora.", "warning")
        else:
            flash("Encuesta de fechas cerrada.", "success")
    except Exception:
        logger.exception("Error cerrando encuesta fechas")
        flash("Error cerrando la encuesta de fechas", "danger")
    return redirect(url_for("meeting_detail_admin", meeting_id=meeting_id))
