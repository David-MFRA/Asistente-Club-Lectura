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
        keyboard = [[InlineKeyboardButton("✅ Apuntarme / Quitar", callback_data=f"attend:{meeting['id']}")]]
        keyboard.append([InlineKeyboardButton("Ver detalles", callback_data=f"meetinginfo:{meeting['id']}")])
        if meeting.get("book_id"):
            keyboard.append([InlineKeyboardButton("Ver libro", callback_data=f"bookinfo:{meeting['book_id']}")])
        return InlineKeyboardMarkup(keyboard)

    def _attendance_text(self, meeting):
        from html import escape as h
        attendees = db.get_attendance(meeting["id"])
        date_text = str(meeting["final_date"])[:16] if meeting.get("final_date") else "Sin fecha"
        lines = [
            f"📅 <b>{h(meeting['name'])}</b>",
            f"🗓 <b>{h(date_text)}</b>",
        ]
        if meeting.get("location"):
            lines.append(f"📍 {h(meeting['location'])}")
        if meeting.get("extras"):
            lines.append(f"✨ <i>{h(meeting['extras'])}</i>")
        numbered = "\n".join(f"  {i}. {h(a)}" for i, a in enumerate(attendees, 1)) if attendees else "ninguno de momento"
        lines.append(f"👥 <b>Apuntados ({len(attendees)}):</b>\n{numbered}")
        lines.append("")
        lines.append("Pulsa el botón para apuntarte o quitarte.")
        return "\n".join(lines)

    async def _edit_message_content(self, query, *, text, reply_markup):
        message = query.message
        if getattr(message, "photo", None) or getattr(message, "caption", None):
            await query.edit_message_caption(
                caption=text,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
            return
        await query.edit_message_text(
            text=text,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )

    async def _send_meeting_info(self, query, context, meeting_id):
        from html import escape as h
        meeting = db.get_meeting(meeting_id)
        if not meeting:
            await query.answer("No encuentro esa reunión ahora mismo.", show_alert=True)
            return
        attendees = db.get_attendance(meeting_id)
        date_text = str(meeting["final_date"])[:16] if meeting.get("final_date") else "Sin fecha"
        lines = [f"📅 <b>{h(meeting['name'])}</b>", f"🗓 <b>{h(date_text)}</b>"]
        if meeting.get("location"):
            lines.append(f"📍 {h(meeting['location'])}")
        if meeting.get("extras"):
            lines.append(f"✨ <i>{h(meeting['extras'])}</i>")
        lines.append(f"👥 <b>Apuntados:</b> {len(attendees)}")
        if meeting.get("notes"):
            lines.append(f"\n📝 <i>{h(str(meeting['notes'])[:500])}</i>")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="\n".join(lines),
            parse_mode="HTML",
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
                    "La votación ahora se hace en la encuesta oficial fijada del grupo.",
                    show_alert=True,
                )
                return

            if data.startswith("vt:"):
                theme_id = int(data.split(":")[1])
                db.log_event(
                    "bot",
                    f"Intento de voto inline antiguo de temática #{theme_id}",
                    category="callback",
                    actor=user,
                )
                await query.answer(
                    "La votación de temáticas ahora se hace en la encuesta oficial fijada del grupo.",
                    show_alert=True,
                )
                return

            if data.startswith("attend:"):
                meeting_id, meeting = self._resolve_meeting(data.split(":")[1])
                if not meeting_id:
                    db.log_event("bot", "Callback de asistencia sin reunión activa", category="callback", actor=user)
                    await query.answer("No hay una reunión activa ahora mismo", show_alert=True)
                    return
                meeting = meeting or db.get_meeting(meeting_id)
                meeting_name = meeting["name"] if meeting else f"reunión #{meeting_id}"
                already_in = user_id and any(m["user_id"] == user_id for m in db.get_attendance_members(meeting_id))
                if already_in:
                    db.remove_attendance(meeting_id, user, user_id)
                    db.log_event("bot", f"Asistencia inline cancelada para {meeting_name}", category="callback", actor=user)
                    await self._edit_message_content(
                        query,
                        text=self._attendance_text(meeting),
                        reply_markup=self._attendance_markup(meeting),
                    )
                    await query.answer(f"Te has quitado de '{meeting_name}'")
                else:
                    db.add_attendance(meeting_id, user, user_id)
                    db.log_event("bot", f"Asistencia inline registrada para {meeting_name}", category="callback", actor=user)
                    await self._edit_message_content(
                        query,
                        text=self._attendance_text(meeting),
                        reply_markup=self._attendance_markup(meeting),
                    )
                    await query.answer(f"Apuntado a '{meeting_name}'")
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
                        from html import escape as h
                        lines = [f"📗 <b>{h(book['title'])}</b>"]
                        if book.get("author"):
                            lines.append(f"✍️ <i>{h(book['author'])}</i>")
                        if book.get("pages"):
                            lines.append(f"📄 {book['pages']} páginas")
                        if book.get("description"):
                            description = book["description"]
                            if len(description) > 900:
                                description = description[:897] + "…"
                            lines.append(f"\n{h(description)}")
                        await context.bot.send_message(
                            chat_id=query.message.chat_id,
                            text="\n".join(lines),
                            parse_mode="HTML",
                        )
                        await query.answer("Te mando la ficha del libro en este chat.")
                    else:
                        await query.answer("No se encontró el libro", show_alert=True)
                else:
                    await query.answer("No hay libro asignado a esta reunión", show_alert=True)
                return

            await query.answer("Acción no reconocida", show_alert=True)
        except Exception:
            self.logger.exception("Error en button_handler")
            db.log_event("error", "Error procesando callback", category="callback", actor=user, extra={"data": data})
            await query.answer("Error procesando la acción", show_alert=True)
