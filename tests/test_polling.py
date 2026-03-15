import asyncio
import sys
import types
import unittest
from types import SimpleNamespace


flask_module = types.ModuleType("flask")


class _FakeResponse:
    def __init__(self, status=200):
        self.status_code = int(status)


flask_module.Response = _FakeResponse
sys.modules["flask"] = flask_module

telegram_module = types.ModuleType("telegram")


class _FakeUpdate:
    @staticmethod
    def de_json(data, bot):
        return {"data": data, "bot": bot}


telegram_module.Update = _FakeUpdate
sys.modules["telegram"] = telegram_module

from app.telegram.polling import PollAnswerHandler


class FakeDB:
    def __init__(self):
        self.calls = []

    def get_poll_by_telegram_id(self, poll_id):
        return {"poll_id": poll_id, "poll_type": "books", "is_closed": False}

    def get_poll_option_mapping(self, poll_id):
        return [101, 202, 303]

    def get_poll_user_selection(self, poll_id, user_id):
        return [0]

    def remove_book_vote(self, entity_id, user_name, user_id):
        self.calls.append(("remove_book_vote", entity_id, user_name, user_id))

    def vote_book(self, entity_id, user_name, user_id):
        self.calls.append(("vote_book", entity_id, user_name, user_id))

    def set_poll_user_selection(self, poll_id, user_id, option_ids):
        self.calls.append(("set_poll_user_selection", poll_id, user_id, list(option_ids)))

    def log_event(self, *args, **kwargs):
        self.calls.append(("log_event", args, kwargs))


class FakeLogger:
    def info(self, *args, **kwargs):
        return None

    def exception(self, *args, **kwargs):
        return None


class PollAnswerHandlerTests(unittest.TestCase):
    def test_poll_answer_uses_user_id_when_username_changes(self):
        db = FakeDB()
        handler = PollAnswerHandler(db=db, logger=FakeLogger())
        update = SimpleNamespace(
            poll_answer=SimpleNamespace(
                poll_id="poll-1",
                user=SimpleNamespace(id=77, first_name="NuevoNombre", username="nuevo_user"),
                option_ids=[2],
            )
        )

        asyncio.run(handler(update, None))

        self.assertIn(("remove_book_vote", 101, "NuevoNombre", 77), db.calls)
        self.assertIn(("vote_book", 303, "NuevoNombre", 77), db.calls)
        self.assertIn(("set_poll_user_selection", "poll-1", 77, [2]), db.calls)


if __name__ == "__main__":
    unittest.main()
