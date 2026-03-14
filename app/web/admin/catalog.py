import json

from flask import Response, flash, redirect, render_template, request, url_for

import db


def render_meetings(require_admin):
    auth = require_admin()
    if auth:
        return auth
    if request.method == "POST":
        name = request.form.get("meeting_name", "").strip()
        meeting_date = request.form.get("meeting_date", "").strip() or None
        location = request.form.get("location", "").strip() or None
        if not name:
            meetings_list = db.get_meetings()
            meetings_json = json.dumps(
                [
                    {
                        "id": meeting["id"],
                        "name": meeting["name"],
                        "final_date": str(meeting["final_date"])[:10] if meeting.get("final_date") else None,
                        "status": meeting.get("status", "draft"),
                    }
                    for meeting in meetings_list
                ]
            )
            return render_template(
                "meetings.html",
                meetings=meetings_list,
                meetings_json=meetings_json,
                error="Falta el nombre",
            )
        try:
            meeting = db.create_meeting(name=name, final_date=meeting_date, created_by="admin")
            if location:
                db.update_meeting(meeting_id=meeting["id"], location=location)
        except Exception:
            pass
        return redirect(url_for("meetings_admin"))

    meetings_list = db.get_meetings()
    meetings_json = json.dumps(
        [
            {
                "id": meeting["id"],
                "name": meeting["name"],
                "final_date": str(meeting["final_date"])[:10] if meeting.get("final_date") else None,
                "status": meeting.get("status", "draft"),
            }
            for meeting in meetings_list
        ]
    )
    return render_template("meetings.html", meetings=meetings_list, meetings_json=meetings_json)


def render_themes(require_admin):
    auth = require_admin()
    if auth:
        return auth
    return render_template("themes.html", themes=db.get_themes())


def render_ranking(require_admin):
    auth = require_admin()
    if auth:
        return auth
    return render_template("ranking.html", ranking=db.get_book_ranking())


def render_meeting_detail(require_admin, meeting_id):
    auth = require_admin()
    if auth:
        return auth
    meeting = db.get_meeting(meeting_id)
    if not meeting:
        return "Reunion no encontrada", 404
    attendees = db.get_attendance(meeting_id)
    date_options = db.get_meeting_date_options(meeting_id)
    open_poll = db.get_open_poll(poll_type="dates", meeting_id=meeting_id)
    return render_template(
        "meeting_detail.html",
        meeting=meeting,
        attendees=attendees,
        date_options=date_options,
        open_poll=open_poll,
    )


def update_meeting(require_admin, meeting_id):
    auth = require_admin()
    if auth:
        return auth
    name = request.form.get("name", "").strip()
    final_date = request.form.get("final_date", "").strip() or None
    summary = request.form.get("summary", "").strip() or None
    status = request.form.get("status", "").strip() or None
    location = request.form.get("location", "").strip() or None
    notes = request.form.get("notes", "").strip() or None
    db.update_meeting(
        meeting_id=meeting_id,
        name=name or None,
        final_date=final_date,
        summary=summary,
        status=status,
        location=location,
        notes=notes,
    )
    return redirect(url_for("meeting_detail_admin", meeting_id=meeting_id))


def delete_meeting(require_admin, meeting_id):
    auth = require_admin()
    if auth:
        return auth
    db.delete_meeting(meeting_id)
    return redirect(url_for("meetings_admin"))


def add_meeting_date_option(require_admin, meeting_id):
    auth = require_admin()
    if auth:
        return auth
    option_date = request.form.get("option_date", "").strip()
    if not option_date:
        return "Fecha obligatoria", 400
    db.add_meeting_date_option(meeting_id, option_date)
    return redirect(url_for("meeting_detail_admin", meeting_id=meeting_id))


def close_meeting_date(require_admin, meeting_id):
    auth = require_admin()
    if auth:
        return auth
    final_date = request.form.get("final_date", "").strip()
    if not final_date:
        return "Fecha obligatoria", 400
    db.set_meeting_final_date(meeting_id, final_date)
    return redirect(url_for("meeting_detail_admin", meeting_id=meeting_id))


def create_meeting(require_admin, logger):
    auth = require_admin()
    if auth:
        return auth
    name = request.form.get("meeting_name", "").strip()
    meeting_date = request.form.get("meeting_date", "").strip() or None
    location = request.form.get("location", "").strip() or None
    if not name:
        return "Falta el nombre", 400
    try:
        meeting = db.create_meeting(name=name, final_date=meeting_date, created_by="admin")
        if location:
            db.update_meeting(meeting_id=meeting["id"], location=location)
        return redirect(url_for("meetings_admin"))
    except Exception:
        logger.exception("Error creando reunion")
        return "Error creando reunion", 500


def export_books(require_admin):
    auth = require_admin()
    if auth:
        return auth
    rows = db.get_books()
    text = "id,title,author,votes\n"
    for row in rows:
        text += f'{row["id"]},"{row["title"]}","{row.get("author","") or ""}",{row["votes"]}\n'
    return Response(
        text,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=club_lectura_books.csv"},
    )


def render_close_voting(require_admin):
    auth = require_admin()
    if auth:
        return auth
    winner = db.get_winner_book()
    if not winner:
        return "No hay libros propuestos", 404
    return f"Libro ganador actual: {winner['title']} ({winner['votes']} votos)"


