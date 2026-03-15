import ai_features
import db
import recommendations
import trivia


class ExtraHandlers:
    def __init__(self, allowed, check_cooldown, logger, formatting, admin_ids=None):
        self.allowed = allowed
        self.check_cooldown = check_cooldown
        self.logger = logger
        self.bold = formatting["bold"]
        self.esc = formatting["esc"]
        self.italic = formatting["italic"]
        self.admin_ids = set(str(i) for i in (admin_ids or []))

    def _is_admin(self, update):
        uid = str(update.effective_user.id) if update.effective_user else ""
        return uid in self.admin_ids

    async def trivia_cmd(self, update, context):
        if not await self.allowed(update):
            return
        self.logger.info("/trivia: user_id=%d", update.effective_user.id)
        if not self.check_cooldown(update.effective_user.id, "trivia", 15):
            await update.message.reply_text("Espera unos segundos antes de volver a usar este comando.", parse_mode=None)
            return
        try:
            question = trivia.generate()
            await update.message.reply_text(self.esc(question), parse_mode="MarkdownV2")
        except Exception:
            self.logger.exception("Error en /trivia")
            await update.message.reply_text("Error generando trivia\\.", parse_mode="MarkdownV2")

    async def recomendar(self, update, context):
        if not await self.allowed(update):
            return
        u = update.effective_user
        self.logger.info("/recomendar: user=%s id=%d", u.first_name or u.username, u.id)
        if not self.check_cooldown(update.effective_user.id, "recomendar", 60):
            await update.message.reply_text("Espera unos segundos antes de volver a usar este comando.", parse_mode=None)
            return
        try:
            top_theme = db.get_top_theme()
            theme_name = top_theme["name"] if top_theme else "novela"
            wait = await update.message.reply_text(
                f"Buscando libros de _{self.esc(theme_name)}_\\.\\.\\.",
                parse_mode="MarkdownV2",
            )
            rec = recommendations.recommend(theme_name)
            await wait.delete()
            if not rec:
                await update.message.reply_text("No encontre recomendaciones\\.", parse_mode="MarkdownV2")
                return
            lines = [f"{self.bold('Recomendaciones')} - tema {self.italic(theme_name)}\n"]
            for index, item in enumerate(rec, 1):
                author_str = f"\n   _{self.esc(item['author'])}_" if item.get("author") else ""
                lines.append(f"{self.bold(str(index))}\\. {self.esc(item['title'])}{author_str}")
            await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2")
        except Exception:
            self.logger.exception("Error en /recomendar")
            await update.message.reply_text("Error obteniendo recomendaciones\\.", parse_mode="MarkdownV2")

    async def preguntas_cmd(self, update, context):
        if not await self.allowed(update):
            return
        u = update.effective_user
        self.logger.info("/preguntas: user=%s id=%d", u.first_name or u.username, u.id)
        if not self._is_admin(update):
            await update.message.reply_text("⛔ Este comando es solo para administradores del club.", parse_mode=None)
            return
        if not self.check_cooldown(update.effective_user.id, "preguntas", 60):
            await update.message.reply_text("Espera un momento antes de generar mas preguntas.", parse_mode=None)
            return
        try:
            winner = db.get_winner_book()
            if not winner:
                await update.message.reply_text("No hay libro del ciclo activo.", parse_mode=None)
                return
            self.logger.info("/preguntas: generando para «%s»", winner["title"])
            wait = await update.message.reply_text("Generando preguntas de debate...", parse_mode=None)
            questions = ai_features.generate_discussion_questions(
                winner["title"],
                winner.get("author", ""),
                winner.get("description", ""),
            )
            await wait.delete()
            self.logger.info("/preguntas: respuesta generada (%d chars)", len(questions))
            user = update.effective_user.first_name or update.effective_user.username or "alguien"
            db.log_event("bot", f"/preguntas solicitado para «{winner['title']}»", category="ai", actor=user)
            await update.message.reply_text(
                f"Preguntas de debate - {winner['title']}\n\n{questions}",
                parse_mode=None,
            )
        except Exception:
            self.logger.exception("Error en /preguntas")
            await update.message.reply_text("Error generando preguntas.", parse_mode=None)

    async def cita_cmd(self, update, context):
        if not await self.allowed(update):
            return
        u = update.effective_user
        self.logger.info("/cita: user=%s id=%d", u.first_name or u.username, u.id)
        if not self._is_admin(update):
            await update.message.reply_text("⛔ Este comando es solo para administradores del club.", parse_mode=None)
            return
        if not self.check_cooldown(update.effective_user.id, "cita", 30):
            await update.message.reply_text("Espera un momento.", parse_mode=None)
            return
        try:
            winner = db.get_winner_book()
            if not winner:
                await update.message.reply_text("No hay libro del ciclo activo.", parse_mode=None)
                return
            wait = await update.message.reply_text("Buscando cita...", parse_mode=None)
            quote = ai_features.generate_book_quote(winner["title"], winner.get("author", ""))
            await wait.delete()
            await update.message.reply_text(
                f"{quote}\n\nSobre «{winner['title']}»",
                parse_mode=None,
            )
        except Exception:
            self.logger.exception("Error en /cita")
            await update.message.reply_text("Error generando cita.", parse_mode=None)
