import json
import logging
from datetime import datetime, timezone
from html import escape as hesc

from flask import flash, redirect, render_template, request, url_for

import ai_features
import db
from app.messages import get_text
from app.services.admin_audit import prepare_admin_audit
from app.services.bot_context import get_contextual_commands

logger = logging.getLogger(__name__)

_MONTHS_ES = [
    "Enero",
    "Febrero",
    "Marzo",
    "Abril",
    "Mayo",
    "Junio",
    "Julio",
    "Agosto",
    "Septiembre",
    "Octubre",
    "Noviembre",
    "Diciembre",
]

PHASES = ["setup", "theme_voting", "books", "book_voting", "date_voting", "reading", "closed"]


def _suggested_cycle_name():
    now = datetime.now(timezone.utc)
    next_month = (now.month % 12) + 1
    year = now.year if next_month > 1 else now.year + 1
    return f"Lectura de {_MONTHS_ES[next_month - 1]} {year}"


def _set_phase(phase):
    db.set_config("cycle_phase", phase)


def _public_settings_snapshot(group_invite_link):
    return {
        "club_name": db.get_config("public_club_name", "Tribu de Libros"),
        "city": db.get_config("public_city", "Leon, Espana"),
        "description": db.get_config("public_description", ""),
        "invite_link": db.get_config("public_invite_link", "") or group_invite_link,
        "pub_theme": db.get_config("public_theme", "amber"),
        "hero_title": db.get_config("public_hero_title", "Leemos, debatimos y crecemos."),
        "section_libro": db.get_config("public_section_libro", "El libro que estamos leyendo"),
        "section_reunion": db.get_config("public_section_reunion", "Proxima reunion"),
        "section_propuestas": db.get_config("public_section_propuestas", "Propuestas en votacion"),
        "section_bot": db.get_config("public_section_bot", "Como funciona el bot?"),
        "section_historia": db.get_config("public_section_historia", "Lo que hemos leido juntos"),
        "join_title": db.get_config("public_join_title", "Te unes al club?"),
        "join_body": db.get_config("public_join_body", "Somos un grupo de lectores apasionados. Unete, propon libros y queda con nosotros."),
    }


def render_public_page(group_invite_link):
    current_cycle = db.get_current_cycle_key()
    winner = db.get_winner_book(current_cycle)
    meeting = db.get_latest_scheduled_meeting(cycle_key=current_cycle)
    proposals = db.get_book_proposals(current_cycle)
    top_theme = db.get_top_theme(current_cycle)
    attendees = db.get_attendance(meeting["id"]) if meeting else []
    galeria = db.get_galeria_data(limit=3)
    invite_link = db.get_config("public_invite_link", "") or group_invite_link
    canonical_url = db.get_config("public_canonical_url", "").strip() or "https://asistente-club-lectura-1.onrender.com"
    default_description = (
        "Club de lectura mensual en Leon. Elegimos libros juntos, debatimos y quedamos "
        "en persona cada mes. Unete gratis y propon el proximo libro."
    )
    settings = _public_settings_snapshot(group_invite_link)
    settings["description"] = settings["description"] or default_description
    public_commands = get_contextual_commands("private", cycle_key=current_cycle, is_admin=False)[:6]
    return render_template(
        "public.html",
        winner=winner,
        meeting=meeting,
        proposals=proposals[:5],
        top_theme=top_theme,
        attendees=attendees,
        galeria=galeria,
        group_invite_link=invite_link,
        canonical_url=canonical_url,
        og_image=(winner or {}).get("cover"),
        public_commands=public_commands,
        current_cycle=current_cycle,
        **settings,
    )


