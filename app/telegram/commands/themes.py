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
            flow_token = str(int(time() * 1000))
            context.user_data["active_flow"] = {
                "kind": "theme_proposal",
                "step": "await_query",
                "token": flow_token,
                "started_at": time(),
                "draft": {},
            }
            db.log_event("bot", "Flujo /tema pendiente iniciado", category="command", actor=user_obj.first_name or user_obj.username or str(user_obj.id))
            await update.message.reply_text(
                "¿Cómo se llama la temática que quieres proponer?\n\nEscríbela y te dejaré confirmarla antes de enviarla.",
                parse_mode=None,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("Cancelar", callback_data=f"flow:{flow_token}:cancel")]]
                ),
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
                    f"Temática propuesta: {name}\nPropuesta por {user}.{warning}\nSigue /temas y vota en la encuesta fijada del grupo.",
                    parse_mode=None,
                )
            else:
                await update.message.reply_text(
                    f"La temática {name} ya existe en este ciclo.",
                    parse_mode=None,
                )
        except InputValidationError as exc:
            await update.message.reply_text(str(exc), parse_mode=None)
        except Exception:
            self.logger.exception("Error en /tema")
            await update.message.reply_text("Error creando temática.", parse_mode=None)

    async def temas(self, update, context):
        if not await self.allowed(update):
            return
        try:
            rows = db.get_themes(db.get_current_cycle_key())
            if not rows:
                guidance = get_soft_guidance("temas")
                await update.message.reply_text(
                    guidance or "No hay temáticas. Usa /tema para añadir la primera.",
                    parse_mode=None,
                )
                return
            from html import escape as h
            lines = ["<b>Temáticas del ciclo</b>\n"]
            for theme in rows:
                bar = "■" * min(theme["votes"], 8) if theme["votes"] > 0 else "·"
                lines.append(
                    f"<b>{theme['id']}.</b> {h(theme['name'])}\n"
                    f"   {bar} <b>{theme['votes']}</b> voto{'s' if theme['votes'] != 1 else ''}"
                )
            lines.append("\n<i>La votación se hace en la encuesta fijada del grupo.</i>")
            if db.get_open_poll("themes", cycle_key=db.get_current_cycle_key()):
                lines.append("<i>Abre el mensaje fijado para votar.</i>")
            else:
                lines.append("<i>Ahora mismo no hay encuesta activa; cuando se abra aparecerá fijada en el grupo.</i>")
            await update.message.reply_text(
                "\n".join(lines),
                parse_mode="HTML",
            )
        except Exception:
            self.logger.exception("Error en /temas")
            await update.message.reply_text("Error obteniendo temáticas.", parse_mode=None)

    async def votar_tema(self, update, context):
        if not await self.allowed(update):
            return
        await update.message.reply_text(
            "Las votaciones de tematicas ya no se hacen con /votar_tema.\n\nUsa la encuesta fijada del grupo y /temas para revisar las opciones.",
            parse_mode=None,
        )
