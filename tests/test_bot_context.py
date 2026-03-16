import importlib
import sys
import types
import unittest


STATE = {
    "cycle": "2026-03",
    "meeting": None,
    "open_theme_poll": None,
    "open_book_polls": [],
    "open_dates_poll": None,
    "winner": None,
    "dashboard_state": {
        "step": "collecting_proposals",
        "step_label": "Recogiendo propuestas",
        "step_desc": "Anade propuestas de libros para este ciclo.",
    },
    "latest_meeting": None,
    "settings": {
        "private_highlights": [],
        "group_highlights": [],
        "hidden_commands": [],
        "context_note": "",
        "help_note": "",
        "soft_mode_enabled": True,
    },
    "themes": [],
    "books": [],
}


def set_state(**overrides):
    STATE.update(overrides)


fake_db = types.ModuleType("db")


def _get_open_poll(poll_type="themes", cycle_key=None, meeting_id=None):
    if poll_type == "themes":
        return STATE["open_theme_poll"]
    if poll_type == "dates":
        return STATE["open_dates_poll"]
    if poll_type == "books":
        return STATE["open_book_polls"][0] if STATE["open_book_polls"] else None
    return None


def _get_open_polls(poll_type="books", cycle_key=None):
    if poll_type == "books":
        return list(STATE["open_book_polls"])
    return []


fake_db.get_current_cycle_key = lambda: STATE["cycle"]
fake_db.get_latest_scheduled_meeting = lambda cycle_key=None: STATE["meeting"]
fake_db.get_open_poll = _get_open_poll
fake_db.get_open_polls = _get_open_polls
fake_db.get_winner_book = lambda cycle_key=None: STATE["winner"]
fake_db.get_cycle_dashboard_state = lambda cycle=None: STATE["dashboard_state"]
fake_db.get_latest_meeting = lambda: STATE["latest_meeting"]
fake_db.get_cycle_bot_settings = lambda cycle_key=None: dict(STATE["settings"])
fake_db.get_themes = lambda cycle_key=None: list(STATE["themes"])
fake_db.get_books = lambda cycle_key=None: list(STATE["books"])

sys.modules["db"] = fake_db
sys.modules.pop("app.services.bot_context", None)
bot_context = importlib.import_module("app.services.bot_context")


class BotContextTests(unittest.TestCase):
    def setUp(self):
        set_state(
            cycle="2026-03",
            meeting=None,
            open_theme_poll=None,
            open_book_polls=[],
            open_dates_poll=None,
            winner=None,
            dashboard_state={
                "step": "collecting_proposals",
                "step_label": "Recogiendo propuestas",
                "step_desc": "Anade propuestas de libros para este ciclo.",
            },
            latest_meeting=None,
            settings={
                "private_highlights": [],
                "group_highlights": [],
                "hidden_commands": [],
                "context_note": "",
                "help_note": "",
                "soft_mode_enabled": True,
            },
            themes=[],
            books=[],
        )

    def test_get_contextual_commands_prioritizes_theme_poll_follow_up(self):
        set_state(
            open_theme_poll={"id": 99},
            themes=[{"id": 1, "name": "Distopias"}],
        )

        commands = bot_context.get_contextual_commands("private", "2026-03", is_admin=False)
        command_ids = [item["id"] for item in commands[:4]]

        self.assertEqual(command_ids[:3], ["temas", "tema", "recomendar"])
        self.assertNotIn("votar_tema", [item["id"] for item in commands])
        self.assertNotIn("admin_ayuda", [item["id"] for item in commands])
        self.assertNotIn("asistir", [item["id"] for item in commands])

    def test_build_help_text_includes_phase_examples_and_help_note(self):
        set_state(
            open_book_polls=[{"id": 5}],
            dashboard_state={
                "step": "poll_open",
                "step_label": "Encuesta de libros abierta",
                "step_desc": "La encuesta esta activa en Telegram.",
            },
            settings={
                "private_highlights": [],
                "group_highlights": [],
                "hidden_commands": [],
                "context_note": "",
                "help_note": "Prioriza cerrar la votacion hoy.",
                "soft_mode_enabled": True,
            },
        )

        text = bot_context.build_help_text(is_admin=False, cycle_key="2026-03", audience="private")

        self.assertIn("Encuesta de libros abierta", text)
        self.assertIn("Ejemplos rapidos", text)
        self.assertIn("/propuestas", text)
        self.assertIn("encuestas nativas", text)
        self.assertIn("Prioriza cerrar la votacion hoy.", text)

    def test_build_welcome_text_for_admin_mentions_admin_help(self):
        set_state(
            winner={"title": "Dune", "author": "Frank Herbert"},
            meeting={"id": 1, "name": "Sesion Dune", "final_date": "2026-03-18 19:30"},
        )

        text, commands = bot_context.build_welcome_text("Marta", is_admin=True, cycle_key="2026-03")

        self.assertIn("Dune", text)
        self.assertIn("/admin_ayuda", text)
        self.assertIn("admin_ayuda", [item["id"] for item in commands])

    def test_resolve_private_shortcut_supports_plain_labels(self):
        self.assertEqual(bot_context.resolve_private_shortcut("Ver reunion"), "reunion")
        self.assertEqual(bot_context.resolve_private_shortcut("Ayuda admin"), "admin_ayuda")

    def test_answer_help_question_explains_pinned_poll(self):
        set_state(open_book_polls=[{"id": 5}])

        answer = bot_context.answer_help_question("donde se vota", cycle_key="2026-03")

        self.assertIn("encuesta fijada", answer)
        self.assertIn("/propuestas", answer)

    def test_answer_help_question_can_suggest_next_steps(self):
        set_state(
            winner={"title": "Dune", "author": "Frank Herbert"},
            meeting={"id": 1, "name": "Sesion Dune", "final_date": "2026-03-18 19:30"},
        )

        answer = bot_context.answer_help_question("que hago ahora", cycle_key="2026-03")

        self.assertIn("Lo mas util ahora", answer)
        self.assertIn("Ver reunion", answer)

    def test_resolve_private_intent_understands_simple_language(self):
        self.assertEqual(bot_context.resolve_private_intent("me apunto"), "asistir")
        self.assertEqual(bot_context.resolve_private_intent("quiero proponer un libro"), "proponer")
        self.assertEqual(bot_context.resolve_private_intent("menu"), "ayuda")


if __name__ == "__main__":
    unittest.main()