def handle_public_settings(require_admin, group_invite_link):
    auth = require_admin()
    if auth:
        return auth
    if request.method == "POST":
        before = _public_settings_snapshot(group_invite_link)
        db.set_config("public_club_name", request.form.get("club_name", "").strip() or "Tribu de Libros")
        db.set_config("public_city", request.form.get("city", "").strip() or "Leon, Espana")
        db.set_config("public_description", request.form.get("description", "").strip())
        db.set_config("public_invite_link", request.form.get("invite_link", "").strip())
        db.set_config("public_theme", request.form.get("theme", "amber"))
        db.set_config("public_hero_title", request.form.get("hero_title", "").strip() or "Leemos, debatimos y crecemos.")
        db.set_config("public_section_libro", request.form.get("section_libro", "").strip() or "El libro que estamos leyendo")
        db.set_config("public_section_reunion", request.form.get("section_reunion", "").strip() or "Proxima reunion")
        db.set_config("public_section_propuestas", request.form.get("section_propuestas", "").strip() or "Propuestas en votacion")
        db.set_config("public_section_bot", request.form.get("section_bot", "").strip() or "Como funciona el bot?")
        db.set_config("public_section_historia", request.form.get("section_historia", "").strip() or "Lo que hemos leido juntos")
        db.set_config("public_join_title", request.form.get("join_title", "").strip() or "Te unes al club?")
        db.set_config("public_join_body", request.form.get("join_body", "").strip())
        after = _public_settings_snapshot(group_invite_link)
        prepare_admin_audit(
            action="public_settings_update",
            target_type="public_page",
            target_id="main",
            before=before,
            after=after,
        )
        flash("Configuracion de la pagina publica guardada", "success")
        return redirect(url_for("admin_public_settings"))
    return render_template("admin_public_settings.html", **_public_settings_snapshot(group_invite_link))


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


def render_admin_cycle(require_admin):
    auth = require_admin()
    if auth:
        return auth

    active_keys = db.get_active_cycle_keys()
    cycles = [db.get_cycle_state(key) for key in active_keys]
    return render_template(
        "admin_ciclo.html",
        cycles=cycles,
        all_cycles=db.get_all_cycle_keys(),
        suggested_name=_suggested_cycle_name(),
    )


async def activate_cycle(require_admin, send_to_group, logger, telegram_app=None, telegram_chat_id=None):
    auth = require_admin()
    if auth:
        return auth

    name = request.form.get("cycle_name", "").strip() or _suggested_cycle_name()
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
        flash("Anade al menos 2 tematicas distintas para crear el ciclo.", "danger")
        return redirect(url_for("admin_ciclo"))

    before_cycles = db.get_active_cycle_keys()
    logger.info("Admin: activando ciclo '%s' con %d tematicas", name, len(candidate_themes))
    db.add_active_cycle(name)
    db.set_config("active_theme", "")
    db.set_config(f"active_theme:{name}", "")

    created_theme_rows = []
    duplicate_themes = []
    failed_themes = []
    for theme_name in candidate_themes:
        try:
            row = db.create_theme(theme_name, created_by="admin", cycle_key=name)
            if row:
                created_theme_rows.append(row)
            else:
                duplicate_themes.append(theme_name)
        except Exception:
            failed_themes.append(theme_name)
            logger.exception("Error creando tematica inicial '%s' para ciclo '%s'", theme_name, name)

    created_themes = [theme["name"] for theme in created_theme_rows]
    created_theme_ids = [theme["id"] for theme in created_theme_rows]
    db.log_event("admin", f"Ciclo '{name}' activado", category="cycle", actor="admin")

    poll_launched = False
    try:
        themes_line = ""
        if created_themes:
            themes_line = "\n\n🏷️ <b>Tematicas propuestas:</b>\n" + "\n".join(f"  • {hesc(item)}" for item in created_themes)
        msg = (
            f"🔄 <b>Nuevo ciclo: {hesc(name)}</b>\n\n"
            "Comienza un nuevo ciclo de lectura. Primero vamos a <b>elegir la tematica</b> "
            "que guiara las propuestas."
            f"{themes_line}\n\n📊 A continuacion la encuesta de tematicas. Votad."
        )
        await send_to_group(msg, parse_mode="HTML", message_type="new_cycle")
    except Exception:
        logger.exception("Error enviando mensaje de nuevo ciclo al grupo")

    if len(created_themes) >= 2 and telegram_app and telegram_chat_id:
        try:
            msg_poll = await telegram_app.bot.send_poll(
                chat_id=telegram_chat_id,
                question=get_text("poll_themes_question", audience="group", phase="theme_voting", cycle_key=name),
                options=[item[:100] for item in created_themes[:10]],
                is_anonymous=False,
                allows_multiple_answers=False,
            )
            db.save_poll(
                chat_id=msg_poll.chat_id,
                message_id=msg_poll.message_id,
                poll_id=msg_poll.poll.id,
                poll_type="themes",
                cycle_key=name,
            )
            db.set_config(f"poll_options_{msg_poll.poll.id}", json.dumps(created_theme_ids[:10]))
            db.set_config("cycle_phase", "theme_voting")
            poll_launched = True
        except Exception:
            logger.exception("Error lanzando encuesta de temas automaticamente")

    themes_msg = f" con {len(created_themes)} tematica(s)" if created_themes else ""
    poll_msg = " y encuesta lanzada" if poll_launched else ""
    flash_msg = f"Ciclo '{name}' activado{themes_msg}{poll_msg}. Mensaje enviado al grupo."
    if duplicate_themes or duplicate_inputs or failed_themes:
        skipped = len(duplicate_themes) + len(duplicate_inputs) + len(failed_themes)
        flash(f"{flash_msg} Se omitieron {skipped} tematica(s) repetidas o con error.", "warning")
    else:
        flash(flash_msg, "success")

    prepare_admin_audit(
        action="cycle_activate",
        target_type="cycle",
        target_id=name,
        before={"active_cycles": before_cycles},
        after={
            "active_cycles": db.get_active_cycle_keys(),
            "created_themes": created_themes,
            "poll_launched": poll_launched,
        },
    )
    return redirect(url_for("admin_ciclo"))


