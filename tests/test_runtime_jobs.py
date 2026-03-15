import asyncio
import sys
import types
import unittest
from types import SimpleNamespace


telegram_module = types.ModuleType("telegram")


class _FakeBotCommand:
    def __init__(self, command, description):
        self.command = command
        self.description = description


class _FakeScopeAllGroupChats:
    pass


class _FakeScopeAllPrivateChats:
    pass


class _FakeScopeChat:
    def __init__(self, chat_id):
        self.chat_id = chat_id


telegram_module.BotCommand = _FakeBotCommand
telegram_module.BotCommandScopeAllGroupChats = _FakeScopeAllGroupChats
telegram_module.BotCommandScopeAllPrivateChats = _FakeScopeAllPrivateChats
telegram_module.BotCommandScopeChat = _FakeScopeChat
sys.modules["telegram"] = telegram_module

from app.runtime.jobs import RuntimeJobs


class FakeScheduler:
    def __init__(self):
        self.jobs = [SimpleNamespace(id="custom_reminder_old"), SimpleNamespace(id="weekly_reminder")]
        self.removed = []
        self.added = []

    def get_jobs(self):
        return list(self.jobs)

    def remove_job(self, job_id):
        self.removed.append(job_id)

    def add_job(self, func, trigger, **kwargs):
        self.added.append({"func": func, "trigger": trigger, **kwargs})


class FakeBot:
    def __init__(self):
        self.calls = []

    async def set_my_commands(self, commands, scope):
        self.calls.append({"commands": commands, "scope": scope})


class FakeDB:
    def get_custom_reminders(self):
        return [
            {"id": "r1", "message": "hola", "schedule_type": "interval", "interval_hours": 6, "enabled": True},
            {"id": "r2", "message": "", "schedule_type": "interval", "interval_hours": 6, "enabled": True},
            {"id": "r3", "message": "bye", "schedule_type": "cron", "day_of_week": "mon", "hour": 10, "minute": 30, "enabled": False},
        ]

    def get_config(self, key, default=None):
        return default

    def get_current_cycle_key(self):
        return "2026-03"


class FakeLogger:
    def info(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def exception(self, *args, **kwargs):
        return None


class RuntimeJobsTests(unittest.TestCase):
    def test_reload_custom_reminders_replaces_existing_custom_jobs(self):
        scheduler = FakeScheduler()
        jobs = RuntimeJobs(
            db=FakeDB(),
            scheduler=scheduler,
            telegram_app=SimpleNamespace(bot=FakeBot()),
            logger=FakeLogger(),
            webhook_url="https://example.com",
            admin_ids=["1"],
            get_contextual_commands=lambda *args, **kwargs: [],
        )

        async def fake_send_to_group(*args, **kwargs):
            return None

        jobs.reload_custom_reminders(fake_send_to_group)

        self.assertEqual(scheduler.removed, ["custom_reminder_old"])
        self.assertEqual(len(scheduler.added), 1)
        self.assertEqual(scheduler.added[0]["id"], "custom_reminder_r1")

    def test_register_runtime_bot_commands_updates_group_private_and_admin_scopes(self):
        bot = FakeBot()
        jobs = RuntimeJobs(
            db=FakeDB(),
            scheduler=FakeScheduler(),
            telegram_app=SimpleNamespace(bot=bot),
            logger=FakeLogger(),
            webhook_url="https://example.com",
            admin_ids=["1", "2"],
            get_contextual_commands=lambda *args, **kwargs: [
                {"id": "ayuda", "emoji": "?", "desc": "Ayuda"},
                {"id": "tema", "emoji": "#", "desc": "Tema"},
            ],
        )

        asyncio.run(jobs.register_runtime_bot_commands())

        self.assertEqual(len(bot.calls), 4)


if __name__ == "__main__":
    unittest.main()
