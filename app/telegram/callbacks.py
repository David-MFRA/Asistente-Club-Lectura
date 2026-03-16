from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import db


class CallbackHandler:
    def __init__(self, logger):
        self.logger = logger

    def _resolve_meeting(self, raw_value):
        value = (raw_value or "").strip()
        if value == "next":
            meeting = db.get_latest_scheduled_meeting()
            return (meeting["id"], meeting) if meeting else (None, None)
        return int(value), None

    def _attendance_markup(self, meeting):
        keyboard = [[
            InlineKeyboardButton("Asistir", callback_data=f"attend:{meeting['id']}"),
            InlineKeyboardButton("No voy", callback_data=f"noattend:{meeting['id']}"),
        ]]
        keyboard.append([InlineKeyboardButton("Ver detalles", callback_data=f"meetinginfo:{meeting['id']}")])
        if meeting.get("book_id"):
            keyboard.append([InlineKeyboardButton("Ver libro", callback_data=f"bookinfo:{meeting['book_id']}")])
        return InlineKeyboardMarkup(keyboard)

    def _attendance_text(self, meeting):
        attendees = db.get_attendance(meeting["id"])
        names = ", ".join(attendees) if attendees else "nadie"
        date_text = str(meeting["final_date"])[:16] if meeting.get("final_date") else "Sin fecha cerrada"
        lines = [
            f"Reunion: {meeting['name']}",
            f"Fecha: {date_text}",
            f"Apuntados ({len(attendees)}): {names}",
        ]
        if meeting.get("location"):
            lines.append(f"Lugar: {meeting['location']}")
        lines.append("")
        lines.append("Pulsa Asistir o No voy. Los botones siguen visibles para todo el grupo.")
        return "\n".join(lines)

    async def _edit_message_content(self, query, *, text, reply_markup):
        message = query.message
        if getattr(message, "photo", None) or getattr(message, "caption", None):
            await query.edit_message_caption(
                caption=text,
                parse_mode=None,
                reply_markup=reply_markup,
            )
            return
        await query.edit_message_text(
            text=text,
            parse_mode=None,
            reply_markup=reply_markup,
        )

    async def _send_meeting_info(self, query, context, meeting_id):
        meeting = db.get_meeting(meeting_id)
        if not meeting:
            await query.answer("No encuentro esa reunion ahora mismo.", show_alert=True)
            return
        attendees = db.get_attendance(meeting_id)
        date_text = str(meeting["final_date"])[:16] if meeting.get("final_date") else "Sin fecha"
        status_map = {"draft": "Borrador", "scheduled": "Confirmada", "closed": "Cerrada"}
        lines = [
            meeting["name"],
            "",
            f"Fecha: {date_text}",
            f"Estado: {status_map.get(meeting.get('status'), meeting.get('status', ''))}",
            f"Asistentes: {len(attendees)}",
        ]
        if meeting.get("location"):
            lines.append(f"Lugar: {meeting['location']}")
        if meeting.get("notes"):
            lines.append("")
            lines.append(str(meeting["notes"])[:500])
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="\n".join(lines),
            parse_mode=None,
        )
        await query.answer("Te mando los detalles en este chat.")

    async def handle(self, update, context):
        query = update.callback_query
        data = query.data or ""
        user = update.effective_user.first_name or update.effective_user.username or "alguien"
        user_id = update.effective_user.id if update.effective_user else None
        self.logger.info("Callback recibido: data=%r user=%s", data, user)

        try:
            if data.startswith("vb:"):
                proposal_id = int(data.split(":")[1])
                proposal = db.get_proposal_by_id(proposal_id)
                book_name = proposal["title"] if proposal else f"propuesta #{proposal_id}"
                db.log_event(
                    "bot",
                    f"Intento de voto inline antiguo para {book_name}",
                    category="callback",
                    actor=user,
                )
                await query.answer(
                    "La votacion ahora se hace en la encuesta oficial fijada del grupo.",
                    show_alert=True,
                )
                return

            if data.startswith("vt:"):
                theme_id = int(data.split(":")[1])
                db.log_event(
                    "bot",
                    f"Intento de voto inline antiguo de tematica #{theme_id}",
                    category="callback",
                    actor=user,
                )
                await query.answer(
                    "La votacion de tematicas ahora se hace en la encuesta oficial fijada del grupo.",
                    show_alert=True,
                )
                return

            if data.startswith("attend:"):
                meeting_id, meeting = self._resolve_meeting(data.split(":")[1])
                if not meeting_id:
                    db.log_event("bot", "Callback de asistencia sin reunion activa", category="callback", actor=user)
                    await query.answer("No hay una reunion activa ahora mismo", show_alert=True)
                    return
                ok = db.add_attendance(meeting_id, user, user_id)
                meeting = meeting or db.get_meeting(meeting_id)
                meeting_name = meeting["name"] if meeting else f"reunion #{meeting_id}"
                if ok:
                    db.log_event("bot", f"Asistencia inline registrada para {meeting_name}", category="callback", actor=user)
                    await self._edit_message_content(
                        query,
                        text=self._attendance_text(meeting),
                        reply_markup=self._attendance_markup(meeting),
                    )
                    await query.answer(f"Apuntado a '{meeting_name}'")
                else:
                    db.log_event("bot", f"Asistencia inline duplicada para {meeting_name}", category="callback", actor=user)
                    await query.answer(f"Ya estas apuntado a '{meeting_name}'", show_alert=True)
                return

            if data.startswith("noattend:"):
                meeting_id, meeting = self._resolve_meeting(data.split(":")[1])
                if not meeting_id:
                    db.log_event("bot", "Callback de no asistencia sin reunion activa", category="callback", actor=user)
                    await query.answer("No hay una reunion activa ahora mismo", show_alert=True)
                    return
                db.remove_attendance(meeting_id, user, user_id)
                meeting = meeting or db.get_meeting(meeting_id)
                meeting_name = meeting["name"] if meeting else f"reunion #{meeting_id}"
                db.log_event("bot", f"Asistencia inline cancelada para {meeting_name}", category="callback", actor=user)
                await self._edit_message_content(
                    query,
                    text=self._attendance_text(meeting),
                    reply_markup=self._attendance_markup(meeting),
                )
                await query.answer(f"Te has quitado de '{meeting_name}'")
                return

            if data.startswith("meetinginfo:"):
                meeting_id = int(data.split(":")[1])
                await self._send_meeting_info(query, context, meeting_id)
                return

            if data.startswith("bookinfo:"):
                book_id_str = data.split(":")[1]
                if book_id_str and book_id_str != "0":
                    book = db.get_book_by_id(int(book_id_str))
                    if book:
                        lines = [book["title"]]
                        if book.get("author"):
                            lines.append(book["author"])
                        if book.get("pages"):
                            lines.append(f"{book['pages']} paginas")
                        if book.get("description"):
                            description = book["description"]
                            if len(description) > 400:
                                description = description[:397] + "..."
                            lines.append(f"\n{description}")
                        await context.bot.send_message(
                            chat_id=query.message.chat_id,
                            text="\n".join(lines),
                            parse_mode=None,
                        )
                        await query.answer("Te mando la ficha del libro en este chat.")
                    else:
                        await query.answer("No se encontro el libro", show_alert=True)
                else:
                    await query.answer("No hay libro asignado a esta reunion", show_alert=True)
                return

            await query.answer("Accion no reconocida", show_alert=True)
        except Exception:
            self.logger.exception("Error en button_handler")
            db.log_event("error", "Error procesando callback", category="callback", actor=user, extra={"data": data})
            await query.answer("Error procesando la accion", show_alert=True)
