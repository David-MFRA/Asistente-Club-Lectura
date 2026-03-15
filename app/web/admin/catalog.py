import json
import logging

from flask import Response, flash, redirect, render_template, request, url_for

import db
from app.services.admin_audit import prepare_admin_audit

logger = logging.getLogger(__name__)


def _build_db_editor_columns(columns, row, pk_column):
    prepared = []
    for column in columns:
        name = column["name"]
        value = row.get(name) if row else None
        prepared.append(
            {
                **column,
                "is_primary_key": name == pk_column,
                "form_value": db.format_table_value_for_form(value),
                "is_null": value is None,
                "textarea_rows": 8 if column["is_json"] or column["is_array"] else 4,
            }
        )
    return prepared


def _meetings_context(meetings_list):
    """Builds shared context dict for the meetings template."""
    active_cycles = db.get_active_cycle_keys()
    current_cycle = db.get_current_cycle_key()
    winner_by_cycle = {ck: db.get_winner_book(ck) for ck in active_cycles}
    meetings_json = json.dumps(
        [
            {
                "id": m["id"],
                "name": m["name"],
                "final_date": str(m["final_date"])[:10] if m.get("final_date") else None,
                "status": m.get("status", "draft"),
                "cycle_key": m.get("cycle_key", ""),
            }
            for m in meetings_list
        ]
    )
    return dict(
        meetings=meetings_list,
        meetings_json=meetings_json,
        active_cycles=active_cycles,
        current_cycle=current_cycle,
        winner_by_cycle=winner_by_cycle,
    )


def render_meetings(require_admin):
    auth = require_admin()
    if auth:
        return auth

    cycle_filter = request.args.get("cycle", "").strip() or None

    if request.method == "POST":
        name = request.form.get("meeting_name", "").strip()
        meeting_date = request.form.get("meeting_date", "").strip() or None
        location = request.form.get("location", "").strip() or None
        cycle_key = request.form.get("cycle", "").strip() or None

        if not name:
            meetings_list = db.get_meetings(cycle_key=cycle_filter)
            ctx = _meetings_context(meetings_list)
            ctx["error"] = "Falta el nombre"
            ctx["cycle_filter"] = cycle_filter
            return render_template("meetings.html", **ctx)

        try:
            # Auto-associate winner book if the chosen cycle has one
            book_id = None
            effective_cycle = cycle_key or db.get_current_cycle_key()
            winner = db.get_winner_book(effective_cycle)
            if winner:
                book_id = winner["id"]

            meeting = db.create_meeting(
                name=name,
                final_date=meeting_date,
                cycle_key=cycle_key,
                book_id=book_id,
                created_by="admin",
            )
            if location:
                db.update_meeting(meeting_id=meeting["id"], location=location)
            logger.info(
                "Admin: reunión «%s» creada (id=%d) ciclo=%s book_id=%s",
                name, meeting["id"], effective_cycle, book_id,
            )
            if winner:
                flash(f"Reunión «{name}» creada y libro «{winner['title']}» asignado automáticamente", "success")
            else:
                flash(f"Reunión «{name}» creada (ciclo: {effective_cycle})", "success")
        except Exception:
            logger.exception("Error creando reunión «%s»", name)
            flash("Error creando la reunión", "danger")
        return redirect(url_for("meetings_admin"))

    meetings_list = db.get_meetings(cycle_key=cycle_filter)
    ctx = _meetings_context(meetings_list)
    ctx["cycle_filter"] = cycle_filter
    return render_template("meetings.html", **ctx)


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
    cycle_winner = db.get_winner_book(meeting.get("cycle_key"))
    return render_template(
        "meeting_detail.html",
        meeting=meeting,
        attendees=attendees,
        date_options=date_options,
        open_poll=open_poll,
        cycle_winner=cycle_winner,
    )


def update_meeting(require_admin, meeting_id):
    auth = require_admin()
    if auth:
        return auth
    logger.info("Admin: actualizando reunión meeting_id=%d", meeting_id)
    name = request.form.get("name", "").strip()
    final_date = request.form.get("final_date", "").strip() or None
    summary = request.form.get("summary", "").strip() or None
    status = request.form.get("status", "").strip() or None
    location = request.form.get("location", "").strip() or None
    notes = request.form.get("notes", "").strip() or None
    try:
        db.update_meeting(
            meeting_id=meeting_id,
            name=name or None,
            final_date=final_date,
            summary=summary,
            status=status,
            location=location,
            notes=notes,
        )
        flash("Reunión actualizada", "success")
    except Exception:
        flash("Error actualizando la reunión", "danger")
    return redirect(url_for("meeting_detail_admin", meeting_id=meeting_id))


