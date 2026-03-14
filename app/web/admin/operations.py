from flask import flash, redirect, request, url_for
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import db


async def send_manual_meeting_reminder(require_admin, send_meeting_reminder, logger):
    auth = require_admin()
    if auth:
        return auth
    try:
        await send_meeting_reminder()
        db.log_event("admin", "Recordatorio de reunion enviado manualmente", category="meeting", actor="admin")
    except Exception:
        logger.exception("Error enviando recordatorio de reunion manual")
    return redirect(url_for("admin_dashboard"))


async def send_manual_reading_reminder(require_admin, send_reading_reminder, logger):
    auth = require_admin()
    if auth:
        return auth
    try:
        await send_reading_reminder()
    except Exception:
        logger.exception("Error enviando recordatorio de lectura manual")
    return redirect(url_for("admin_dashboard"))


async def send_manual_meeting_info(require_admin, send_meeting_reminder, logger):
    auth = require_admin()
    if auth:
        return auth
    try:
        await send_meeting_reminder()
        flash("Informacion de reunion enviada al grupo", "success")
    except Exception:
        logger.exception("Error enviando info de reunion")
        flash("Error enviando la informacion", "danger")
    return redirect(url_for("admin_dashboard"))


async def send_dm_reminders(require_admin, meeting_id, telegram_app, logger):
    auth = require_admin()
    if auth:
        return auth
    meeting = db.get_meeting(meeting_id)
    if not meeting:
        flash("Reunion no encontrada", "danger")
        return redirect(url_for("admin_dashboard"))
    members = db.get_all_members()
    confirmed = set(db.get_attendance(meeting_id))
    date_text = str(meeting["final_date"])[:16] if meeting.get("final_date") else "sin fecha"
    sent = 0
    failed = 0
    for member in members:
        name = member.get("first_name") or member.get("username") or "miembro"
        if name in confirmed:
            continue
        try:
            await telegram_app.bot.send_message(
                chat_id=member["user_id"],
                text=(
                    f"Hola {name}.\n\n"
                    f"La proxima reunion es:\n"
                    f"{meeting['name']}\n"
                    f"{date_text}\n"
                    + (f"{meeting['location']}\n" if meeting.get("location") else "")
                    + "\nUsa /asistir o /noasistir para confirmarlo."
                ),
                parse_mode=None,
            )
            sent += 1
        except Exception:
            failed += 1
    flash(
        f"Recordatorios enviados: {sent} enviados, {failed} no alcanzados.",
        "success" if sent > 0 else "warning",
    )
    return redirect(url_for("meeting_detail_admin", meeting_id=meeting_id))


async def send_pin_all(require_admin, send_and_pin, logger):
    auth = require_admin()
    if auth:
        return auth
    try:
        all_meetings = db.get_meetings(limit=10)
        upcoming = [meeting for meeting in all_meetings if meeting.get("status") != "closed"]
        if not upcoming:
            flash("No hay reuniones activas para fijar", "danger")
            return redirect(url_for("admin_dashboard"))
        lines = ["REUNIONES ACTIVAS\n"]
        keyboard = []
        for index, meeting in enumerate(upcoming[:5], 1):
            attendees = db.get_attendance(meeting["id"])
            date_text = str(meeting["final_date"])[:16] if meeting.get("final_date") else "Sin fecha"
            lines.append(f"Reunion {index}: {meeting['name']}")
            lines.append(f"   Fecha: {date_text}")
            if meeting.get("location"):
                lines.append(f"   Lugar: {meeting['location']}")
            lines.append(f"   Apuntados: {len(attendees)}")
            if index < len(upcoming[:5]):
                lines.append("")
            short_name = meeting["name"][:20]
            keyboard.append(
                [
                    InlineKeyboardButton(f"{short_name}", callback_data=f"attend:{meeting['id']}"),
                    InlineKeyboardButton("No voy", callback_data=f"noattend:{meeting['id']}"),
                ]
            )
        sent, pinned = await send_and_pin(
            "\n".join(lines),
            parse_mode=None,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        if pinned:
            flash("Mensaje de reuniones enviado y fijado en el grupo", "success")
        elif sent:
            flash("Mensaje enviado al grupo, pero no se pudo fijar", "warning")
        else:
            flash("Error enviando mensaje al grupo", "danger")
    except Exception:
        logger.exception("Error en pin-all")
        flash("Error fijando mensaje", "danger")
    return redirect(url_for("admin_dashboard"))


def assign_book_to_meeting(require_admin, meeting_id):
    auth = require_admin()
    if auth:
        return auth
    book_id = request.form.get("book_id", "").strip()
    if not book_id:
        db.update_meeting(meeting_id=meeting_id, book_id=None)
        flash("Libro desasignado de la reunion", "success")
        return redirect(url_for("meeting_detail_admin", meeting_id=meeting_id))

    try:
        book_id_int = int(book_id)
    except ValueError:
        flash("El libro seleccionado no es valido", "danger")
        return redirect(url_for("meeting_detail_admin", meeting_id=meeting_id))

    if not db.get_book_by_id(book_id_int):
        flash("El libro seleccionado ya no existe", "danger")
        return redirect(url_for("meeting_detail_admin", meeting_id=meeting_id))

    try:
        db.update_meeting(meeting_id=meeting_id, book_id=book_id_int)
        flash("Libro asignado a la reunion", "success")
    except Exception:
        flash("No se pudo asignar el libro seleccionado", "danger")
    return redirect(url_for("meeting_detail_admin", meeting_id=meeting_id))