def close_cycle(require_admin, logger, cycle_key=None):
    auth = require_admin()
    if auth:
        return auth
    cycle = cycle_key or request.form.get("cycle_key") or db.get_current_cycle_key()
    before_cycles = db.get_active_cycle_keys()
    cycle_theme = db.get_config(f"active_theme:{cycle}") or db.get_config("active_theme") or None
    logger.info("Admin: cerrando ciclo '%s'", cycle)
    db.close_cycle(cycle)
    try:
        db.auto_add_runners_up_to_waitlist(cycle_key=cycle, cycle_theme=cycle_theme)
    except Exception:
        logger.exception("Error anadiendo runners-up a la lista de espera")
    db.log_event("admin", f"Ciclo '{cycle}' cerrado", category="cycle", actor="admin")
    prepare_admin_audit(
        action="cycle_close",
        target_type="cycle",
        target_id=cycle,
        before={"active_cycles": before_cycles, "cycle_theme": cycle_theme},
        after={"active_cycles": db.get_active_cycle_keys()},
    )
    flash(f"Ciclo '{cycle}' cerrado. Runners-up guardados en lista de espera.", "success")
    return redirect(url_for("admin_ciclo"))


def set_cycle_theme(require_admin):
    auth = require_admin()
    if auth:
        return auth
    theme = request.form.get("active_theme", "").strip()
    cycle_key = request.form.get("cycle_key", "").strip() or db.get_current_cycle_key()
    before = {
        "active_theme": db.get_config(f"active_theme:{cycle_key}") or "",
        "global_active_theme": db.get_config("active_theme") or "",
    }
    logger.info("Admin: tematica del ciclo '%s' -> '%s'", cycle_key, theme or "(borrada)")
    if cycle_key == db.get_current_cycle_key():
        db.set_config("active_theme", theme)
    db.set_config(f"active_theme:{cycle_key}", theme)
    after = {
        "active_theme": db.get_config(f"active_theme:{cycle_key}") or "",
        "global_active_theme": db.get_config("active_theme") or "",
    }
    prepare_admin_audit(
        action="cycle_theme_set",
        target_type="cycle",
        target_id=cycle_key,
        before=before,
        after=after,
    )
    flash(f"Tematica del ciclo {'actualizada a ' + theme if theme else 'borrada'}", "success")
    return redirect(url_for("admin_ciclo"))


def unlock_proposals(require_admin):
    auth = require_admin()
    if auth:
        return auth
    cycle_key = request.form.get("cycle_key") or request.form.get("cycle") or ""
    before = {"locked_cycles": db.get_locked_cycle_keys()}
    db.unlock_cycle_proposals(cycle_key or None)
    prepare_admin_audit(
        action="cycle_unlock_proposals",
        target_type="cycle" if cycle_key else "global",
        target_id=cycle_key or "all",
        before=before,
        after={"locked_cycles": db.get_locked_cycle_keys()},
    )
    if cycle_key:
        flash(f"Propuestas desbloqueadas para el ciclo '{cycle_key}'.", "success")
    else:
        flash("Propuestas desbloqueadas. Los miembros pueden volver a proponer libros.", "success")
    return redirect(url_for("admin_ciclo"))


