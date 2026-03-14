import db
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


class ThemeHandlers:
    def __init__(self, allowed, check_cooldown, logger, formatting):
        self.allowed = allowed
        self.check_cooldown = check_cooldown
        self.logger = logger
        self.bold = formatting["bold"]
        self.code = formatting["code"]
        self.esc = formatting["esc"]

    async def tema(self, update, context):
        if not await self.allowed(update):
            return
        if not self.check_cooldown(update.effective_user.id, "tema", 30):
            await update.message.reply_text("Espera unos segundos antes de volver a usar este comando.", parse_mode=None)
            return
        name = " ".join(context.args).strip()
        if not name:
            await update.message.reply_text(
                f"Usa {self.code('/tema nombre de la tematica')}",
                parse_mode="MarkdownV2",
            )
            return
        try:
            user = update.effective_user.first_name or update.effective_user.username or "alguien"
            row = db.create_theme(name, created_by=user)
            if row:
                previous = db.get_theme_previous_cycles(name)
                warning = ""
                if previous:
                    cycles = ", ".join(item["cycle_key"] for item in previous[:3])
                    warning = f"\n\nEsta tematica ya se uso en: {cycles}"
                await update.message.reply_text(
                    f"Tematica propuesta: {name}\n"
                    f"Propuesta por {user}.{warning}\n"
                    "Usa /temas para votar.",
                    parse_mode=None,
                )
            else:
                await update.message.reply_text(
                    f"La tematica _{self.esc(name)}_ ya existe en este ciclo\\.",
                    parse_mode="MarkdownV2",
                )
        except Exception:
            self.logger.exception("Error en /tema")
            await update.message.reply_text("Error creando tematica\\.", parse_mode="MarkdownV2")

    async def temas(self, update, context):
        if not await self.allowed(update):
            return
        try:
            rows = db.get_themes()
            if not rows:
                await update.message.reply_text(
                    "No hay tematicas\\. Usa /tema para anadir la primera\\.",
                    parse_mode="MarkdownV2",
                )
                return
            lines = [f"{self.bold('Tematicas del ciclo')}\n"]
            for theme in rows:
                bar = "█" * min(theme["votes"], 8) if theme["votes"] > 0 else "░"
                lines.append(
                    f"{self.bold(str(theme['id']))}\\. {self.esc(theme['name'])}\n"
                    f"   {bar} {self.bold(str(theme['votes']))} voto{'s' if theme['votes'] != 1 else ''}"
                )
            lines.append("\n_Pulsa un boton para votar:_")
            keyboard = []
            for theme in rows[:10]:
                label = f"Votar {theme['name'][:26]}"
                keyboard.append([InlineKeyboardButton(label, callback_data=f"vt:{theme['id']}")])
            await update.message.reply_text(
                "\n".join(lines),
                parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        except Exception:
            self.logger.exception("Error en /temas")
            await update.message.reply_text("Error obteniendo tematicas\\.", parse_mode="MarkdownV2")

    async def votar_tema(self, update, context):
        if not await self.allowed(update):
            return
        if not self.check_cooldown(update.effective_user.id, "votar_tema", 10):
            await update.message.reply_text("Espera unos segundos antes de volver a usar este comando.", parse_mode=None)
            return
        if not context.args:
            await update.message.reply_text(
                f"Usa {self.code('/votar_tema id')} - consulta IDs con /temas\\.",
                parse_mode="MarkdownV2",
            )
            return
        try:
            theme_id = int(context.args[0])
            user = update.effective_user.first_name or update.effective_user.username or "alguien"
            ok = db.vote_theme(theme_id, user)
            if ok:
                await update.message.reply_text(
                    f"{self.bold('Voto de tematica registrado')}\\! Usa /temas para ver el ranking\\.",
                    parse_mode="MarkdownV2",
                )
            else:
                await update.message.reply_text("Ya habias votado esa tematica\\.", parse_mode="MarkdownV2")
        except ValueError:
            await update.message.reply_text("El ID debe ser un numero\\.", parse_mode="MarkdownV2")
        except Exception:
            self.logger.exception("Error en /votar_tema")
            await update.message.reply_text("Error registrando voto\\.", parse_mode="MarkdownV2")