def delete_meeting(require_admin, meeting_id):
    auth = require_admin()
    if auth:
        return auth
    logger.info("Admin: eliminando reunión meeting_id=%d", meeting_id)
    try:
        db.delete_meeting(meeting_id)
        flash("Reunión eliminada", "success")
    except Exception:
        logger.exception("Error eliminando reunión meeting_id=%d", meeting_id)
        flash("Error eliminando la reunión", "danger")
    return redirect(url_for("meetings_admin"))


def add_meeting_date_option(require_admin, meeting_id):
    auth = require_admin()
    if auth:
        return auth
    option_date = request.form.get("option_date", "").strip()
    logger.info("Admin: añadiendo opción de fecha meeting_id=%d → %s", meeting_id, option_date)
    if not option_date:
        flash("La fecha es obligatoria", "danger")
        return redirect(url_for("meeting_detail_admin", meeting_id=meeting_id))
    try:
        db.add_meeting_date_option(meeting_id, option_date)
        flash("Opción de fecha añadida", "success")
    except Exception:
        flash("Error añadiendo la opción de fecha", "danger")
    return redirect(url_for("meeting_detail_admin", meeting_id=meeting_id))


def close_meeting_date(require_admin, meeting_id):
    auth = require_admin()
    if auth:
        return auth
    final_date = request.form.get("final_date", "").strip()
    if not final_date:
        flash("La fecha es obligatoria", "danger")
        return redirect(url_for("meeting_detail_admin", meeting_id=meeting_id))
    try:
        db.set_meeting_final_date(meeting_id, final_date)
        flash("Fecha de reunión confirmada", "success")
    except Exception:
        flash("Error confirmando la fecha", "danger")
    return redirect(url_for("meeting_detail_admin", meeting_id=meeting_id))


def create_meeting(require_admin, logger):
    auth = require_admin()
    if auth:
        return auth
    name = request.form.get("meeting_name", "").strip()
    meeting_date = request.form.get("meeting_date", "").strip() or None
    location = request.form.get("location", "").strip() or None
    if not name:
        flash("El nombre de la reunión es obligatorio", "danger")
        return redirect(url_for("meetings_admin"))
    try:
        meeting = db.create_meeting(name=name, final_date=meeting_date, created_by="admin")
        if location:
            db.update_meeting(meeting_id=meeting["id"], location=location)
        flash(f"Reunión «{name}» creada", "success")
        return redirect(url_for("meetings_admin"))
    except Exception:
        logger.exception("Error creando reunion")
        flash("Error creando la reunión", "danger")
        return redirect(url_for("meetings_admin"))


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
        cols, rows, pk_column = db.get_table_rows(table)
        logger.info("Admin DB: tabla cargada table=%s rows=%d pk=%s", table, len(rows), pk_column or "(none)")
    except Exception:
        logger.exception("Error cargando tabla")
        flash(f"No se pudo cargar la tabla «{table}».", "danger")
        cols, rows, pk_column = [], [], None
    return render_template("admin_db.html", tables=tables, table=table, cols=cols, rows=rows, pk_column=pk_column)


def delete_db_row(require_admin, logger, table):
    auth = require_admin()
    if auth:
        return auth
    pk_name = (request.form.get("pk_name") or "").strip()
    pk_value = request.form.get("pk_value")
    logger.info("Admin DB: eliminando fila tabla=%s pk=%s valor=%r", table, pk_name, pk_value)
    try:
        deleted = db.delete_table_row(table, pk_name, pk_value)
        if deleted:
            flash(f"Fila eliminada de «{table}».", "success")
        else:
            flash(f"No se encontró la fila seleccionada en «{table}».", "warning")
    except Exception:
        logger.exception("Error borrando fila en tabla %s", table)
        flash(f"No se pudo borrar la fila de «{table}».", "danger")
    return redirect(url_for("admin_db", table=table))


def truncate_db_table(require_admin, logger, table):
    auth = require_admin()
    if auth:
        return auth
    logger.warning("Admin DB: vaciando tabla=%s", table)
    try:
        db.truncate_table(table)
        flash(f"Tabla «{table}» vaciada.", "success")
    except Exception:
        logger.exception("Error vaciando tabla %s", table)
        flash(f"No se pudo vaciar la tabla «{table}».", "danger")
    return redirect(url_for("admin_db", table=table))


def render_admin_db(require_admin, logger):
    auth = require_admin()
    if auth:
        return auth
    tables = db.get_table_names()
    table = request.args.get("table", "books")
    edit_pk_value = request.args.get("edit")
    if table not in tables:
        table = tables[0]
    try:
        cols, rows, pk_column = db.get_table_rows(table)
        columns = db.get_table_columns(table)
        edit_row = None
        editor_columns = []
        if edit_pk_value and pk_column:
            edit_row = db.get_table_row(table, pk_column, edit_pk_value)
            if edit_row:
                editor_columns = _build_db_editor_columns(columns, edit_row, pk_column)
                logger.info("Admin DB: fila en edicion table=%s pk=%s value=%r", table, pk_column, edit_pk_value)
            else:
                flash(f"No se encontro la fila seleccionada en {table}.", "warning")
        logger.info("Admin DB: tabla cargada table=%s rows=%d pk=%s", table, len(rows), pk_column or "(none)")
    except Exception:
        logger.exception("Error cargando tabla")
        flash(f"No se pudo cargar la tabla {table}.", "danger")
        cols, rows, pk_column, edit_row, editor_columns = [], [], None, None, []
    return render_template(
        "admin_db.html",
        tables=tables,
        table=table,
        cols=cols,
        rows=rows,
        pk_column=pk_column,
        edit_row=edit_row,
        editor_columns=editor_columns,
    )


