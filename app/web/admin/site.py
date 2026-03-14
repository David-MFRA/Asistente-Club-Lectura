from datetime import datetime, timezone
from html import escape as hesc

from flask import flash, redirect, render_template, request, url_for

import db

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
        flash("Configuración de la página pública guardada", "success")
        return redirect(url_for("admin_public_settings"))
    settings = {
        "club_name": db.get_config("public_club_name", "Tribu de Libros"),
        "city": db.get_config("public_city", "León, España"),
        "description": db.get_config("public_description", ""),
        "invite_link": db.get_config("public_invite_link", "") or group_invite_link,
        "pub_theme": db.get_config("public_theme", "amber"),
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


async def activate_cycle(require_admin, send_to_group, logger):
    auth = require_admin()
    if auth:
        return auth
    name = request.form.get("cycle_name", "").strip()
    if not name:
        name = _suggested_cycle_name()

    db.add_active_cycle(name)

    # Create predefined themes if provided
    raw_themes = request.form.get("themes", "")
    created_themes = []
    for t in raw_themes.split(","):
        t = t.strip()
        if t:
            try:
                db.create_theme(t, created_by="admin", cycle_key=name)
                created_themes.append(t)
            except Exception:
                pass

    db.log_event("admin", f"Ciclo «{name}» activado", category="cycle", actor="admin")

    # Announce in group
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
            + "\n\n📊 Pronto se abrirá la encuesta de temáticas. ¡Estad atentos!"
        )
        await send_to_group(msg, parse_mode="HTML", message_type="new_cycle")
    except Exception:
        logger.exception("Error enviando mensaje de nuevo ciclo al grupo")

    themes_msg = f" con {len(created_themes)} temática{'s' if len(created_themes) != 1 else ''}" if created_themes else ""
    flash(f"Ciclo «{name}» activado{themes_msg}. Mensaje enviado al grupo.", "success")
    return redirect(url_for("admin_ciclo"))


def close_cycle(require_admin, logger, cycle_key=None):
    auth = require_admin()
    if auth:
        return auth
    cycle = cycle_key or request.form.get("cycle_key") or db.get_current_cycle_key()
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
    db.set_config("active_theme", theme)
    flash(f"Temática del ciclo {'actualizada a «' + theme + '»' if theme else 'borrada'}", "success")
    return redirect(url_for("admin_ciclo"))


def unlock_proposals(require_admin):
    auth = require_admin()
    if auth:
        return auth
    db.set_config("proposals_locked_for", "")
    flash("Propuestas desbloqueadas. Los miembros pueden volver a proponer libros.", "success")
    return redirect(url_for("admin_ciclo"))


async def pick_theme_winner(require_admin, theme_id, send_to_group_fn, logger):
    """Admin elige manualmente la temática ganadora (en caso de empate)."""
    auth = require_admin()
    if auth:
        return auth
    theme = None
    for t in db.get_themes():
        if t["id"] == theme_id:
            theme = t
            break
    if not theme:
        flash("Temática no encontrada", "danger")
        return redirect(url_for("admin_ciclo"))

    db.set_config("active_theme", theme["name"])
    _set_phase("books")
    db.set_config("proposals_locked_for", "")

    try:
        text = (
            f"🏷️ <b>Temática elegida: {hesc(theme['name'])}</b>\n\n"
            f"¡Es hora de proponer libros para este ciclo!\n\n"
            f"📝 Propón con: <code>/proponer título del libro</code>\n"
            f"💡 Cuantas más propuestas, mejor votación."
        )
        await send_to_group_fn(text, parse_mode="HTML", message_type="theme_chosen")
    except Exception:
        logger.exception("Error enviando mensaje tema ganador al grupo")

    flash(f"Temática «{theme['name']}» seleccionada. Mensaje enviado al grupo.", "success")
    return redirect(url_for("admin_ciclo"))


async def advance_to_books(require_admin, send_to_group_fn, logger):
    """Avanza la fase a 'books' — para cuando el admin cierra la encuesta de temas manualmente
    o cuando no hay encuesta y quiere pasar directo."""
    auth = require_admin()
    if auth:
        return auth
    active_theme = db.get_config("active_theme") or ""
    _set_phase("books")
    db.set_config("proposals_locked_for", "")

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
