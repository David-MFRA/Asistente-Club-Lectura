import books_api
import db
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


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
        if not self.check_cooldown(update.effective_user.id, "proponer", 30):
            await update.message.reply_text("⏳ Espera unos segundos antes de volver a proponer.", parse_mode=None)
            return
        if db.get_config("proposals_locked_for") == db.get_current_cycle_key():
            await update.message.reply_text(
                "❌ Las propuestas para este ciclo están cerradas. ¡Espera al siguiente ciclo!",
                parse_mode=None,
            )
            return
        title = " ".join(context.args).strip()
        if not title:
            await update.message.reply_text(
                f"Usa {self.code('/proponer titulo del libro')}",
                parse_mode="MarkdownV2",
            )
            return
        wait_msg = await update.message.reply_text(
            f"Buscando _{self.esc(title)}_\\.\\.\\.",
            parse_mode="MarkdownV2",
        )
        try:
            book = books_api.google_books(title)
            if not book:
                await wait_msg.edit_text("No encontre ese libro\\.", parse_mode="MarkdownV2")
                return
            user = update.effective_user.first_name or update.effective_user.username or "alguien"
            db.insert_book(book, user)
            db.log_event("bot", f"Libro propuesto: «{book['title']}»", category="book", actor=user)
            await wait_msg.delete()

            lines = [f"{self.bold('¡Libro propuesto!')} por {self.italic(user)}\n"]
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
            lines.append("\n_Usa /propuestas y /votar para votar\\._")
            caption = "\n".join(lines)

            if book.get("cover"):
                await update.message.reply_photo(photo=book["cover"], caption=caption, parse_mode="MarkdownV2")
            else:
                await update.message.reply_text(caption, parse_mode="MarkdownV2")
        except Exception:
            self.logger.exception("Error en /proponer")
            await update.message.reply_text("Error anadiendo el libro\\.", parse_mode="MarkdownV2")

    async def propuestas(self, update, context):
        if not await self.allowed(update):
            return
        try:
            books = db.get_book_proposals()
            if not books:
                await update.message.reply_text(
                    "No hay propuestas todavia\\. Usa /proponer para anadir la primera\\.",
                    parse_mode="MarkdownV2",
                )
                return
            lines = [f"{self.bold('Propuestas del ciclo')}\n"]
            for book in books:
                pos = book.get("cycle_position", book["proposal_id"])
                author_str = f" - _{self.esc(book['author'])}_" if book.get("author") else ""
                stars = "⭐" * min(book["votes"], 5) if book["votes"] > 0 else "·"
                lines.append(
                    f"{self.bold(str(pos))}\\. {self.esc(book['title'])}{author_str}\n"
                    f"   {stars} {self.bold(str(book['votes']))} voto{'s' if book['votes'] != 1 else ''}"
                )
            lines.append("\n_Pulsa un boton para votar directamente:_")
            keyboard = []
            for book in books[:10]:
                pos = book.get("cycle_position", book["proposal_id"])
                label = f"Votar {pos}. {book['title'][:24]}"
                keyboard.append([InlineKeyboardButton(label, callback_data=f"vb:{book['proposal_id']}")])
            await update.message.reply_text(
                "\n".join(lines),
                parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        except Exception:
            self.logger.exception("Error en /propuestas")
            await update.message.reply_text("Error obteniendo propuestas\\.", parse_mode="MarkdownV2")

    async def votar(self, update, context):
        if not await self.allowed(update):
            return
        if not self.check_cooldown(update.effective_user.id, "votar", 10):
            await update.message.reply_text("Espera unos segundos antes de volver a usar este comando.", parse_mode=None)
            return
        if not context.args:
            await update.message.reply_text(
                f"Usa {self.code('/votar numero')} - el numero es la posicion en /propuestas\\.",
                parse_mode="MarkdownV2",
            )
            return
        try:
            num = int(context.args[0])
            books = db.get_book_proposals()
            proposal = next((book for book in books if book.get("cycle_position") == num), None)
            if not proposal:
                proposal = db.get_proposal_by_id(num)
            if not proposal:
                await update.message.reply_text(
                    f"No existe la propuesta \\#{self.bold(str(num))}\\. Usa /propuestas para ver la lista\\.",
                    parse_mode="MarkdownV2",
                )
                return
            proposal_id = proposal["proposal_id"]
            user = update.effective_user.first_name or update.effective_user.username or "alguien"
            ok = db.vote_book(proposal_id, user)
            if ok:
                proposal = db.get_proposal_by_id(proposal_id)
                book_name = proposal["title"] if proposal else f"propuesta #{proposal_id}"
                await update.message.reply_text(
                    f"{self.bold('Voto registrado')} para _{self.esc(book_name)}_\\.\n"
                    "Usa /propuestas para ver el ranking\\.",
                    parse_mode="MarkdownV2",
                )
            else:
                await update.message.reply_text("Ya habias votado esa propuesta\\.", parse_mode="MarkdownV2")
        except ValueError:
            await update.message.reply_text("El ID debe ser un numero\\.", parse_mode="MarkdownV2")
        except Exception:
            self.logger.exception("Error en /votar")
            await update.message.reply_text("Error registrando el voto\\.", parse_mode="MarkdownV2")

    async def resultados(self, update, context):
        if not await self.allowed(update):
            return
        try:
            books = db.get_cycle_results()
            if not books:
                await update.message.reply_text("No hay resultados todavia\\.", parse_mode="MarkdownV2")
                return
            medals = ["🥇", "🥈", "🥉"]
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
            await update.message.reply_text("Error obteniendo resultados\\.", parse_mode="MarkdownV2")
