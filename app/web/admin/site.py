import logging
from datetime import datetime, timezone
from html import escape as hesc

from flask import flash, redirect, render_template, request, url_for

import ai_features
import db
from app.messages import get_text

logger = logging.getLogger(__name__)

# Nombres de mes en español
_MONTHS_ES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]

PHASES = ["setup", "theme_voting", "books", "book_voting", "date_voting", "reading", "closed"]


def _suggested_cycle_name():
    now = datetime.now(timezone.utc)
    next_month = (now.month % 12) + 1
    year = now.year if next_month > 1 else now.year + 1
    return f"Lectura de {_MONTHS_ES[next_month - 1]} {year}"


def _get_phase():
    return db.get_config("cycle_phase") or "setup"


def _set_phase(phase):
    db.set_config("cycle_phase", phase)


# ─── Public page ──────────────────────────────────────────────────────────────

def render_public_page(group_invite_link):
    winner = db.get_winner_book()
    meeting = db.get_latest_scheduled_meeting()
    proposals = db.get_book_proposals()
    top_theme = db.get_top_theme()
    attendees = db.get_attendance(meeting["id"]) if meeting else []
    galeria = db.get_galeria_data(limit=3)
    invite_link = db.get_config("public_invite_link", "") or group_invite_link
    canonical_url = db.get_config("public_canonical_url", "").strip() or None
    return render_template(
        "public.html",
        winner=winner,
        meeting=meeting,
        proposals=proposals[:5],
        top_theme=top_theme,
        attendees=attendees,
        galeria=galeria,
        group_invite_link=invite_link,
        club_name=db.get_config("public_club_name", "Tribu de Libros"),
        city=db.get_config("public_city", "León, España"),
        description=db.get_config("public_description", ""),
        pub_theme=db.get_config("public_theme", "amber"),
        hero_title=db.get_config("public_hero_title", "Leemos, debatimos y crecemos."),
        section_libro=db.get_config("public_section_libro", "El libro que estamos leyendo"),
        section_reunion=db.get_config("public_section_reunion", "Próxima reunión"),
        section_propuestas=db.get_config("public_section_propuestas", "Propuestas en votación"),
        section_bot=db.get_config("public_section_bot", "¿Cómo funciona el bot?"),
        section_historia=db.get_config("public_section_historia", "Lo que hemos leído juntos"),
        join_title=db.get_config("public_join_title", "¿Te unes al club?"),
        join_body=db.get_config("public_join_body", "Somos un grupo de lectores apasionados. Únete, propón libros y queda con nosotros."),
        canonical_url=canonical_url,
    )


def handle_public_settings(require_admin, group_invite_link):
    auth = require_admin()
    if auth:
        return auth
    if request.method == "POST":
        db.set_config("public_club_name", request.form.get("club_name", "").strip() or "Tribu de Libros")
        db.set_config("public_city", request.form.get("city", "").strip() or "León, España")
        db.set_config("public_description", request.form.get("description", "").strip())
        db.set_config("public_invite_link", request.form.get("invite_link", "").strip())
        db.set_config("public_theme", request.form.get("theme", "amber"))
        db.set_config("public_hero_title", request.form.get("hero_title", "").strip() or "Leemos, debatimos y crecemos.")
        db.set_config("public_section_libro", request.form.get("section_libro", "").strip() or "El libro que estamos leyendo")
        db.set_config("public_section_reunion", request.form.get("section_reunion", "").strip() or "Próxima reunión")
        db.set_config("public_section_propuestas", request.form.get("section_propuestas", "").strip() or "Propuestas en votación")
        db.set_config("public_section_bot", request.form.get("section_bot", "").strip() or "¿Cómo funciona el bot?")
        db.set_config("public_section_historia", request.form.get("section_historia", "").strip() or "Lo que hemos leído juntos")
        db.set_config("public_join_title", request.form.get("join_title", "").strip() or "¿Te unes al club?")
        db.set_config("public_join_body", request.form.get("join_body", "").strip())
        flash("Configuración de la página pública guardada", "success")
        return redirect(url_for("admin_public_settings"))
    settings = {
        "club_name": db.get_config("public_club_name", "Tribu de Libros"),
        "city": db.get_config("public_city", "León, España"),
        "description": db.get_config("public_description", ""),
        "invite_link": db.get_config("public_invite_link", "") or group_invite_link,
        "pub_theme": db.get_config("public_theme", "amber"),
        "hero_title": db.get_config("public_hero_title", "Leemos, debatimos y crecemos."),
        "section_libro": db.get_config("public_section_libro", "El libro que estamos leyendo"),
        "section_reunion": db.get_config("public_section_reunion", "Próxima reunión"),
        "section_propuestas": db.get_config("public_section_propuestas", "Propuestas en votación"),
        "section_bot": db.get_config("public_section_bot", "¿Cómo funciona el bot?"),
        "section_historia": db.get_config("public_section_historia", "Lo que hemos leído juntos"),
        "join_title": db.get_config("public_join_title", "¿Te unes al club?"),
        "join_body": db.get_config("public_join_body", "Somos un grupo de lectores apasionados. Únete, propón libros y queda con nosotros."),
    }
    return render_template("admin_public_settings.html", **settings)


