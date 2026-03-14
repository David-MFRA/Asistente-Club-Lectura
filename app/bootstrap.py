import asyncio
import logging
import urllib.request

from asgiref.wsgi import WsgiToAsgi
from telegram import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats, BotCommandScopeChat
import uvicorn

from app.config import ADMIN_TELEGRAM_IDS, PORT, WEBHOOK_URL

logger = logging.getLogger(__name__)

USER_COMMANDS = [
    BotCommand("start", "👋 Bienvenida y menú de comandos"),
    BotCommand("ayuda", "❓ Ver todos los comandos disponibles"),
    BotCommand("proponer", "📚 Proponer un libro para el ciclo"),
    BotCommand("propuestas", "📋 Ver propuestas y votar"),
    BotCommand("votar", "🗳️ Votar una propuesta por número"),
    BotCommand("resultados", "🏆 Ver ranking de votos"),
    BotCommand("libro", "📖 Ver el libro del ciclo actual"),
    BotCommand("tema", "🎭 Proponer una temática"),
    BotCommand("temas", "🎨 Ver temáticas y votar"),
    BotCommand("reunion", "📅 Info de la próxima reunión"),
    BotCommand("asistir", "✅ Apuntarse a la reunión"),
    BotCommand("noasistir", "❌ Quitarse de la reunión"),
    BotCommand("asistencia", "👥 Ver lista de asistentes"),
    BotCommand("acta", "📝 Acta de la última reunión"),
    BotCommand("preguntas", "🤖 Preguntas de debate con IA"),
    BotCommand("cita", "✨ Cita literaria del libro actual"),
    BotCommand("recomendar", "💡 Recomendaciones según temática"),
    BotCommand("lista_espera", "⏳ Libros en lista de espera"),
    BotCommand("bug", "🐛 Reportar un problema o bug"),
]

ADMIN_COMMANDS = [
    BotCommand("admin_ayuda", "🛠️ Ayuda de administrador"),
    BotCommand("ciclo", "🔄 Ver ciclo activo"),
    BotCommand("nuevo_ciclo", "🆕 Crear nuevo ciclo"),
    BotCommand("cerrar_ciclo", "🔒 Cerrar ciclo actual"),
    BotCommand("anuncio", "📢 Enviar mensaje al grupo"),
    BotCommand("anunciar_ganador", "🎉 Anunciar libro ganador"),
    BotCommand("encuesta_libros", "📊 Lanzar encuesta de libros"),
    BotCommand("encuesta_temas", "📊 Lanzar encuesta de temáticas"),
    BotCommand("enviar_recordatorio", "🔔 Enviar recordatorio de reunión"),
    BotCommand("enviar_lectura", "📖 Enviar recordatorio de lectura"),
    BotCommand("fijar", "📌 Fijar mensaje en el grupo"),
    BotCommand("desfijar", "📍 Desfijar mensaje actual"),
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
):
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
        keep_alive_ping,
        "interval",
        minutes=10,
        id="keep_alive",
        replace_existing=True,
    )


async def startup(telegram_app, scheduler, scheduler_jobs):
    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
    await register_bot_commands(telegram_app.bot)
    configure_scheduler(scheduler, *scheduler_jobs)
    scheduler.start()


async def shutdown(telegram_app, scheduler):
    if scheduler.running:
        scheduler.shutdown(wait=False)
    await telegram_app.stop()
    await telegram_app.shutdown()


async def serve(flask_app, telegram_app, scheduler, scheduler_jobs):
    await startup(telegram_app, scheduler, scheduler_jobs)
    asgi_app = WsgiToAsgi(flask_app)
    server = uvicorn.Server(
        uvicorn.Config(asgi_app, host="0.0.0.0", port=PORT, log_level="info")
    )
    try:
        await server.serve()
    finally:
        await shutdown(telegram_app, scheduler)
