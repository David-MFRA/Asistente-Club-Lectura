from time import time

import db
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.services.bot_context import get_soft_guidance
from app.services.input_limits import InputValidationError, normalize_theme_name


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
        user_obj = update.effective_user
        self.logger.info("/tema: user=%s id=%d args=%r", user_obj.first_name or user_obj.username, user_obj.id, context.args)
        name = " ".join(context.args).strip()
        if not name:
            context.user_data["pending_tema"] = True
            context.user_data["pending_tema_started_at"] = time()
            db.log_event("bot", "Flujo /tema pendiente iniciado", category="command", actor=user_obj.first_name or user_obj.username or str(user_obj.id))
            await update.message.reply_text(
                "Como se llama la tematica que quieres proponer?\n\nEscribela a continuacion:",
                parse_mode=None,
            )
            return
        try:
            name = normalize_theme_name(name)
            user = update.effective_user.first_name or update.effective_user.username or "alguien"
            row = db.create_theme(name, created_by=user, cycle_key=db.get_current_cycle_key())
            if row:
                previous = db.get_theme_previous_cycles(name)
                warning = ""
                if previous:
                    cycles = ", ".join(item["cycle_key"] for item in previous[:3])
                    warning = f"\n\nEsta tematica ya se uso en: {cycles}"
                db.log_event("bot", f"Tematica propuesta: {name}", category="theme", actor=user)
                await update.message.reply_text(
                    f"Tematica propuesta: {name}\nPropuesta por {user}.{warning}\nUsa /temas para votar.",
                    parse_mode=None,
                )
            else:
                await update.message.reply_text(
                    f"La tematica {name} ya existe en este ciclo.",
                    parse_mode=None,
                )
        except InputValidationError as exc:
            await update.message.reply_text(str(exc), parse_mode=None)
        except Exception:
            self.logger.exception("Error en /tema")
            await update.message.reply_text("Error creando tematica.", parse_mode=None)

    async def temas(self, update, context):
        if not await self.allowed(update):
            return
        try:
            rows = db.get_themes(db.get_current_cycle_key())
            if not rows:
                guidance = get_soft_guidance("temas")
                await update.message.reply_text(
                    guidance or "No hay tematicas. Usa /tema para anadir la primera.",
                    parse_mode=None,
                )
                return
            lines = [f"{self.bold('Tematicas del ciclo')}\n"]
            for theme in rows:
                bar = "■" * min(theme["votes"], 8) if theme["votes"] > 0 else "·"
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
            await update.message.reply_text("Error obteniendo tematicas.", parse_mode=None)

    async def votar_tema(self, update, context):
        if not await self.allowed(update):
            return
        user_obj = update.effective_user
        self.logger.info("/votar_tema: user=%s id=%d args=%r", user_obj.first_name or user_obj.username, user_obj.id, context.args)
        if not self.check_cooldown(update.effective_user.id, "votar_tema", 10):
            await update.message.reply_text("Espera unos segundos antes de volver a usar este comando.", parse_mode=None)
            return
        if not context.args:
            await update.message.reply_text(
                f"Usa {self.code('/votar_tema id')} - consulta IDs con /temas.",
                parse_mode="MarkdownV2",
            )
            return
        try:
            theme_id = int(context.args[0])
            user = update.effective_user.first_name or update.effective_user.username or "alguien"
            ok = db.vote_theme(theme_id, user, user_obj.id)
            if ok:
                db.log_event("bot", f"Voto tematica registrado #{theme_id}", category="theme", actor=user)
                await update.message.reply_text(
                    f"{self.bold('Voto de tematica registrado')}\\! Usa /temas para ver el ranking\\.",
                    parse_mode="MarkdownV2",
                )
            else:
                db.log_event("bot", f"Voto tematica duplicado #{theme_id}", category="theme", actor=user)
                await update.message.reply_text("Ya habias votado esa tematica.", parse_mode=None)
        except ValueError:
            await update.message.reply_text("El ID debe ser un numero.", parse_mode=None)
        except Exception:
            self.logger.exception("Error en /votar_tema")
            await update.message.reply_text("Error registrando voto.", parse_mode=None)
