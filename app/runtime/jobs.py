import asyncio
import urllib.request
from time import monotonic

from telegram import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats, BotCommandScopeChat


class RuntimeJobs:
    def __init__(
        self,
        *,
        db,
        scheduler,
        telegram_app,
        logger,
        webhook_url,
        admin_ids,
        get_contextual_commands,
        observability=None,
    ):
        self.db = db
        self.scheduler = scheduler
        self.telegram_app = telegram_app
        self.logger = logger
        self.webhook_url = str(webhook_url or "").rstrip("/")
        self.admin_ids = [str(admin_id) for admin_id in (admin_ids or [])]
        self.get_contextual_commands = get_contextual_commands
        self.observability = observability

    def _record_job(self, name, started_at, ok):
        if self.observability is not None:
            self.observability.record_job(name, duration_ms=int((monotonic() - started_at) * 1000), ok=ok)

    def instrument(self, name, coro):
        async def _wrapped():
            started_at = monotonic()
            try:
                result = await coro()
                self._record_job(name, started_at, True)
                return result
            except Exception:
                self._record_job(name, started_at, False)
                raise

        return _wrapped

    def make_custom_reminder_job(self, message_text, send_to_group):
        async def _job():
            await send_to_group(message_text, parse_mode="HTML", message_type="custom_reminder")

        return self.instrument("custom_reminder", _job)

    def reload_custom_reminders(self, send_to_group):
        for job in self.scheduler.get_jobs():
            if job.id.startswith("custom_reminder_"):
                try:
                    self.scheduler.remove_job(job.id)
                except Exception:
                    pass

        for reminder in self.db.get_custom_reminders():
            if not reminder.get("enabled", True):
                continue
            message = reminder.get("message", "")
            if not message:
                continue
            job_id = f"custom_reminder_{reminder['id']}"
            try:
                if reminder.get("schedule_type") == "cron":
                    kwargs = {"hour": reminder.get("hour", 10), "minute": reminder.get("minute", 0)}
                    if reminder.get("day_of_week"):
                        kwargs["day_of_week"] = reminder["day_of_week"]
                    self.scheduler.add_job(
                        self.make_custom_reminder_job(message, send_to_group),
                        "cron",
                        id=job_id,
                        timezone="Europe/Madrid",
                        replace_existing=True,
                        **kwargs,
                    )
                else:
                    self.scheduler.add_job(
                        self.make_custom_reminder_job(message, send_to_group),
                        "interval",
                        hours=max(1, reminder.get("interval_hours") or reminder.get("hours") or 24),
                        id=job_id,
                        replace_existing=True,
                    )
            except Exception:
                self.logger.exception("Error cargando recordatorio personalizado %s", reminder.get("id"))

    async def keep_alive_ping(self):
        if self.db.get_config("reminder_keepalive_enabled", "1") == "0":
            return
        url = f"{self.webhook_url}/health"
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, urllib.request.urlopen, url)
            self.logger.info("Keep-alive ping OK -> %s", url)
        except Exception:
            self.logger.warning("Keep-alive ping fallo -> %s", url)
            raise

    async def refresh_bot_command_menu(self):
        current_cycle = self.db.get_current_cycle_key()
        user_commands = [BotCommand("start", "👋 Bienvenida y opciones utiles")]
        contextual = self.get_contextual_commands("private", cycle_key=current_cycle, is_admin=False)
        user_commands.extend(
            [
                BotCommand(item["id"], f"{item['emoji']} {item['desc']}")
                for item in contextual[:12]
                if item["id"]
                in {
                    "ayuda",
                    "proponer",
                    "propuestas",
                    "votar",
                    "resultados",
                    "libro",
                    "tema",
                    "temas",
                    "reunion",
                    "asistir",
                    "noasistir",
                    "asistencia",
                    "acta",
                    "progreso",
                    "estadisticas",
                    "recomendar",
                    "lista_espera",
                    "proponer_fecha",
                    "bug",
                    "votar_tema",
                    "trivia",
                }
            ]
        )
        if not any(cmd.command == "ayuda" for cmd in user_commands):
            user_commands.insert(0, BotCommand("ayuda", "❓ Ver el menu contextual"))
        try:
            await self.telegram_app.bot.set_my_commands(user_commands, scope=BotCommandScopeAllGroupChats())
            await self.telegram_app.bot.set_my_commands(user_commands, scope=BotCommandScopeAllPrivateChats())
            self.logger.info("Comandos del bot actualizados para ciclo=%s (%d comandos)", current_cycle, len(user_commands))
        except Exception:
            self.logger.warning("No se pudieron actualizar los comandos contextuales del bot")
        return user_commands

    async def register_runtime_bot_commands(self):
        user_commands = await self.refresh_bot_command_menu()
        admin_extra = [
            BotCommand("preguntas", "🤖 Generar preguntas de debate con IA"),
            BotCommand("cita", "✨ Generar cita literaria del libro actual"),
            BotCommand("admin_ayuda", "🛠️ Ayuda de administrador"),
            BotCommand("ciclo", "🔄 Ver ciclo activo"),
            BotCommand("nuevo_ciclo", "🆕 Crear nuevo ciclo"),
            BotCommand("cerrar_ciclo", "🔒 Cerrar ciclo actual"),
            BotCommand("anuncio", "📢 Enviar mensaje al grupo"),
            BotCommand("anunciar_ganador", "🎉 Anunciar libro ganador"),
            BotCommand("encuesta_libros", "📊 Lanzar encuesta de libros"),
            BotCommand("encuesta_temas", "📊 Lanzar encuesta de tematicas"),
            BotCommand("enviar_recordatorio", "🔔 Enviar recordatorio de reunion"),
            BotCommand("enviar_lectura", "📖 Enviar recordatorio de lectura"),
            BotCommand("fijar", "📌 Fijar mensaje en el grupo"),
            BotCommand("desfijar", "📍 Desfijar mensaje actual"),
        ]
        for admin_id in self.admin_ids:
            try:
                await self.telegram_app.bot.set_my_commands(
                    user_commands + admin_extra,
                    scope=BotCommandScopeChat(chat_id=int(admin_id)),
                )
            except Exception:
                self.logger.warning("No se pudieron registrar comandos admin para %s", admin_id)
