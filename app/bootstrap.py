import asyncio
import logging
import threading
import urllib.request

from telegram import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats, BotCommandScopeChat
from werkzeug.serving import make_server

from app.config import ADMIN_TELEGRAM_IDS, PORT, WEBHOOK_SECRET_TOKEN, WEBHOOK_URL

logger = logging.getLogger(__name__)

USER_COMMANDS = [
    BotCommand("start", "Bienvenida y menu de comandos"),
    BotCommand("ayuda", "Ver todos los comandos disponibles"),
    BotCommand("proponer", "Proponer un libro para el ciclo"),
    BotCommand("propuestas", "Ver propuestas y ranking"),
    BotCommand("resultados", "Ver ranking de votos"),
    BotCommand("libro", "Ver el libro del ciclo actual"),
    BotCommand("tema", "Proponer una tematica"),
    BotCommand("temas", "Ver tematicas y encuesta activa"),
    BotCommand("reunion", "Info de la proxima reunion"),
    BotCommand("asistir", "Apuntarse a la reunion"),
    BotCommand("noasistir", "Quitarse de la reunion"),
    BotCommand("asistencia", "Ver lista de asistentes"),
    BotCommand("recomendar", "Recomendaciones segun tematica"),
    BotCommand("lista_espera", "Libros en lista de espera"),
    BotCommand("bug", "Reportar un problema o bug"),
]

ADMIN_COMMANDS = [
    BotCommand("admin_ayuda", "Ayuda de administrador"),
    BotCommand("ciclo", "Ver ciclo activo"),
    BotCommand("nuevo_ciclo", "Crear nuevo ciclo"),
    BotCommand("cerrar_ciclo", "Cerrar ciclo actual"),
    BotCommand("anuncio", "Enviar mensaje al grupo"),
    BotCommand("anunciar_ganador", "Anunciar libro ganador"),
    BotCommand("encuesta_libros", "Lanzar encuesta de libros"),
    BotCommand("encuesta_temas", "Lanzar encuesta de tematicas"),
    BotCommand("preguntas", "Preguntas de debate con IA"),
    BotCommand("cita", "Cita literaria del libro actual"),
    BotCommand("enviar_recordatorio", "Enviar recordatorio de reunion"),
    BotCommand("enviar_lectura", "Enviar recordatorio de lectura"),
    BotCommand("fijar", "Fijar mensaje en el grupo"),
    BotCommand("desfijar", "Desfijar mensaje actual"),
]


async def keep_alive_ping():
    """Hace ping a /health para mantener el servicio activo en Render."""
    url = f"{WEBHOOK_URL}/health"
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, urllib.request.urlopen, url)
        logger.info("Keep-alive ping OK -> %s", url)
    except Exception:
        logger.warning("Keep-alive ping fallo -> %s", url)


async def register_bot_commands(bot):
    try:
        await bot.set_my_commands(USER_COMMANDS, scope=BotCommandScopeAllGroupChats())
        await bot.set_my_commands(USER_COMMANDS, scope=BotCommandScopeAllPrivateChats())
        logger.info("Comandos del bot registrados en Telegram")
    except Exception:
        logger.warning("No se pudieron registrar los comandos del bot")

    for admin_id in ADMIN_TELEGRAM_IDS:
        try:
            await bot.set_my_commands(
                USER_COMMANDS + ADMIN_COMMANDS,
                scope=BotCommandScopeChat(chat_id=int(admin_id)),
            )
        except Exception:
            logger.warning("No se pudieron registrar comandos admin para %s", admin_id)


def configure_scheduler(
    scheduler,
    send_meeting_reminder,
    send_reading_reminder,
    send_day_before_reminder,
    send_scheduled_messages,
    keep_alive_job=None,
    extra_jobs=None,
):
    keep_alive_fn = keep_alive_job or keep_alive_ping
    scheduler.add_job(
        send_meeting_reminder,
        "cron",
        day_of_week="mon",
        hour=10,
        minute=0,
        id="weekly_reminder",
        replace_existing=True,
    )
    scheduler.add_job(
        send_reading_reminder,
        "interval",
        days=2,
        id="reading_reminder",
        replace_existing=True,
    )
    scheduler.add_job(
        send_day_before_reminder,
        "cron",
        hour=10,
        minute=0,
        id="day_before_reminder",
        replace_existing=True,
    )
    scheduler.add_job(
        send_scheduled_messages,
        "interval",
        minutes=5,
        id="scheduled_messages",
        replace_existing=True,
    )
    scheduler.add_job(
        keep_alive_fn,
        "interval",
        minutes=10,
        id="keep_alive",
        replace_existing=True,
    )
    for job in extra_jobs or []:
        scheduler.add_job(
            job["func"],
            job["trigger"],
            id=job["id"],
            replace_existing=True,
            **dict(job.get("kwargs") or {}),
        )


async def startup(telegram_app, scheduler, scheduler_jobs, register_commands=None, post_scheduler_start=None):
    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.bot.set_webhook(
        url=f"{WEBHOOK_URL}/webhook",
        secret_token=WEBHOOK_SECRET_TOKEN,
    )
    if register_commands is not None:
        await register_commands()
    else:
        await register_bot_commands(telegram_app.bot)
    configure_scheduler(scheduler, *scheduler_jobs)
    scheduler.start()
    if post_scheduler_start is not None:
        post_scheduler_start()


async def shutdown(telegram_app, scheduler):
    if scheduler.running:
        scheduler.shutdown(wait=False)
    await telegram_app.stop()
    await telegram_app.shutdown()


class _FlaskServerThread(threading.Thread):
    def __init__(self, flask_app):
        super().__init__(daemon=True, name="flask-server")
        self.server = make_server("0.0.0.0", PORT, flask_app, threaded=True)

    def run(self):
        logger.info("Flask server running on http://0.0.0.0:%s", PORT)
        self.server.serve_forever()

    def stop(self):
        self.server.shutdown()


async def serve(flask_app, telegram_app, scheduler, scheduler_jobs, register_commands=None, post_scheduler_start=None):
    await startup(
        telegram_app,
        scheduler,
        scheduler_jobs,
        register_commands=register_commands,
        post_scheduler_start=post_scheduler_start,
    )
    server_thread = _FlaskServerThread(flask_app)
    server_thread.start()
    try:
        while server_thread.is_alive():
            await asyncio.sleep(0.5)
    finally:
        server_thread.stop()
        server_thread.join(timeout=5)
        await shutdown(telegram_app, scheduler)
