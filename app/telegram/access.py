import time


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
        if now - last < seconds:
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
            return member.status not in ("left", "kicked", "banned")
        except Exception:
            return False

    async def allowed(self, update) -> bool:
        chat = update.effective_chat
        if not self.allowed_chat_id:
            return True
        if update.effective_user and str(update.effective_user.id) in self.admin_ids:
            return True
        if chat.type in ("group", "supergroup"):
            return str(chat.id) == str(self.allowed_chat_id)
        if chat.type == "private":
            return await self.is_group_member(update.effective_user.id)
        return False
