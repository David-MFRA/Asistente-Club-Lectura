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
        cycle_key = db.get_current_cycle_key()
        self.logger.info("/proponer: user=%s id=%d args=%r", user.first_name or user.username, user.id, context.args)
        if cycle_key in db.get_locked_cycle_keys():
            guidance = get_soft_guidance("proponer", cycle_key=cycle_key)
            self.logger.warning("/proponer: propuestas cerradas, rechazado user=%s", user.first_name or user.username)
            await update.message.reply_text(
                guidance or "Las propuestas para este ciclo estan cerradas. Espera al siguiente ciclo.",
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
                "Que libro quieres proponer?\n\nEscribe el titulo y te ensenare una ficha antes de confirmarlo.",
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
            f"Buscando _{self.esc(title)}_\\.\\.\\.",
            parse_mode="MarkdownV2",
        )
        try:
            book = books_api.google_books(title)
            if not book:
                self.logger.warning("/proponer: libro no encontrado en Google Books, query=%r", title)
                await wait_msg.edit_text("No encontre ese libro.", parse_mode=None)
                return

            user_name = update.effective_user.first_name or update.effective_user.username or "alguien"
            result = db.insert_book(book, user_name, cycle_key=cycle_key, proposed_by_user_id=user.id)
            await wait_msg.delete()

            if not result.get("inserted", True):
                db.log_event("bot", f"Propuesta duplicada: {book['title']}", category="command", actor=user_name)
                await update.message.reply_text(f"{book['title']} ya esta propuesto en este ciclo.", parse_mode=None)
                return

            db.log_event("bot", f"Libro propuesto: {book['title']}", category="book", actor=user_name)
            self.logger.info("/proponer: exito '%s' por %s", book["title"], user_name)
            lines = [f"{self.bold('Libro propuesto')} por {self.italic(user_name)}\n"]
            lines.append(f"{self.bold(book['title'])}")
            if book.get("author"):
                lines.append(self.italic(book["author"]))
            if book.get("pages"):
                lines.append(f"{self.esc(str(book['pages']))} paginas")
            if book.get("description"):
                description = book["description"]
                if len(description) > 300:
                    description = description[:297] + "..."
                lines.append(f"\n_{self.esc(description)}_")
            lines.append("\n_Usa /propuestas para seguir el ranking y vota en la encuesta fijada del grupo._")
            lines.append("_Siguiente paso util: revisa /reunion o propone otro libro._")
            caption = "\n".join(lines)

            if book.get("cover"):
                await update.message.reply_photo(photo=book["cover"], caption=caption, parse_mode="MarkdownV2")
            else:
                await update.message.reply_text(caption, parse_mode="MarkdownV2")
        except Exception:
            self.logger.exception("Error en /proponer")
            await update.message.reply_text("Error anadiendo el libro.", parse_mode=None)

    async def propuestas(self, update, context):
        if not await self.allowed(update):
            return
        cycle_key = db.get_current_cycle_key()
        self.logger.info("/propuestas: solicitado por user_id=%d", update.effective_user.id)
        try:
            books = db.get_book_proposals(cycle_key)
            if not books:
                guidance = get_soft_guidance("propuestas", cycle_key=cycle_key)
                await update.message.reply_text(
                    guidance or "No hay propuestas todavia. Usa /proponer para anadir la primera.",
                    parse_mode=None,
                )
                return

            lines = [f"{self.bold('Propuestas del ciclo')}\n"]
            for book in books:
                pos = book.get("cycle_position", book["proposal_id"])
                author_str = f" - _{self.esc(book['author'])}_" if book.get("author") else ""
                stars = "*" * min(book["votes"], 5) if book["votes"] > 0 else "."
                lines.append(
                    f"{self.bold(str(pos))}\\. {self.esc(book['title'])}{author_str}\n"
                    f"   {stars} {self.bold(str(book['votes']))} voto{'s' if book['votes'] != 1 else ''}"
                )
            lines.append("\n_La votacion se hace en la encuesta fijada del grupo._")
            if db.get_open_polls("books", cycle_key):
                lines.append("_Abre el mensaje fijado para votar y usa /resultados para seguir como va._")
            else:
                lines.append("_Ahora mismo no hay encuesta activa; cuando se abra aparecera fijada en el grupo._")
            await update.message.reply_text(
                "\n".join(lines),
                parse_mode="MarkdownV2",
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
                await update.message.reply_text("No hay resultados todavia.", parse_mode=None)
                return
            medals = ["1.", "2.", "3."]
            lines = [f"{self.bold('Resultados del ciclo')}\n"]
            for index, book in enumerate(books):
                medal = medals[index] if index < 3 else f"{index + 1}\\."
                author_str = f"\n   _{self.esc(book['author'])}_" if book.get("author") else ""
                lines.append(
                    f"{medal} {self.bold(book['title'])}{author_str}\n"
                    f"   {self.bold(str(book['votes']))} voto{'s' if book['votes'] != 1 else ''}"
                )
            await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2")
        except Exception:
            self.logger.exception("Error en /resultados")
            await update.message.reply_text("Error obteniendo resultados.", parse_mode=None)