def render_admin_poster(require_admin):
    auth = require_admin()
    if auth:
        return auth
    winner = db.get_winner_book()
    meeting = db.get_latest_scheduled_meeting()
    return render_template("admin_poster.html", winner=winner, meeting=meeting)


def render_admin_help(require_admin):
    auth = require_admin()
    if auth:
        return auth
    return render_template("admin_help.html")


# ─── Cycle management ─────────────────────────────────────────────────────────

def render_admin_cycle(require_admin):
    auth = require_admin()
    if auth:
        return auth

    active_keys = db.get_active_cycle_keys()
    cycles = [db.get_cycle_state(k) for k in active_keys]

    all_cycles = db.get_all_cycle_keys()
    suggested_name = _suggested_cycle_name()

    return render_template(
        "admin_ciclo.html",
        cycles=cycles,
        all_cycles=all_cycles,
        suggested_name=suggested_name,
    )


async def activate_cycle(require_admin, send_to_group, logger, telegram_app=None, telegram_chat_id=None):
    auth = require_admin()
    if auth:
        return auth
    name = request.form.get("cycle_name", "").strip()
    if not name:
        name = _suggested_cycle_name()

    # Validate themes before creating anything
    raw_themes = request.form.get("themes", "")
    candidate_themes = []
    duplicate_inputs = []
    seen_themes = set()
    for raw_theme in raw_themes.split(","):
        theme = raw_theme.strip()
        if not theme:
            continue
        normalized = theme.casefold()
        if normalized in seen_themes:
            duplicate_inputs.append(theme)
            continue
        seen_themes.add(normalized)
        candidate_themes.append(theme)
    if len(candidate_themes) < 2:
        flash("Añade al menos 2 temáticas distintas para crear el ciclo.", "danger")
        return redirect(url_for("admin_ciclo"))

    logger.info("Admin: activando ciclo «%s» con %d temáticas", name, len(candidate_themes))
    db.add_active_cycle(name)
    db.set_config("active_theme", "")
    db.set_config(f"active_theme:{name}", "")

    # Create predefined themes
    created_theme_rows = []
    duplicate_themes = []
    failed_themes = []
    for t in candidate_themes:
        try:
            result = db.create_theme(t, created_by="admin", cycle_key=name)
            if result:
                created_theme_rows.append(result)
            else:
                duplicate_themes.append(t)
        except Exception:
            failed_themes.append(t)
            logger.exception("Error creando temática inicial «%s» para ciclo «%s»", t, name)
    created_themes = [theme["name"] for theme in created_theme_rows]
    created_theme_ids = [theme["id"] for theme in created_theme_rows]

    db.log_event("admin", f"Ciclo «{name}» activado", category="cycle", actor="admin")

    # Announce in group FIRST, then launch poll
    poll_launched = False
    try:
        themes_line = ""
        if created_themes:
            themes_line = (
                "\n\n🏷️ <b>Temáticas propuestas:</b>\n"
                + "\n".join(f"  • {hesc(t)}" for t in created_themes)
            )
        msg = (
            f"🔄 <b>¡Nuevo ciclo: {hesc(name)}!</b>\n\n"
            f"Comienza un nuevo ciclo de lectura. "
            f"Primero vamos a <b>elegir la temática</b> que guiará las propuestas."
            + themes_line
            + "\n\n📊 A continuación la encuesta de temáticas. ¡Votad!"
        )
        await send_to_group(msg, parse_mode="HTML", message_type="new_cycle")
    except Exception:
        logger.exception("Error enviando mensaje de nuevo ciclo al grupo")

    # Launch theme poll automatically if >= 2 themes were created
    if len(created_themes) >= 2 and telegram_app and telegram_chat_id:
        try:
            options = [t[:100] for t in created_themes[:10]]
            msg_poll = await telegram_app.bot.send_poll(
                chat_id=telegram_chat_id,
                question=get_text("poll_themes_question"),
                options=options,
                is_anonymous=False,
                allows_multiple_answers=False,
            )
            db.save_poll(chat_id=msg_poll.chat_id, message_id=msg_poll.message_id,
                         poll_id=msg_poll.poll.id, poll_type="themes", cycle_key=name)
            # Store option→theme_id mapping for real-time vote tracking
            import json as _json
            db.set_config(f"poll_options_{msg_poll.poll.id}", _json.dumps(created_theme_ids[:10]))
            db.set_config("cycle_phase", "theme_voting")
            poll_launched = True
        except Exception:
            logger.exception("Error lanzando encuesta de temas automáticamente")

    if duplicate_inputs:
        logger.info("Admin: ciclo «%s» ignoró %d temáticas duplicadas en el formulario", name, len(duplicate_inputs))
    themes_msg = f" con {len(created_themes)} temática{'s' if len(created_themes) != 1 else ''}" if created_themes else ""
    poll_msg = " y encuesta lanzada" if poll_launched else ""
    logger.info("Admin: ciclo «%s» activado%s%s", name, themes_msg, poll_msg)
    flash_msg = f"Ciclo «{name}» activado{themes_msg}{poll_msg}. Mensaje enviado al grupo."
    if duplicate_themes or duplicate_inputs or failed_themes:
        skipped = len(duplicate_themes) + len(duplicate_inputs) + len(failed_themes)
        flash(f"{flash_msg} Se omitieron {skipped} temática(s) repetidas o con error.", "warning")
    else:
        flash(flash_msg, "success")
    return redirect(url_for("admin_ciclo"))


