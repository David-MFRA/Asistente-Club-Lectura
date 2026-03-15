import asyncio
import importlib
import os
import sys
import types
import unittest
from unittest.mock import patch


os.environ.setdefault("BOT_TOKEN", "token")
os.environ.setdefault("WEBHOOK_URL", "https://example.com")


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

werkzeug_module = types.ModuleType("werkzeug")
werkzeug_serving_module = types.ModuleType("werkzeug.serving")


def _fake_make_server(*args, **kwargs):
    return object()


werkzeug_serving_module.make_server = _fake_make_server
werkzeug_module.serving = werkzeug_serving_module
sys.modules["werkzeug"] = werkzeug_module
sys.modules["werkzeug.serving"] = werkzeug_serving_module

apscheduler_module = types.ModuleType("apscheduler")
apscheduler_schedulers_module = types.ModuleType("apscheduler.schedulers")
apscheduler_asyncio_module = types.ModuleType("apscheduler.schedulers.asyncio")


class _FakeAsyncIOScheduler:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


apscheduler_asyncio_module.AsyncIOScheduler = _FakeAsyncIOScheduler
apscheduler_schedulers_module.asyncio = apscheduler_asyncio_module
apscheduler_module.schedulers = apscheduler_schedulers_module
sys.modules["apscheduler"] = apscheduler_module
sys.modules["apscheduler.schedulers"] = apscheduler_schedulers_module
sys.modules["apscheduler.schedulers.asyncio"] = apscheduler_asyncio_module

bootstrap = importlib.import_module("app.bootstrap")


class FakeBot:
    def __init__(self):
        self.webhook_calls = []

    async def set_webhook(self, **kwargs):
        self.webhook_calls.append(kwargs)


class FakeTelegramApp:
    def __init__(self):
        self.bot = FakeBot()
        self.calls = []

    async def initialize(self):
        self.calls.append("initialize")

    async def start(self):
        self.calls.append("start")


class FakeScheduler:
    def __init__(self):
        self.started = False

    def start(self):
        self.started = True


class BootstrapTests(unittest.TestCase):
    def test_startup_runs_hooks_and_scheduler_configuration(self):
        telegram_app = FakeTelegramApp()
        scheduler = FakeScheduler()
        trace = []

        async def register_commands():
            trace.append("register_commands")

        def post_scheduler_start():
            trace.append("post_scheduler_start")

        with patch("app.bootstrap.configure_scheduler") as configure_scheduler:
            asyncio.run(
                bootstrap.startup(
                    telegram_app,
                    scheduler,
                    ("job1", "job2"),
                    register_commands=register_commands,
                    post_scheduler_start=post_scheduler_start,
                )
            )

        self.assertEqual(telegram_app.calls, ["initialize", "start"])
        self.assertTrue(scheduler.started)
        self.assertEqual(trace, ["register_commands", "post_scheduler_start"])
        configure_scheduler.assert_called_once_with(scheduler, "job1", "job2")


if __name__ == "__main__":
    unittest.main()
