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

    async def handle(self, update, context):
        query = update.callback_query
        await query.answer()
        data = query.data or ""
        user = update.effective_user.first_name or update.effective_user.username or "alguien"
        self.logger.info("Callback recibido: data=%r user=%s", data, user)

        try:
            if data.startswith("vb:"):
                proposal_id = int(data.split(":")[1])
                ok = db.vote_book(proposal_id, user)
                proposal = db.get_proposal_by_id(proposal_id)
                book_name = proposal["title"] if proposal else f"propuesta #{proposal_id}"
                if ok:
                    self.logger.info("Voto libro (inline): %s → «%s» (proposal_id=%d)", user, book_name, proposal_id)
                    await query.answer(f"Voto registrado para «{book_name}»", show_alert=True)
                else:
                    self.logger.debug("Voto libro duplicado (inline): %s → proposal_id=%d", user, proposal_id)
                    await query.answer(f"Ya habias votado «{book_name}»", show_alert=True)
                return

            if data.startswith("vt:"):
                theme_id = int(data.split(":")[1])
                ok = db.vote_theme(theme_id, user)
                if ok:
                    self.logger.info("Voto temática (inline): %s → theme_id=%d", user, theme_id)
                    await query.answer("Voto de tematica registrado", show_alert=True)
                else:
                    self.logger.debug("Voto temática duplicado (inline): %s → theme_id=%d", user, theme_id)
                    await query.answer("Ya habias votado esa tematica", show_alert=True)
                return

            if data.startswith("attend:"):
                meeting_id, meeting = self._resolve_meeting(data.split(":")[1])
                if not meeting_id:
                    self.logger.warning("Callback asistencia sin reunión resoluble: data=%r", data)
                    await query.answer("No hay una reunión activa ahora mismo", show_alert=True)
                    return
                ok = db.add_attendance(meeting_id, user)
                meeting = meeting or db.get_meeting(meeting_id)
                meeting_name = meeting["name"] if meeting else f"reunion #{meeting_id}"
                if ok:
                    self.logger.info("Asistencia (inline): %s → «%s» (meeting_id=%d)", user, meeting_name, meeting_id)
                    attendees = db.get_attendance(meeting_id)
                    names = ", ".join(attendees) if attendees else "nadie"
                    await query.answer(f"Apuntado a «{meeting_name}»")
                    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                    keep_markup = InlineKeyboardMarkup([[
                        InlineKeyboardButton("❌ No voy", callback_data=f"noattend:{meeting_id}"),
                    ]])
                    await query.edit_message_text(
                        f"{user} apuntado a {meeting_name}\n\n"
                        f"Apuntados ({len(attendees)}): {names}\n\n"
                        "Usa /noasistir para quitarte.",
                        parse_mode=None,
                        reply_markup=keep_markup,
                    )
                else:
                    self.logger.debug("Asistencia duplicada (inline): %s ya en meeting_id=%d", user, meeting_id)
                    await query.answer(f"Ya estas apuntado a «{meeting_name}»", show_alert=True)
                return

            if data.startswith("noattend:"):
                meeting_id, meeting = self._resolve_meeting(data.split(":")[1])
                if not meeting_id:
                    self.logger.warning("Callback no asistencia sin reunión resoluble: data=%r", data)
                    await query.answer("No hay una reunión activa ahora mismo", show_alert=True)
                    return
                self.logger.info("No asistencia (inline): %s → meeting_id=%d", user, meeting_id)
                db.remove_attendance(meeting_id, user)
                meeting = meeting or db.get_meeting(meeting_id)
                meeting_name = meeting["name"] if meeting else f"reunion #{meeting_id}"
                attendees = db.get_attendance(meeting_id)
                names = ", ".join(attendees) if attendees else "nadie"
                await query.answer(f"Te has quitado de «{meeting_name}»")
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                keep_markup = InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Asistir", callback_data=f"attend:{meeting_id}"),
                ]])
                await query.edit_message_text(
                    f"{user} se ha quitado de {meeting_name}\n\n"
                    f"Quedan ({len(attendees)}): {names}",
                    parse_mode=None,
                    reply_markup=keep_markup,
                )
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
                    else:
                        await query.answer("No se encontro el libro", show_alert=True)
                else:
                    await query.answer("No hay libro asignado a esta reunion", show_alert=True)
                return

            await query.answer("Accion no reconocida", show_alert=True)
        except Exception:
            self.logger.exception("Error en button_handler")
            await query.answer("Error procesando la accion", show_alert=True)
