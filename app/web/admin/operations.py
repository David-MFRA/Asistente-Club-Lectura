import logging
from html import escape as hesc

from flask import flash, redirect, request, url_for
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import db

logger = logging.getLogger(__name__)


async def send_manual_meeting_reminder(require_admin, send_meeting_reminder, logger):
    auth = require_admin()
    if auth:
        return auth
    logger.info("Admin: enviando recordatorio de reunion manualmente")
    try:
        await send_meeting_reminder()
        db.log_event("admin", "Recordatorio de reunion enviado manualmente", category="meeting", actor="admin")
        flash("Recordatorio de reunion enviado al grupo", "success")
    except Exception:
        logger.exception("Error enviando recordatorio de reunion manual")
        flash("Error enviando el recordatorio de reunion", "danger")
    return redirect(url_for("admin_dashboard"))


async def send_manual_reading_reminder(require_admin, send_reading_reminder, logger):
    auth = require_admin()
    if auth:
        return auth
    try:
        await send_reading_reminder()
        flash("Recordatorio de lectura enviado al grupo", "success")
    except Exception:
        logger.exception("Error enviando recordatorio de lectura manual")
        flash("Error enviando el recordatorio de lectura", "danger")
    return redirect(url_for("admin_dashboard"))


async def send_manual_meeting_info(require_admin, send_to_group, logger):
    auth = require_admin()
    if auth:
        return auth
    try:
        meeting = db.get_latest_scheduled_meeting()
        if not meeting:
            flash("No hay reunion activa para anunciar", "warning")
            return redirect(url_for("admin_dashboard"))

        date_text = str(meeting["final_date"])[:16] if meeting.get("final_date") else "Sin fecha confirmada"
        location_line = f"\n📍 <b>{hesc(meeting['location'])}</b>" if meeting.get("location") else ""

        winner = db.get_winner_book(meeting.get("cycle_key"))
        book_line = f"\n📖 Libro: <b>{hesc(winner['title'])}</b>" if winner else ""

        attendees = db.get_attendance(meeting["id"])
        attend_line = f"\n👥 {len(attendees)} confirmado{'s' if len(attendees) != 1 else ''}" if attendees else ""

        text = (
            f"📅 <b>{hesc(meeting['name'])}</b>\n\n"
            f"🗓 <b>{hesc(date_text)}</b>"
            f"{location_line}"
            f"{book_line}"
            f"{attend_line}\n\n"
            "✅ Apuntate con los botones o con /asistir\n"
            "❌ Si no puedes venir, usa los botones o /noasistir"
        )
        keyboard = [[InlineKeyboardButton("✅ Apuntarme / Quitar", callback_data=f"attend:{meeting['id']}")]]
        keyboard.append([InlineKeyboardButton("Ver detalles", callback_data=f"meetinginfo:{meeting['id']}")])
        await send_to_group(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
            message_type="meeting_info",
        )
        logger.info("Admin: info de reunion enviada (meeting_id=%d)", meeting["id"])
        flash("Info de reunion enviada al grupo con botones de asistencia", "success")
    except Exception:
        logger.exception("Error enviando info de reunion")
        flash("Error enviando la informacion", "danger")
    return redirect(url_for("admin_dashboard"))


async def send_dm_reminders(require_admin, meeting_id, telegram_app, logger):
    auth = require_admin()
    if auth:
        return auth
    logger.info("Admin: enviando DMs para meeting_id=%d", meeting_id)

    meeting = db.get_meeting(meeting_id)
    if not meeting:
        flash("Reunion no encontrada", "danger")
        return redirect(url_for("admin_dashboard"))

    members = db.get_all_members()
    confirmed = {row["user_id"] for row in db.get_attendance_members(meeting_id) if row.get("user_id") is not None}
    date_text = str(meeting["final_date"])[:16] if meeting.get("final_date") else "sin fecha"
    sent = 0
    failed = 0

    for member in members:
        name = member.get("first_name") or member.get("username") or "miembro"
        if member.get("user_id") in confirmed:
            continue
        try:
            location_line = f"\n📍 <b>{hesc(meeting['location'])}</b>" if meeting.get("location") else ""
            await telegram_app.bot.send_message(
                chat_id=member["user_id"],
                text=(
                    f"📚 Hola, <b>{hesc(name)}</b>.\n\n"
                    "Te recuerdo la proxima reunion del club:\n\n"
                    f"🫶 <b>{hesc(meeting['name'])}</b>\n"
                    f"🗓 <b>{hesc(date_text)}</b>"
                    f"{location_line}\n\n"
                    "Puedes confirmar desde estos botones o revisar primero los detalles."
                ),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("✅ Apuntarme / Quitar", callback_data=f"attend:{meeting_id}")],
                        [InlineKeyboardButton("Ver detalles", callback_data=f"meetinginfo:{meeting_id}")],
                    ]
                ),
            )
            sent += 1
        except Exception:
            logger.warning("DM fallido para user_id=%s (%s)", member.get("user_id"), name)
            failed += 1

    logger.info("Admin: DMs reunion: %d enviados, %d fallidos", sent, failed)
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

        parts = ["📌 <b>Proximas reuniones del club</b>\n"]
        keyboard = []

        for index, meeting in enumerate(upcoming[:5], 1):
            attendees = db.get_attendance(meeting["id"])
            date_text = str(meeting["final_date"])[:16] if meeting.get("final_date") else "Sin fecha cerrada"
            location_line = f"\n📍 {hesc(meeting['location'])}" if meeting.get("location") else ""

            parts.append(
                f"<b>{index}. {hesc(meeting['name'])}</b>\n"
                f"🗓 {hesc(date_text)}"
                f"{location_line}\n"
                f"👥 {len(attendees)} confirmado{'s' if len(attendees) != 1 else ''}"
            )

            short_name = meeting["name"][:20]
            keyboard.append(
                [InlineKeyboardButton(f"✅ {meeting['name'][:25]}", callback_data=f"attend:{meeting['id']}")]
            )

        parts.append("\nPulsa un boton para apuntarte o quitarte.")

        sent, pinned = await send_and_pin(
            "\n\n".join(parts),
            parse_mode="HTML",
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