def delete_db_row(require_admin, logger, table):
    auth = require_admin()
    if auth:
        return auth
    pk_name = (request.form.get("pk_name") or "").strip()
    pk_value = request.form.get("pk_value")
    logger.info("Admin DB: eliminando fila tabla=%s pk=%s valor=%r", table, pk_name, pk_value)
    try:
        before = db.get_table_row(table, pk_name, pk_value)
        deleted = db.delete_table_row(table, pk_name, pk_value)
        if deleted:
            prepare_admin_audit(
                action="db_row_delete",
                target_type=table,
                target_id=pk_value,
                before=before,
                after={"deleted": True},
                extra={"pk_name": pk_name},
            )
            flash(f"Fila eliminada de {table}.", "success")
        else:
            flash(f"No se encontro la fila seleccionada en {table}.", "warning")
    except Exception:
        logger.exception("Error borrando fila en tabla %s", table)
        flash(f"No se pudo borrar la fila de {table}.", "danger")
    return redirect(url_for("admin_db", table=table))


def update_db_row(require_admin, logger, table):
    auth = require_admin()
    if auth:
        return auth

    pk_name = (request.form.get("pk_name") or "").strip()
    pk_value = request.form.get("pk_value")

    try:
        before = db.get_table_row(table, pk_name, pk_value)
        columns = db.get_table_columns(table)
        updates = {}
        for column in columns:
            name = column["name"]
            if name == pk_name:
                continue
            updates[name] = {
                "value": request.form.get(f"value__{name}"),
                "set_null": request.form.get(f"null__{name}") == "1",
            }

        logger.info(
            "Admin DB: actualizando fila table=%s pk=%s value=%r editable_columns=%d",
            table,
            pk_name,
            pk_value,
            len(updates),
        )
        updated = db.update_table_row(table, pk_name, pk_value, updates)
        if updated:
            after = db.get_table_row(table, pk_name, pk_value)
            prepare_admin_audit(
                action="db_row_update",
                target_type=table,
                target_id=pk_value,
                before=before,
                after=after,
                extra={"pk_name": pk_name},
            )
            flash(f"Fila actualizada en {table}.", "success")
        else:
            flash(f"No se encontro la fila seleccionada en {table}.", "warning")
    except ValueError as exc:
        logger.warning(
            "Admin DB: validacion fallida al actualizar table=%s pk=%s value=%r error=%s",
            table,
            pk_name,
            pk_value,
            exc,
        )
        flash(str(exc), "danger")
    except Exception:
        logger.exception("Error actualizando fila en tabla %s", table)
        flash(f"No se pudo actualizar la fila de {table}.", "danger")
    return redirect(url_for("admin_db", table=table, edit=pk_value))


def truncate_db_table(require_admin, logger, table):
    auth = require_admin()
    if auth:
        return auth
    logger.warning("Admin DB: vaciando tabla=%s", table)
    try:
        prepare_admin_audit(
            action="db_table_truncate",
            target_type="table",
            target_id=table,
            before={"table": table},
            after={"truncated": True},
        )
        db.truncate_table(table)
        flash(f"Tabla {table} vaciada.", "success")
    except Exception:
        logger.exception("Error vaciando tabla %s", table)
        flash(f"No se pudo vaciar la tabla {table}.", "danger")
    return redirect(url_for("admin_db", table=table))


def edit_book(require_admin, logger, book_id):
    auth = require_admin()
    if auth:
        return auth
    logger.info("Admin: editando libro book_id=%d", book_id)
    title = request.form.get("title", "").strip() or None
    author = request.form.get("author", "").strip() or None
    description = request.form.get("description", "").strip() or None
    pages = request.form.get("pages", "").strip() or None
    cover = request.form.get("cover", "").strip() or None
    before = db.get_book_by_id(book_id)
    try:
        db.update_book(book_id, title=title, author=author, description=description, pages=pages, cover=cover)
        after = db.get_book_by_id(book_id)
        prepare_admin_audit(
            action="book_update",
            target_type="book",
            target_id=book_id,
            before=before,
            after=after,
        )
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
    logger.info("Admin: añadiendo book_id=%s a lista de espera", book_id)
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
    logger.info("Admin: eliminando wl_id=%d de lista de espera", wl_id)
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
