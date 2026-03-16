import ai_features
import db
import recommendations
import trivia


class ExtraHandlers:
    def __init__(
        self,
        allowed,
        check_cooldown,
        logger,
        formatting,
        admin_ids=None,
        quota_limiter=None,
        response_cache=None,
    ):
        self.allowed = allowed
        self.check_cooldown = check_cooldown
        self.logger = logger
        self.bold = formatting["bold"]
        self.esc = formatting["esc"]
        self.italic = formatting["italic"]
        self.admin_ids = set(str(i) for i in (admin_ids or []))
        self.quota_limiter = quota_limiter
        self.response_cache = response_cache

    def _is_admin(self, update):
        uid = str(update.effective_user.id) if update.effective_user else ""
        return uid in self.admin_ids

    async def _check_quota(self, update, command, *, limit, window_seconds, message):
        if self.quota_limiter is None:
            return True
        key = f"{command}:{update.effective_user.id}"
        allowed, retry_after = self.quota_limiter.allow(key, limit=limit, window_seconds=window_seconds)
        if allowed:
            return True
        await update.message.reply_text(message.format(retry_after=retry_after), parse_mode=None)
        return False

    def _get_cached(self, key):
        return self.response_cache.get(key) if self.response_cache is not None else None

    def _set_cached(self, key, value, *, ttl_seconds):
        if self.response_cache is not None:
            self.response_cache.set(key, value, ttl_seconds=ttl_seconds)

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
        user = update.effective_user
        self.logger.info("/recomendar: user=%s id=%d", user.first_name or user.username, user.id)
        if not self.check_cooldown(update.effective_user.id, "recomendar", 60):
            await update.message.reply_text("Espera unos segundos antes de volver a usar este comando.", parse_mode=None)
            return
        if not await self._check_quota(
            update,
            "recomendar",
            limit=6,
            window_seconds=3600,
            message="Has alcanzado el limite temporal de /recomendar. Vuelve a intentarlo en {retry_after}s.",
        ):
            return
        try:
            top_theme = db.get_top_theme()
            theme_name = top_theme["name"] if top_theme else "novela"
            cache_key = f"recomendar:{theme_name.casefold()}"
            rec = self._get_cached(cache_key)
            if rec is None:
                wait = await update.message.reply_text(
                    f"Buscando libros de _{self.esc(theme_name)}_\\.\\.\\.",
                    parse_mode="MarkdownV2",
                )
                rec = recommendations.recommend(theme_name)
                await wait.delete()
                self._set_cached(cache_key, rec, ttl_seconds=1800)
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
        user = update.effective_user
        self.logger.info("/preguntas: user=%s id=%d", user.first_name or user.username, user.id)
        if not self._is_admin(update):
            await update.message.reply_text("Este comando es solo para administradores del club.", parse_mode=None)
            return
        if not self.check_cooldown(update.effective_user.id, "preguntas", 60):
            await update.message.reply_text("Espera un momento antes de generar mas preguntas.", parse_mode=None)
            return
        if not await self._check_quota(
            update,
            "preguntas",
            limit=5,
            window_seconds=3600,
            message="Has alcanzado el limite temporal de /preguntas. Prueba de nuevo en {retry_after}s.",
        ):
            return
        try:
            winner = db.get_winner_book()
            if not winner:
                await update.message.reply_text("No hay libro del ciclo activo.", parse_mode=None)
                return
            self.logger.info("/preguntas: generando para '%s'", winner["title"])
            cache_key = f"preguntas:{winner.get('id') or winner['title']}:{winner.get('author', '')}"
            questions = self._get_cached(cache_key)
            if questions is None:
                wait = await update.message.reply_text("Generando preguntas de debate...", parse_mode=None)
                questions = ai_features.generate_discussion_questions(
                    winner["title"],
                    winner.get("author", ""),
                    winner.get("description", ""),
                )
                await wait.delete()
                self._set_cached(cache_key, questions, ttl_seconds=3600)
            user_name = update.effective_user.first_name or update.effective_user.username or "alguien"
            db.log_event("bot", f"/preguntas solicitado para '{winner['title']}'", category="ai", actor=user_name)
            await update.message.reply_text(f"Preguntas de debate - {winner['title']}\n\n{questions}", parse_mode=None)
        except Exception:
            self.logger.exception("Error en /preguntas")
            await update.message.reply_text("Error generando preguntas.", parse_mode=None)

    async def cita_cmd(self, update, context):
        if not await self.allowed(update):
            return
        user = update.effective_user
        self.logger.info("/cita: user=%s id=%d", user.first_name or user.username, user.id)
        if not self._is_admin(update):
            await update.message.reply_text("Este comando es solo para administradores del club.", parse_mode=None)
            return
        if not self.check_cooldown(update.effective_user.id, "cita", 30):
            await update.message.reply_text("Espera un momento.", parse_mode=None)
            return
        if not await self._check_quota(
            update,
            "cita",
            limit=8,
            window_seconds=3600,
            message="Has alcanzado el limite temporal de /cita. Vuelve a intentarlo en {retry_after}s.",
        ):
            return
        try:
            winner = db.get_winner_book()
            if not winner:
                await update.message.reply_text("No hay libro del ciclo activo.", parse_mode=None)
                return
            cache_key = f"cita_html:{winner.get('id') or winner['title']}:{winner.get('author', '')}"
            quote = self._get_cached(cache_key)
            if quote is None:
                wait = await update.message.reply_text("Buscando cita...", parse_mode=None)
                quote = ai_features.generate_book_quote_html(winner["title"], winner.get("author", ""))
                await wait.delete()
                self._set_cached(cache_key, quote, ttl_seconds=1800)
            await update.message.reply_text(quote, parse_mode="HTML")
        except Exception:
            self.logger.exception("Error en /cita")
            await update.message.reply_text("Error generando cita.", parse_mode=None)
