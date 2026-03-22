from html import escape as h

import db
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.services.bot_context import get_soft_guidance
from app.services.meeting_lookup import find_meeting_by_text


class MeetingHandlers:
    def __init__(self, allowed, check_cooldown, logger, formatting):
        self.allowed = allowed
        self.check_cooldown = check_cooldown
        self.logger = logger
        self.bold = formatting["bold"]
        self.italic = formatting["italic"]
        self.esc = formatting["esc"]

    async def reunion(self, update, context):
        if not await self.allowed(update):
            return
        self.logger.info("/reunion: user_id=%d args=%r", update.effective_user.id, context.args)
        try:
            meetings = db.get_upcoming_meetings_list(limit=10)
            if not meetings:
                guidance = get_soft_guidance("asistir")
                await update.message.reply_text(guidance or "No hay reuniones programadas todavía.", parse_mode=None)
                return

            lines = ["📆 <b>Reuniones programadas</b>\n"]
            for meeting in meetings:
                date_text = str(meeting["final_date"])[:16] if meeting.get("final_date") else "Sin fecha"
                attendees = db.get_attendance(meeting["id"])
                lines.append(f"🔹 <b>{h(meeting['name'])}</b>")
                lines.append(f"🗓 {h(date_text)}")
                if meeting.get("location"):
                    lines.append(f"📍 {h(meeting['location'])}")
                if meeting.get("extras"):
                    lines.append(f"✨ <i>{h(meeting['extras'])}</i>")
                if meeting.get("book_id"):
                    book = db.get_book_by_id(meeting["book_id"])
                    if book:
                        book_line = f"📗 <b>{h(book['title'])}</b>"
                        if book.get("author"):
                            book_line += f" — <i>{h(book['author'])}</i>"
                        lines.append(book_line)
                lines.append(f"👥 Apuntados: <b>{len(attendees)}</b>")
                lines.append("")

            await update.message.reply_text(
                "\n".join(lines).rstrip(),
                parse_mode="HTML",
            )

            # Send attend/leave button for each non-closed meeting
            for meeting in meetings:
                if meeting.get("status") == "closed":
                    continue
                date_text = str(meeting["final_date"])[:16] if meeting.get("final_date") else "Sin fecha"
                keyboard = [
                    [InlineKeyboardButton("✅ Apuntarme / Quitar", callback_data=f"attend:{meeting['id']}")]
                ]
                await update.message.reply_text(
                    f"<b>{h(meeting['name'])}</b> · {h(date_text)}",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
        except Exception:
            self.logger.exception("Error en /reunion")
            await update.message.reply_text("Error obteniendo las reuniones.", parse_mode=None)

    async def asistir(self, update, context):
        if not await self.allowed(update):
            return
        user_obj = update.effective_user
        self.logger.info("/asistir: user=%s id=%d", user_obj.first_name or user_obj.username, user_obj.id)
        if not self.check_cooldown(update.effective_user.id, "asistir", 10):
            await update.message.reply_text("Espera unos segundos antes de volver a usar este comando.", parse_mode=None)
            return
        try:
            meetings = db.get_upcoming_meetings()
            if not meetings:
                guidance = get_soft_guidance("asistir")
                await update.message.reply_text(guidance or "No hay reunion activa.", parse_mode=None)
                return
            user = update.effective_user.first_name or update.effective_user.username or "alguien"
            if len(meetings) == 1:
                meeting = meetings[0]
                ok = db.add_attendance(meeting["id"], user, user_obj.id)
                if not ok:
                    db.log_event("bot", f"Asistencia duplicada para {meeting['name']}", category="meeting", actor=user)
                    await update.message.reply_text(f"Ya estas apuntado a {meeting['name']}.", parse_mode=None)
                    return
                db.log_event("bot", f"{user} se apunto a '{meeting['name']}'", category="meeting", actor=user)
                attendees = db.get_attendance(meeting["id"])
                names = "\n".join(f"  - {name}" for name in attendees)
                await update.message.reply_text(
                    (
                        f"{user} se apunto a {meeting['name']}\n\n"
                        f"Apuntados ({len(attendees)}):\n{names}\n\n"
                        "Siguiente paso util: usa /asistencia, /reunion o /libro."
                    ),
                    parse_mode=None,
                )
            else:
                keyboard = []
                for meeting in meetings[:5]:
                    date_text = str(meeting["final_date"])[:16] if meeting.get("final_date") else "Sin fecha"
                    label = f"{meeting['name']} - {date_text}"
                    keyboard.append([InlineKeyboardButton(label, callback_data=f"attend:{meeting['id']}")])
                await update.message.reply_text(
                    "A que reunion te apuntas? Elige una:",
                    parse_mode=None,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
        except Exception:
            self.logger.exception("Error en /asistir")
            await update.message.reply_text("Error al apuntarte.", parse_mode=None)

    async def noasistir(self, update, context):
        if not await self.allowed(update):
            return
        user_obj = update.effective_user
        self.logger.info("/noasistir: user=%s id=%d", user_obj.first_name or user_obj.username, user_obj.id)
        if not self.check_cooldown(update.effective_user.id, "noasistir", 10):
            await update.message.reply_text("Espera unos segundos antes de volver a usar este comando.", parse_mode=None)
            return
        try:
            meetings = db.get_upcoming_meetings()
            if not meetings:
                guidance = get_soft_guidance("noasistir")
                await update.message.reply_text(guidance or "No hay reunion activa.", parse_mode=None)
                return
            user = update.effective_user.first_name or update.effective_user.username or "alguien"
            if len(meetings) == 1:
                meeting = meetings[0]
                db.remove_attendance(meeting["id"], user, user_obj.id)
                db.log_event("bot", f"{user} se ha quitado de '{meeting['name']}'", category="meeting", actor=user)
                attendees = db.get_attendance(meeting["id"])
                names = "\n".join(f"  - {name}" for name in attendees) if attendees else "Nadie de momento"
                await update.message.reply_text(
                    (
                        f"{user} se ha quitado de {meeting['name']}\n\n"
                        f"Quedan ({len(attendees)}):\n{names}\n\n"
                        "Siguiente paso util: usa /reunion o /asistencia para revisar el estado."
                    ),
                    parse_mode=None,
                )
            else:
                keyboard = []
                for meeting in meetings[:5]:
                    date_text = str(meeting["final_date"])[:16] if meeting.get("final_date") else "Sin fecha"
                    label = f"{meeting['name']} - {date_text}"
                    keyboard.append([InlineKeyboardButton(label, callback_data=f"attend:{meeting['id']}")])
                await update.message.reply_text(
                    "De que reunion te quitas? Elige una:",
                    parse_mode=None,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
        except Exception:
            self.logger.exception("Error en /noasistir")
            await update.message.reply_text("Error al quitarte.", parse_mode=None)

    async def asistencia(self, update, context):
        if not await self.allowed(update):
            return
        try:
            meeting = db.get_latest_scheduled_meeting(cycle_key=db.get_current_cycle_key())
            if not meeting:
                guidance = get_soft_guidance("asistencia")
                await update.message.reply_text(guidance or "No hay reunion activa.", parse_mode=None)
                return
            attendees = db.get_attendance(meeting["id"])
            if attendees:
                names = "\n".join(f"  {i}. {h(name)}" for i, name in enumerate(attendees, 1))
            else:
                names = "Nadie apuntado todavía"
            await update.message.reply_text(
                (
                    f"📅 <b>{h(meeting['name'])}</b>\n\n"
                    f"👥 <b>Apuntados ({len(attendees)}):</b>\n{names}\n\n"
                    "Usa /asistir o /noasistir para apuntarte o quitarte."
                ),
                parse_mode="HTML",
            )
        except Exception:
            self.logger.exception("Error en /asistencia")
            await update.message.reply_text("Error obteniendo asistencia.", parse_mode=None)