def render_attendance(require_admin):
    auth = require_admin()
    if auth:
        return auth
    latest_meeting = db.get_latest_meeting()
    if not latest_meeting:
        return render_template("attendance.html", meeting=None, attendees=[])
    attendees = db.get_attendance(latest_meeting["id"])
    return render_template("attendance.html", meeting=latest_meeting, attendees=attendees)


def render_history(require_admin):
    auth = require_admin()
    if auth:
        return auth
    return render_template(
        "admin_historico.html",
        books_history=db.get_all_books_history(),
        themes_history=db.get_all_themes_history(),
        polls_history=db.get_all_polls_history(),
        meetings_history=db.get_all_meetings_history(),
    )


def render_gallery(require_admin):
    auth = require_admin()
    if auth:
        return auth
    meetings = db.get_galeria_data()
    return render_template("admin_galeria.html", meetings=meetings)


def save_gallery_notes(require_admin, meeting_id):
    auth = require_admin()
    if auth:
        return auth
    notes = request.form.get("notes", "").strip() or None
    summary = request.form.get("summary", "").strip() or None
    db.update_meeting(meeting_id=meeting_id, notes=notes, summary=summary)
    flash("Notas guardadas", "success")
    return redirect(url_for("admin_galeria"))


def render_admin_db(require_admin, logger):
    auth = require_admin()
    if auth:
        return auth
    tables = db.get_table_names()
    table = request.args.get("table", "books")
    if table not in tables:
        table = tables[0]
    try:
        cols, rows = db.get_table_rows(table)
    except Exception:
        logger.exception("Error cargando tabla")
        cols, rows = [], []
    return render_template("admin_db.html", tables=tables, table=table, cols=cols, rows=rows)


def delete_db_row(require_admin, logger, table, row_id):
    auth = require_admin()
    if auth:
        return auth
    try:
        db.delete_table_row(table, row_id)
    except Exception:
        logger.exception("Error borrando fila en tabla %s", table)
    return redirect(url_for("admin_db", table=table))


def truncate_db_table(require_admin, logger, table):
    auth = require_admin()
    if auth:
        return auth
    try:
        db.truncate_table(table)
    except Exception:
        logger.exception("Error vaciando tabla %s", table)
    return redirect(url_for("admin_db", table=table))


def edit_book(require_admin, logger, book_id):
    auth = require_admin()
    if auth:
        return auth
    title = request.form.get("title", "").strip() or None
    author = request.form.get("author", "").strip() or None
    description = request.form.get("description", "").strip() or None
    pages = request.form.get("pages", "").strip() or None
    cover = request.form.get("cover", "").strip() or None
    try:
        db.update_book(book_id, title=title, author=author, description=description, pages=pages, cover=cover)
        flash("Libro actualizado correctamente", "success")
    except Exception:
        logger.exception("Error editando libro")
        flash("Error actualizando el libro", "danger")
    return redirect(url_for("admin_dashboard"))


def render_waitlist(require_admin):
    auth = require_admin()
    if auth:
        return auth
    theme_filter = request.args.get("theme", "")
    waitlist = db.get_waitlist(theme=theme_filter if theme_filter else None)
    themes = db.get_waitlist_themes()
    winner = db.get_winner_book()
    books = db.get_book_proposals()
    return render_template(
        "admin_waitlist.html",
        waitlist=waitlist,
        themes=themes,
        theme_filter=theme_filter,
        winner=winner,
        books=books,
    )


def add_waitlist_entry(require_admin):
    auth = require_admin()
    if auth:
        return auth
    book_id = request.form.get("book_id", type=int)
    cycle_theme = request.form.get("cycle_theme", "").strip() or None
    notes = request.form.get("notes", "").strip() or None
    if not book_id:
        flash("Falta el ID del libro", "danger")
        return redirect(url_for("admin_waitlist"))
    cycle_key = db.get_current_cycle_key()
    db.add_to_waitlist(book_id=book_id, cycle_key=cycle_key, cycle_theme=cycle_theme, added_by="admin", notes=notes)
    flash("Libro anadido a la lista de espera", "success")
    return redirect(url_for("admin_waitlist"))


def delete_waitlist_entry(require_admin, wl_id):
    auth = require_admin()
    if auth:
        return auth
    db.remove_from_waitlist(wl_id)
    flash("Eliminado de la lista de espera", "success")
    return redirect(url_for("admin_waitlist"))


async def suggest_waitlist_to_group(require_admin, send_to_group):
    auth = require_admin()
    if auth:
        return auth
    theme = request.form.get("theme", "").strip()
    books = db.get_waitlist(theme=theme if theme else None)
    if not books:
        flash("No hay libros en la lista de espera para esa tematica", "warning")
        return redirect(url_for("admin_waitlist"))
    lines = ["📚 Lista de espera del club\n"]
    if theme:
        lines[0] = f"📚 Lista de espera - tematica: {theme}\n"
    for index, book in enumerate(books[:10], 1):
        line = f"{index}. {book['title']}" + (f" - {book['author']}" if book.get("author") else "")
        if book.get("votes_at_time"):
            line += f" ({book['votes_at_time']} votos en su ciclo)"
        lines.append(line)
    lines.append("\n¿Alguno de estos te apetece releer o proponer?")
    await send_to_group("\n".join(lines), parse_mode=None)
    flash("Sugerencias enviadas al grupo", "success")
    return redirect(url_for("admin_waitlist"))
