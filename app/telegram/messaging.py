import logging

import db
from telegram.error import ChatMigrated

logger = logging.getLogger(__name__)


class TelegramMessagingService:
    def __init__(self, get_bot, chat_id, logger):
        self.get_bot = get_bot
        self.chat_id = chat_id
        self.logger = logger

    async def send_to_group(self, text, parse_mode=None, reply_markup=None, message_type="custom"):
        if not self.chat_id:
            self.logger.warning("TELEGRAM_CHAT_ID no configurado")
            db.log_event("error", "Intento de envio sin TELEGRAM_CHAT_ID", category="telegram", actor="bot")
            return False
        self.logger.info("send_to_group: tipo=%s chat_id=%s (%d chars)", message_type, self.chat_id, len(text))
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
            db.log_event(
                "bot",
                f"Mensaje enviado al grupo ({message_type})",
                category="telegram",
                actor="bot",
                extra={"chat_id": self.chat_id, "message_id": msg.message_id, "message_type": message_type},
            )
            return True
        except ChatMigrated as exc:
            new_id = exc.new_chat_id
            self.logger.warning(
                "Grupo migrado a supergrupo. Nuevo chat_id: %s. Actualiza TELEGRAM_CHAT_ID y ALLOWED_CHAT_ID.",
                new_id,
            )
            db.set_config("migrated_chat_id", str(new_id))
            db.log_event(
                "system",
                f"Grupo migrado a {new_id}",
                category="telegram",
                actor="bot",
                extra={"old_chat_id": self.chat_id, "new_chat_id": new_id},
            )
            self.chat_id = new_id
            try:
                msg = await self.get_bot().send_message(
                    chat_id=self.chat_id,
                    text=text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                )
                db.log_sent_message(message_type, self.chat_id, text, msg.message_id)
                db.log_event(
                    "bot",
                    f"Mensaje reenviado tras migración ({message_type})",
                    category="telegram",
                    actor="bot",
                    extra={"chat_id": self.chat_id, "message_id": msg.message_id, "message_type": message_type},
                )
                return True
            except Exception as exc2:
                self.logger.exception("Error enviando al nuevo chat_id tras migración")
                db.log_event(
                    "error",
                    "Fallo enviando mensaje tras migración de chat",
                    category="telegram",
                    actor="bot",
                    extra={"chat_id": self.chat_id, "error": type(exc2).__name__, "message_type": message_type},
                )
                return False
        except Exception as exc:
            self.logger.exception("Error enviando al grupo")
            db.log_event(
                "error",
                "Fallo enviando mensaje al grupo",
                category="telegram",
                actor="bot",
                extra={"chat_id": self.chat_id, "error": type(exc).__name__, "message_type": message_type},
            )
            return False

    async def send_and_pin(self, text, parse_mode=None, reply_markup=None):
        if not self.chat_id:
            db.log_event("error", "Intento de pin sin TELEGRAM_CHAT_ID", category="telegram", actor="bot")
            return False, False
        self.logger.info("send_and_pin: chat_id=%s (%d chars)", self.chat_id, len(text))
        try:
            msg = await self.get_bot().send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
            db.log_event(
                "bot",
                "Mensaje enviado para fijado",
                category="telegram",
                actor="bot",
                extra={"chat_id": self.chat_id, "message_id": msg.message_id},
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
                db.log_event(
                    "bot",
                    "Mensaje fijado en el grupo",
                    category="telegram",
                    actor="bot",
                    extra={"chat_id": self.chat_id, "message_id": msg.message_id},
                )
                return True, True
            except Exception as exc:
                self.logger.warning("No se pudo fijar el mensaje: %s", exc)
                db.log_event(
                    "error",
                    "No se pudo fijar el mensaje",
                    category="telegram",
                    actor="bot",
                    extra={"chat_id": self.chat_id, "message_id": msg.message_id, "error": type(exc).__name__},
                )
                return True, False
        except Exception as exc:
            self.logger.exception("Error en send_and_pin")
            db.log_event(
                "error",
                "Error enviando mensaje para fijar",
                category="telegram",
                actor="bot",
                extra={"chat_id": self.chat_id, "error": type(exc).__name__},
            )
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
                db.log_event(
                    "bot",
                    "Mensaje desfijado del grupo",
                    category="telegram",
                    actor="bot",
                    extra={"chat_id": self.chat_id, "message_id": int(pinned_id)},
                )
            except Exception as exc:
                self.logger.warning("No se pudo desfijar el mensaje")
                db.log_event(
                    "error",
                    "No se pudo desfijar el mensaje",
                    category="telegram",
                    actor="bot",
                    extra={"chat_id": self.chat_id, "message_id": pinned_id, "error": type(exc).__name__},
                )