async def pick_theme_winner(require_admin, theme_id, send_to_group_fn, logger):
    auth = require_admin()
    if auth:
        return auth
    theme = db.get_theme_by_id(theme_id)
    if not theme:
        flash("Tematica no encontrada", "danger")
        return redirect(url_for("admin_ciclo"))

    cycle_key = theme.get("cycle_key") or db.get_current_cycle_key()
    before = {
        "active_theme": db.get_config(f"active_theme:{cycle_key}") or "",
        "locked_cycles": db.get_locked_cycle_keys(),
    }
    if cycle_key == db.get_current_cycle_key():
        db.set_config("active_theme", theme["name"])
    db.set_config(f"active_theme:{cycle_key}", theme["name"])
    _set_phase("books")
    db.unlock_cycle_proposals(cycle_key)
    logger.info("Admin: tematica ganadora manual '%s' en ciclo=%s", theme["name"], cycle_key)

    try:
        ai_suggestion = ""
        try:
            suggestion = ai_features.suggest_book_for_theme(theme["name"])
            if suggestion:
                ai_suggestion = f"\n\n💡 <b>Sugerencia IA:</b> {hesc(suggestion)}"
        except Exception:
            pass
        text = (
            f"🏷️ <b>Tematica elegida: {hesc(theme['name'])}</b>\n\n"
            "Es hora de proponer libros para este ciclo.\n\n"
            "📝 Propon con el comando /proponer"
            f"{ai_suggestion}\n\n💡 Cuantas mas propuestas, mejor votacion."
        )
        await send_to_group_fn(text, parse_mode="HTML", message_type="theme_chosen")
    except Exception:
        logger.exception("Error enviando mensaje tema ganador al grupo")

    prepare_admin_audit(
        action="cycle_pick_theme",
        target_type="theme",
        target_id=theme_id,
        before=before,
        after={
            "active_theme": db.get_config(f"active_theme:{cycle_key}") or "",
            "locked_cycles": db.get_locked_cycle_keys(),
        },
    )
    flash(f"Tematica '{theme['name']}' seleccionada. Mensaje enviado al grupo.", "success")
    return redirect(url_for("admin_ciclo"))


def rename_cycle(require_admin):
    auth = require_admin()
    if auth:
        return auth
    cycle_key = request.view_args.get("cycle_key") or ""
    new_name = request.form.get("new_name", "").strip()
    if not new_name or not cycle_key:
        flash("Nombre invalido", "danger")
        return redirect(url_for("admin_ciclo"))
    if cycle_key == new_name:
        flash("El ciclo ya tiene ese nombre.", "info")
        return redirect(url_for("admin_ciclo"))
    if db.cycle_exists(new_name):
        flash(f"Ya existe un ciclo llamado '{new_name}'.", "danger")
        return redirect(url_for("admin_ciclo"))
    summary = db.rename_cycle_key(cycle_key, new_name)
    prepare_admin_audit(
        action="cycle_rename",
        target_type="cycle",
        target_id=cycle_key,
        before={"cycle_key": cycle_key},
        after={"cycle_key": new_name, "summary": summary},
    )
    logger.info("Admin: ciclo renombrado %s -> %s con resumen=%r", cycle_key, new_name, summary)
    flash(f"Ciclo renombrado a '{new_name}'", "success")
    return redirect(url_for("admin_ciclo"))


async def advance_to_books(require_admin, send_to_group_fn, logger):
    auth = require_admin()
    if auth:
        return auth
    cycle_key = request.form.get("cycle") or db.get_current_cycle_key()
    active_theme = db.get_config(f"active_theme:{cycle_key}") or ""
    before = {
        "active_theme": active_theme,
        "locked_cycles": db.get_locked_cycle_keys(),
    }
    if cycle_key == db.get_current_cycle_key():
        db.set_config("active_theme", active_theme)
    logger.info("Admin: avanzando a fase books para ciclo=%s", cycle_key)
    _set_phase("books")
    db.unlock_cycle_proposals(cycle_key)

    try:
        theme_line = f"🏷️ Tematica: <b>{hesc(active_theme)}</b>\n\n" if active_theme else ""
        text = (
            "📚 <b>Hora de proponer libros</b>\n\n"
            f"{theme_line}"
            "Propon tus lecturas favoritas para este ciclo:\n"
            "<code>/proponer titulo del libro</code>\n\n"
            "💡 Tienes hasta que el admin cierre las propuestas."
        )
        await send_to_group_fn(text, parse_mode="HTML", message_type="books_open")
    except Exception:
        logger.exception("Error enviando mensaje apertura propuestas")

    prepare_admin_audit(
        action="cycle_advance_books",
        target_type="cycle",
        target_id=cycle_key,
        before=before,
        after={
            "active_theme": db.get_config(f"active_theme:{cycle_key}") or "",
            "locked_cycles": db.get_locked_cycle_keys(),
        },
    )
    flash("Fase de propuestas abierta. Mensaje enviado al grupo.", "success")
    return redirect(url_for("admin_ciclo"))