def close_cycle(require_admin, logger, cycle_key=None):
    auth = require_admin()
    if auth:
        return auth
    cycle = cycle_key or request.form.get("cycle_key") or db.get_current_cycle_key()
    logger.info("Admin: cerrando ciclo «%s»", cycle)
    cycle_theme = db.get_config(f"active_theme:{cycle}") or db.get_config("active_theme") or None
    db.close_cycle(cycle)  # also calls remove_active_cycle internally
    try:
        db.auto_add_runners_up_to_waitlist(cycle_key=cycle, cycle_theme=cycle_theme)
    except Exception:
        logger.exception("Error añadiendo runners-up a la lista de espera")
    db.log_event("admin", f"Ciclo «{cycle}» cerrado", category="cycle", actor="admin")
    flash(f"Ciclo «{cycle}» cerrado. Runners-up guardados en lista de espera.", "success")
    return redirect(url_for("admin_ciclo"))


def set_cycle_theme(require_admin):
    auth = require_admin()
    if auth:
        return auth
    theme = request.form.get("active_theme", "").strip()
    cycle_key = request.form.get("cycle_key", "").strip() or db.get_current_cycle_key()
    logger.info("Admin: temática del ciclo «%s» → «%s»", cycle_key, theme or "(borrada)")
    if cycle_key == db.get_current_cycle_key():
        db.set_config("active_theme", theme)
    db.set_config(f"active_theme:{cycle_key}", theme)
    flash(f"Temática del ciclo {'actualizada a «' + theme + '»' if theme else 'borrada'}", "success")
    return redirect(url_for("admin_ciclo"))


def unlock_proposals(require_admin):
    auth = require_admin()
    if auth:
        return auth
    cycle_key = request.form.get("cycle_key") or request.form.get("cycle") or ""
    db.unlock_cycle_proposals(cycle_key or None)
    if cycle_key:
        flash(f"Propuestas desbloqueadas para el ciclo «{cycle_key}».", "success")
    else:
        flash("Propuestas desbloqueadas. Los miembros pueden volver a proponer libros.", "success")
    return redirect(url_for("admin_ciclo"))


