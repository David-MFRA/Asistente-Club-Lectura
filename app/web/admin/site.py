from flask import flash, redirect, render_template, request, url_for

import db


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
        city=db.get_config("public_city", "Leon, Espana"),
        description=db.get_config("public_description", ""),
        pub_theme=db.get_config("public_theme", "amber"),
    )


def handle_public_settings(require_admin, group_invite_link):
    auth = require_admin()
    if auth:
        return auth
    if request.method == "POST":
        db.set_config("public_club_name", request.form.get("club_name", "").strip() or "Tribu de Libros")
        db.set_config("public_city", request.form.get("city", "").strip() or "Leon, Espana")
        db.set_config("public_description", request.form.get("description", "").strip())
        db.set_config("public_invite_link", request.form.get("invite_link", "").strip())
        db.set_config("public_theme", request.form.get("theme", "amber"))
        flash("Configuracion de la pagina publica guardada", "success")
        return redirect(url_for("admin_public_settings"))
    settings = {
        "club_name": db.get_config("public_club_name", "Tribu de Libros"),
        "city": db.get_config("public_city", "Leon, Espana"),
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


def render_admin_cycle(require_admin):
    auth = require_admin()
    if auth:
        return auth
    current_cycle = db.get_current_cycle_key()
    all_cycles = db.get_all_cycle_keys()
    books = db.get_book_proposals()
    themes = db.get_themes()
    winner = db.get_winner_book()
    return render_template(
        "admin_ciclo.html",
        current_cycle=current_cycle,
        all_cycles=all_cycles,
        books=books,
        themes=themes,
        winner=winner,
    )


def activate_cycle(require_admin):
    auth = require_admin()
    if auth:
        return auth
    name = request.form.get("cycle_name", "").strip()
    if not name:
        flash("El nombre del ciclo no puede estar vacio", "danger")
        return redirect(url_for("admin_ciclo"))
    db.set_config("active_cycle_key", name)
    db.set_config("proposals_locked_for", "")
    db.log_event("admin", f"Ciclo «{name}» activado", category="cycle", actor="admin")
    flash(f"Ciclo «{name}» activado correctamente", "success")
    return redirect(url_for("admin_ciclo"))


def close_cycle(require_admin, logger):
    auth = require_admin()
    if auth:
        return auth
    cycle = db.get_current_cycle_key()
    cycle_theme = db.get_config("active_theme") or None
    db.close_cycle(cycle)
    db.set_config("proposals_locked_for", "")
    try:
        db.auto_add_runners_up_to_waitlist(cycle_key=cycle, cycle_theme=cycle_theme)
    except Exception:
        logger.exception("Error anadiendo runners-up a la lista de espera")
    db.log_event("admin", f"Ciclo «{cycle}» cerrado", category="cycle", actor="admin")
    flash(f"Ciclo «{cycle}» cerrado. Propuestas y tematicas desactivadas.", "success")
    return redirect(url_for("admin_ciclo"))
