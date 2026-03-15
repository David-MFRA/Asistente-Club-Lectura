import logging
import os
import hashlib
import secrets

from apscheduler.schedulers.asyncio import AsyncIOScheduler

APP_TIMEZONE = "Europe/Madrid"

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.environ.get("PORT", "10000"))
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY")
if not FLASK_SECRET_KEY:
    bot_token = os.getenv("BOT_TOKEN", "")
    if ADMIN_SECRET:
        FLASK_SECRET_KEY = hashlib.sha256(
            f"flask-{ADMIN_SECRET}-{bot_token}-secret".encode()
        ).hexdigest()
        logging.getLogger(__name__).warning(
            "FLASK_SECRET_KEY no configurada - derivando de ADMIN_SECRET y BOT_TOKEN. "
            "Define la variable de entorno para mayor seguridad."
        )
    else:
        FLASK_SECRET_KEY = secrets.token_hex(32)
        logging.getLogger(__name__).warning(
            "FLASK_SECRET_KEY no configurada y ADMIN_SECRET ausente - generando una clave efimera. "
            "Define FLASK_SECRET_KEY para mantener sesiones estables."
        )

WEBHOOK_SECRET_TOKEN = os.getenv("WEBHOOK_SECRET_TOKEN")
if not WEBHOOK_SECRET_TOKEN:
    bot_token = os.getenv("BOT_TOKEN", "")
    WEBHOOK_SECRET_TOKEN = hashlib.sha256(f"webhook-{bot_token}".encode()).hexdigest()
    logging.getLogger(__name__).warning(
        "WEBHOOK_SECRET_TOKEN no configurado - derivando un token desde BOT_TOKEN. "
        "Define la variable de entorno para mayor seguridad operativa."
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