async def pick_theme_winner(require_admin, theme_id, send_to_group_fn, logger):
    """Admin elige manualmente la temática ganadora (en caso de empate)."""
    auth = require_admin()
    if auth:
        return auth
    theme = db.get_theme_by_id(theme_id)
    if not theme:
        flash("Temática no encontrada", "danger")
        return redirect(url_for("admin_ciclo"))

    cycle_key = theme.get("cycle_key") or db.get_current_cycle_key()
    if cycle_key == db.get_current_cycle_key():
        db.set_config("active_theme", theme["name"])
    db.set_config(f"active_theme:{cycle_key}", theme["name"])
    _set_phase("books")
    db.unlock_cycle_proposals(cycle_key)
    logger.info("Admin: temática ganadora manual «%s» en ciclo=%s", theme["name"], cycle_key)

    try:
        ai_suggestion = ""
        try:
            suggestion = ai_features.suggest_book_for_theme(theme["name"])
            if suggestion:
                ai_suggestion = f"\n\n💡 <b>Sugerencia IA:</b> {hesc(suggestion)}"
        except Exception:
            pass
        text = (
            f"🏷️ <b>Temática elegida: {hesc(theme['name'])}</b>\n\n"
            f"¡Es hora de proponer libros para este ciclo!\n\n"
            f"📝 Propón con el comando /proponer"
            + ai_suggestion
            + f"\n\n💡 Cuantas más propuestas, mejor votación."
        )
        await send_to_group_fn(text, parse_mode="HTML", message_type="theme_chosen")
    except Exception:
        logger.exception("Error enviando mensaje tema ganador al grupo")

    flash(f"Temática «{theme['name']}» seleccionada. Mensaje enviado al grupo.", "success")
    return redirect(url_for("admin_ciclo"))


def rename_cycle(require_admin):
    auth = require_admin()
    if auth:
        return auth
    from flask import request
    cycle_key = request.view_args.get("cycle_key") or ""
    new_name = request.form.get("new_name", "").strip()
    if not new_name or not cycle_key:
        flash("Nombre inválido", "danger")
        return redirect(url_for("admin_ciclo"))
    if cycle_key == new_name:
        flash("El ciclo ya tiene ese nombre.", "info")
        return redirect(url_for("admin_ciclo"))
    if db.cycle_exists(new_name):
        flash(f"Ya existe un ciclo llamado «{new_name}».", "danger")
        return redirect(url_for("admin_ciclo"))
    summary = db.rename_cycle_key(cycle_key, new_name)
    logger.info("Admin: ciclo renombrado %s -> %s con resumen=%r", cycle_key, new_name, summary)
    flash(f"Ciclo renombrado a «{new_name}»", "success")
    return redirect(url_for("admin_ciclo"))


async def advance_to_books(require_admin, send_to_group_fn, logger):
    """Avanza la fase a 'books' — para cuando el admin cierra la encuesta de temas manualmente
    o cuando no hay encuesta y quiere pasar directo."""
    auth = require_admin()
    if auth:
        return auth
    cycle_key = request.form.get("cycle") or db.get_current_cycle_key()
    active_theme = db.get_config(f"active_theme:{cycle_key}") or ""
    if cycle_key == db.get_current_cycle_key():
        db.set_config("active_theme", active_theme)
    logger.info("Admin: avanzando a fase 'books' para ciclo=%s (temática activa: «%s»)", cycle_key, active_theme or "ninguna")
    _set_phase("books")
    db.unlock_cycle_proposals(cycle_key)

    try:
        theme_line = f"🏷️ Temática: <b>{hesc(active_theme)}</b>\n\n" if active_theme else ""
        text = (
            f"📚 <b>¡Hora de proponer libros!</b>\n\n"
            f"{theme_line}"
            f"Propón tus lecturas favoritas para este ciclo:\n"
            f"<code>/proponer título del libro</code>\n\n"
            f"💡 Tienes hasta que el admin cierre las propuestas."
        )
        await send_to_group_fn(text, parse_mode="HTML", message_type="books_open")
    except Exception:
        logger.exception("Error enviando mensaje apertura propuestas")

    flash("Fase de propuestas abierta. Mensaje enviado al grupo.", "success")
    return redirect(url_for("admin_ciclo"))
