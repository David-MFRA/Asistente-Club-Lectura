import logging

import db
from telegram.error import ChatMigrated

logger = logging.getLogger(__name__)


class TelegramMessagingService:
    def __init__(self, get_bot, chat_id, logger):
        self.get_bot = get_bot
        self.chat_id = chat_id
        self.logger = logger

    async def send_to_group(self, text, parse_mode="MarkdownV2", reply_markup=None, message_type="custom"):
        if not self.chat_id:
            self.logger.warning("TELEGRAM_CHAT_ID no configurado")
            return False
        try:
            msg = await self.get_bot().send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
            try:
                db.log_sent_message(message_type, self.chat_id, text, msg.message_id)
            except Exception:
                pass
            return True
        except ChatMigrated as exc:
            new_id = exc.new_chat_id
            self.logger.warning(
                "Grupo migrado a supergrupo. Nuevo chat_id: %s. "
                "Actualiza TELEGRAM_CHAT_ID y ALLOWED_CHAT_ID en Render.",
                new_id,
            )
            db.set_config("migrated_chat_id", str(new_id))
            self.chat_id = new_id
            try:
                msg = await self.get_bot().send_message(
                    chat_id=self.chat_id,
                    text=text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                )
                db.log_sent_message(message_type, self.chat_id, text, msg.message_id)
                return True
            except Exception:
                self.logger.exception("Error enviando al nuevo chat_id tras migración")
                return False
        except Exception:
            self.logger.exception("Error enviando al grupo")
            return False

    async def send_and_pin(self, text, parse_mode=None, reply_markup=None):
        if not self.chat_id:
            return False, False
        try:
            msg = await self.get_bot().send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
            try:
                await self.get_bot().pin_chat_message(
                    chat_id=self.chat_id,
                    message_id=msg.message_id,
                    disable_notification=True,
                )
                existing = db.get_config("pinned_message_ids") or ""
                ids = [value for value in existing.split(",") if value.strip()]
                ids.append(str(msg.message_id))
                db.set_config("pinned_message_ids", ",".join(ids))
                db.set_config("pinned_message_id", str(msg.message_id))
                return True, True
            except Exception as exc:
                self.logger.warning("No se pudo fijar el mensaje: %s", exc)
                return True, False
        except Exception:
            self.logger.exception("Error en send_and_pin")
            return False, False

    async def unpin_group_message(self):
        pinned_id = db.get_config("pinned_message_id")
        if pinned_id and self.chat_id:
            try:
                await self.get_bot().unpin_chat_message(
                    chat_id=self.chat_id,
                    message_id=int(pinned_id),
                )
                db.set_config("pinned_message_id", "")
            except Exception:
                self.logger.warning("No se pudo desfijar el mensaje")
