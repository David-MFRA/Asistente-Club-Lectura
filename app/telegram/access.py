import logging
import time

logger = logging.getLogger(__name__)


class TelegramAccessControl:
    def __init__(self, allowed_chat_id, admin_ids, get_bot):
        self.allowed_chat_id = allowed_chat_id
        self.admin_ids = admin_ids
        self.get_bot = get_bot
        self.cooldowns = {}

    def check_cooldown(self, user_id: int, command: str, seconds: int = 20) -> bool:
        key = (user_id, command)
        now = time.monotonic()
        last = self.cooldowns.get(key, 0)
        remaining = seconds - (now - last)
        if remaining > 0:
            logger.debug("Cooldown activo: user_id=%d comando=%s (%.1fs restantes)", user_id, command, remaining)
            return False
        self.cooldowns[key] = now
        return True

    async def is_group_member(self, user_id: int) -> bool:
        if not self.allowed_chat_id:
            return True
        try:
            member = await self.get_bot().get_chat_member(
                chat_id=int(self.allowed_chat_id),
                user_id=user_id,
            )
            is_member = member.status not in ("left", "kicked", "banned")
            if not is_member:
                logger.warning("Acceso denegado (no miembro): user_id=%d status=%s", user_id, member.status)
            return is_member
        except Exception:
            logger.exception("Error comprobando membresía: user_id=%d", user_id)
            return False

    async def allowed(self, update) -> bool:
        chat = update.effective_chat
        user = update.effective_user
        if not self.allowed_chat_id:
            return True
        if user and str(user.id) in self.admin_ids:
            return True
        if chat.type in ("group", "supergroup"):
            ok = str(chat.id) == str(self.allowed_chat_id)
            if not ok:
                logger.warning("Acceso denegado (grupo no permitido): chat_id=%s user_id=%s", chat.id, user.id if user else "?")
            return ok
        if chat.type == "private":
            ok = await self.is_group_member(user.id)
            if not ok:
                logger.warning("Acceso denegado (privado, no miembro): user_id=%d nombre=%s", user.id, user.first_name or user.username)
            return ok
        return False
