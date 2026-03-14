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
    current_cycle = db.get_current_cycle_key()
    all_cycles = db.get_all_cycle_keys()
    books = db.get_book_proposals()
    themes = db.get_themes()
    winner = db.get_winner_book()
    phase = _get_phase()

    proposals_locked_for = db.get_config("proposals_locked_for") or ""
    locked_cycles = {c.strip() for c in proposals_locked_for.split(",") if c.strip()}
    is_locked = current_cycle in locked_cycles
    active_theme = db.get_config("active_theme") or ""

    open_theme_poll = db.get_open_poll(poll_type="themes")
    open_book_poll = db.get_open_poll(poll_type="books")
    meeting = db.get_latest_scheduled_meeting()
    tied_themes = db.get_tied_themes()
    tied_books = db.get_tied_books()
    suggested_name = _suggested_cycle_name()

    return render_template(
        "admin_ciclo.html",
        current_cycle=current_cycle,
        all_cycles=all_cycles,
        books=books,
        themes=themes,
        winner=winner,
        phase=phase,
        is_locked=is_locked,
        active_theme=active_theme,
        open_theme_poll=open_theme_poll,
        open_book_poll=open_book_poll,
        meeting=meeting,
        tied_themes=tied_themes,
        tied_books=tied_books,
        suggested_name=suggested_name,
    )


def activate_cycle(require_admin):
    auth = require_admin()
    if auth:
        return auth
    name = request.form.get("cycle_name", "").strip()
    if not name:
        name = _suggested_cycle_name()
    db.set_config("active_cycle_key", name)
    db.set_config("proposals_locked_for", "")
    db.set_config("active_theme", "")
    _set_phase("setup")
    db.log_event("admin", f"Ciclo «{name}» activado", category="cycle", actor="admin")
    flash(f"Ciclo «{name}» activado. Ahora añade las temáticas y lanza la encuesta.", "success")
    return redirect(url_for("admin_ciclo"))


def close_cycle(require_admin, logger):
    auth = require_admin()
    if auth:
        return auth
    cycle = db.get_current_cycle_key()
    cycle_theme = db.get_config("active_theme") or None
    db.close_cycle(cycle)
    db.set_config("proposals_locked_for", "")
    _set_phase("closed")
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
