from time import time

import books_api
import db
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from app.services.bot_context import get_soft_guidance
from app.services.input_limits import InputValidationError, normalize_book_query


class BookHandlers:
    def __init__(self, allowed, check_cooldown, logger, formatting):
        self.allowed = allowed
        self.check_cooldown = check_cooldown
        self.logger = logger
        self.bold = formatting["bold"]
        self.code = formatting["code"]
        self.esc = formatting["esc"]
        self.italic = formatting["italic"]

    async def proponer(self, update, context):
        if not await self.allowed(update):
            return
        user = update.effective_user
        self.logger.info("/proponer: user=%s id=%d args=%r", user.first_name or user.username, user.id, context.args)

        # Check for open voting meeting first
        open_meeting = db.get_open_voting_meeting()
        if not open_meeting:
            await update.message.reply_text(
                "No hay votación de libros abierta en este momento.",
                parse_mode=None,
            )
            return

        title = " ".join(context.args).strip()
        if not title:
            flow_token = str(int(time() * 1000))
            context.user_data["active_flow"] = {
                "kind": "book_proposal",
                "step": "await_query",
                "token": flow_token,
                "started_at": time(),
                "draft": {},
            }
            db.log_event("bot", "Flujo /proponer pendiente iniciado", category="command", actor=user.first_name or user.username or str(user.id))
            await update.message.reply_text(
                "¿Qué libro quieres proponer?\n\nEscribe el título y te enseñaré una ficha antes de confirmarlo.",
                parse_mode=None,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("Cancelar", callback_data=f"flow:{flow_token}:cancel")]]
                ),
            )
            return
        try:
            title = normalize_book_query(title)
        except InputValidationError as exc:
            await update.message.reply_text(str(exc), parse_mode=None)
            return

        wait_msg = await update.message.reply_text(
            f"Buscando <i>{__import__('html').escape(title)}</i>...",
            parse_mode="HTML",
        )
        try:
            book = books_api.google_books(title)
            if not book:
                self.logger.warning("/proponer: libro no encontrado en Google Books, query=%r", title)
                await wait_msg.edit_text("No encontré ese libro.", parse_mode=None)
                return

            user_name = update.effective_user.first_name or update.effective_user.username or "alguien"

            # Check if already proposed for this meeting
            existing = db.get_book_proposals_for_meeting(open_meeting["id"])
            existing_titles = [p["title"].lower() for p in existing]
            if book["title"].lower() in existing_titles:
                await wait_msg.delete()
                db.log_event("bot", f"Propuesta duplicada: {book['title']}", category="command", actor=user_name)
                await update.message.reply_text(f"{book['title']} ya está propuesto para esta reunión.", parse_mode=None)
                return

            cycle_key = db.get_current_cycle_key()
            result = db.insert_book(book, user_name, cycle_key=cycle_key, proposed_by_user_id=user.id, meeting_id=open_meeting["id"])
            await wait_msg.delete()

            if not result.get("inserted", True):
                db.log_event("bot", f"Propuesta duplicada: {book['title']}", category="command", actor=user_name)
                await update.message.reply_text(f"{book['title']} ya está propuesto en este ciclo.", parse_mode=None)
                return

            db.log_event("bot", f"Libro propuesto: {book['title']}", category="book", actor=user_name)
            self.logger.info("/proponer: exito '%s' por %s (meeting_id=%s)", book["title"], user_name, open_meeting["id"])
            from html import escape as h
            lines = [f"📗 <b>Libro propuesto</b> por <i>{h(user_name)}</i>\n"]
            lines.append(f"<b>{h(book['title'])}</b>")
            if book.get("author"):
                lines.append(f"✍️ <i>{h(book['author'])}</i>")
            if book.get("pages"):
                lines.append(f"📄 {book['pages']} páginas")
            if book.get("description"):
                description = book["description"]
                if len(description) > 900:
                    description = description[:897] + "…"
                lines.append(f"\n<i>{h(description)}</i>")
            lines.append("\nUsa /propuestas para ver las propuestas.")
            caption = "\n".join(lines)

            if book.get("cover"):
                await update.message.reply_photo(photo=book["cover"], caption=caption, parse_mode="HTML")
            else:
                await update.message.reply_text(caption, parse_mode="HTML")
        except Exception:
            self.logger.exception("Error en /proponer")
            await update.message.reply_text("Error añadiendo el libro.", parse_mode=None)

    async def propuestas(self, update, context):
        if not await self.allowed(update):
            return
        self.logger.info("/propuestas: solicitado por user_id=%d", update.effective_user.id)
        try:
            # Check for open voting meeting first
            open_meeting = db.get_open_voting_meeting()
            if open_meeting:
                books = db.get_book_proposals_for_meeting(open_meeting["id"])
                header = f"{self.bold('Propuestas para')} {self.esc(open_meeting['name'])}"
            else:
                cycle_key = db.get_current_cycle_key()
                books = db.get_book_proposals(cycle_key)
                header = f"{self.bold('Propuestas del ciclo')}"

            if not books:
                guidance = get_soft_guidance("propuestas", cycle_key=db.get_current_cycle_key())
                await update.message.reply_text(
                    guidance or "No hay propuestas todavía. Usa /proponer para añadir la primera.",
                    parse_mode=None,
                )
                return

            from html import escape as h
            cycle_key = db.get_current_cycle_key()
            has_active_poll = bool(db.get_open_polls("books", cycle_key))

            if open_meeting:
                header = f"<b>Propuestas para</b> {h(open_meeting['name'])}"
            else:
                header = "<b>Propuestas del ciclo</b>"

            lines = [f"{header}\n"]
            for idx, book in enumerate(books, 1):
                pos = book.get("cycle_position", idx)
                author_str = f" — <i>{h(book['author'])}</i>" if book.get("author") else ""
                if has_active_poll:
                    votes = book.get("votes", 0)
                    stars = "★" * min(votes, 5) if votes > 0 else "·"
                    lines.append(
                        f"<b>{pos}.</b> {h(book['title'])}{author_str}\n"
                        f"   {stars} <b>{votes}</b> voto{'s' if votes != 1 else ''}"
                    )
                else:
                    lines.append(f"<b>{pos}.</b> {h(book['title'])}{author_str}")

            lines.append("")
            if has_active_poll:
                lines.append("<i>Abre el mensaje fijado para votar y usa /resultados para seguir cómo va.</i>")
            else:
                lines.append("<i>Todavía no hay encuesta activa. Cuando se abra aparecerá fijada en el grupo.</i>")
            await update.message.reply_text(
                "\n".join(lines),
                parse_mode="HTML",
            )
        except Exception:
            self.logger.exception("Error en /propuestas")
            await update.message.reply_text("Error obteniendo propuestas.", parse_mode=None)

    async def votar(self, update, context):
        if not await self.allowed(update):
            return
        await update.message.reply_text(
            "Las votaciones ya no se hacen con /votar.\n\nUsa la encuesta fijada del grupo y /propuestas para ver el ranking.",
            parse_mode=None,
        )

    async def resultados(self, update, context):
        if not await self.allowed(update):
            return
        try:
            books = db.get_cycle_results(db.get_current_cycle_key())
            if not books:
                await update.message.reply_text("No hay resultados todavía.", parse_mode=None)
                return
            from html import escape as h
            medals = ["🥇", "🥈", "🥉"]
            lines = ["<b>Resultados del ciclo</b>\n"]
            for index, book in enumerate(books):
                medal = medals[index] if index < 3 else f"{index + 1}."
                author_str = f"\n   <i>{h(book['author'])}</i>" if book.get("author") else ""
                lines.append(
                    f"{medal} <b>{h(book['title'])}</b>{author_str}\n"
                    f"   <b>{book['votes']}</b> voto{'s' if book['votes'] != 1 else ''}"
                )
            await update.message.reply_text("\n".join(lines), parse_mode="HTML")
        except Exception:
            self.logger.exception("Error en /resultados")
            await update.message.reply_text("Error obteniendo resultados.", parse_mode=None)
