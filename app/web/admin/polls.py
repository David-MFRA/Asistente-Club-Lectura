from html import escape as hesc

from flask import flash, redirect, url_for

import db


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
            question = "📚 ¿Qué libro leemos este ciclo?"
            if len(chunks) > 1:
                question = f"📚 ¿Qué libro leemos? (parte {i+1}/{len(chunks)})"
            msg = await telegram_app.bot.send_poll(
                chat_id=telegram_chat_id,
                question=question,
                options=options,
                is_anonymous=False,
                allows_multiple_answers=False,
            )
            db.save_poll(chat_id=msg.chat_id, message_id=msg.message_id, poll_id=msg.poll.id, poll_type="books")

        _set_phase("book_voting")
        suffix = f" (en {len(chunks)} partes)" if len(chunks) > 1 else ""
        flash(f"Propuestas bloqueadas. Encuesta de libros lanzada{suffix}.", "success")
    except Exception:
        logger.exception("Error creando encuesta libros")
        flash("Error creando la encuesta de libros", "danger")
    return redirect(url_for("admin_dashboard"))


async def close_poll(require_admin, poll_db_id, telegram_app, telegram_chat_id, send_to_group, announce_winner, logger):
    auth = require_admin()
    if auth:
        return auth
    try:
        poll = db.get_poll_by_id(poll_db_id)
        if not poll:
            flash("Encuesta no encontrada", "danger")
            return redirect(url_for("admin_dashboard"))

        await telegram_app.bot.stop_poll(chat_id=poll["chat_id"], message_id=poll["message_id"])
        db.close_poll(poll_db_id)

        if poll.get("poll_type") == "books" and telegram_chat_id:
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
                )
                flash(f"Empate entre {len(tied)} libros. Encuesta de desempate lanzada automáticamente.", "warning")
                return redirect(url_for("admin_dashboard"))

            winner = db.get_winner_book()
            if winner:
                await announce_winner(winner)
                next_meeting = db.get_latest_scheduled_meeting()
                if next_meeting and not next_meeting.get("book_id"):
                    db.update_meeting(meeting_id=next_meeting["id"], book_id=winner["id"])
                _set_phase("date_voting")
                flash(f"¡Ganador: «{winner['title']}»! Ahora añade fechas para la reunión.", "success")
            else:
                flash("Encuesta cerrada. Sin ganador claro aún.", "warning")
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
        if len(themes) < 2:
            flash("Necesitas al menos 2 temáticas para crear una encuesta", "danger")
            return redirect(url_for("admin_ciclo"))
        if not telegram_chat_id:
            flash("TELEGRAM_CHAT_ID no configurado", "danger")
            return redirect(url_for("admin_ciclo"))

        options = [theme["name"][:100] for theme in themes[:10]]
        msg = await telegram_app.bot.send_poll(
            chat_id=telegram_chat_id,
            question="🏷️ ¿Qué temática elegimos para este ciclo?",
            options=options,
            is_anonymous=False,
            allows_multiple_answers=False,
        )
        db.save_poll(chat_id=msg.chat_id, message_id=msg.message_id, poll_id=msg.poll.id, poll_type="themes")
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
    try:
        poll = db.get_poll_by_id(poll_db_id)
        if not poll:
            flash("Encuesta no encontrada", "danger")
            return redirect(url_for("admin_ciclo"))

        await telegram_app.bot.stop_poll(chat_id=poll["chat_id"], message_id=poll["message_id"])
        db.close_poll(poll_db_id)

        tied = db.get_tied_themes()
        if len(tied) > 1:
            themes_list = "\n".join(f"  • <b>{hesc(t['name'])}</b>" for t in tied)
            tie_text = (
                f"⚖️ <b>¡Empate en la votación de temática!</b>\n\n"
                f"Estas temáticas han quedado empatadas con <b>{tied[0]['votes']} votos</b>:\n"
                f"{themes_list}\n\n"
                f"🔁 El admin decidirá el siguiente paso."
            )
            await send_to_group(tie_text, parse_mode="HTML", message_type="theme_tie")

            if telegram_chat_id:
                options = [t["name"][:100] for t in tied[:10]]
                tie_poll = await telegram_app.bot.send_poll(
                    chat_id=telegram_chat_id,
                    question=f"⚖️ Desempate temática: ¿cuál elegimos?",
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
            flash(f"Empate entre {len(tied)} temáticas. Encuesta de desempate lanzada.", "warning")
            return redirect(url_for("admin_ciclo"))

        # No tie → set winner theme, advance to books
        top = db.get_top_theme()
        if top:
            db.set_config("active_theme", top["name"])
            _set_phase("books")
            db.set_config("proposals_locked_for", "")
            theme_text = (
                f"🏷️ <b>Temática elegida: {hesc(top['name'])}</b>\n\n"
                f"¡Es hora de proponer libros para este ciclo!\n\n"
                f"📝 Propón con: <code>/proponer título del libro</code>\n"
                f"💡 Cuantas más propuestas tengamos, mejor será la votación."
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
            question=f"📅 ¿Cuándo nos reunimos? · {meeting['name']}",
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
            tied_opts = [o for o in tg_poll.options if o.voter_count == max_votes and max_votes > 0]
            if len(tied_opts) > 1:
                # Tiebreaker for dates
                if len(tied_opts) >= 2:
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
