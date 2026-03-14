import logging
import os
import secrets

from apscheduler.schedulers.asyncio import AsyncIOScheduler

APP_TIMEZONE = "Europe/Madrid"

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.environ.get("PORT", "10000"))
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY")
if not FLASK_SECRET_KEY:
    FLASK_SECRET_KEY = secrets.token_hex(32)
    logging.getLogger(__name__).warning(
        "FLASK_SECRET_KEY no configurada - sesion no persistira entre reinicios. "
        "Define la variable de entorno para produccion."
    )

TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ALLOWED_CHAT_ID = os.getenv("ALLOWED_CHAT_ID")
ADMIN_TELEGRAM_IDS = {
    value.strip()
    for value in os.getenv("ADMIN_TELEGRAM_ID", "").split(",")
    if value.strip()
}
GROUP_INVITE_LINK = os.getenv("GROUP_INVITE_LINK", "")

if not BOT_TOKEN:
    raise RuntimeError("Falta BOT_TOKEN")
if not WEBHOOK_URL:
    raise RuntimeError("Falta WEBHOOK_URL")


def create_scheduler() -> AsyncIOScheduler:
    return AsyncIOScheduler(timezone=APP_TIMEZONE)
