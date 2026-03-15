import importlib
import sys
import types
import unittest


STATE = {
    "cycle": "2026-04",
    "meeting": None,
    "open_theme_poll": None,
    "open_book_polls": [],
    "open_dates_poll": None,
    "winner": None,
    "dashboard_state": {
        "step": "new_cycle",
        "step_label": "Nuevo ciclo",
        "step_desc": "Crea el ciclo y define las tematicas.",
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
sys.modules.pop("app.services.admin_guidance", None)
importlib.import_module("app.services.bot_context")
admin_guidance = importlib.import_module("app.services.admin_guidance")


class AdminGuidanceTests(unittest.TestCase):
    def setUp(self):
        set_state(
            cycle="2026-04",
            meeting=None,
            open_theme_poll=None,
            open_book_polls=[],
            open_dates_poll=None,
            winner=None,
            dashboard_state={
                "step": "new_cycle",
                "step_label": "Nuevo ciclo",
                "step_desc": "Crea el ciclo y define las tematicas.",
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

    def test_build_dashboard_focus_adds_primary_action_and_meta(self):
        focus = admin_guidance.build_dashboard_focus(
            {
                "step": "meeting_scheduled",
                "step_label": "Reunion programada",
                "step_desc": "Reunion: Abril - 2026-04-18 19:30",
                "step_action": "Anunciar fecha al grupo",
                "step_url": "/admin/wizard/announce-date",
                "winner": {"title": "Dune"},
            },
            active_cycles=["2026-04", "2026-03"],
            alert_count=2,
        )

        self.assertEqual(focus["links"][0]["kind"], "primary")
        self.assertEqual(focus["links"][0]["url"], "/admin/wizard/announce-date")
        self.assertTrue(any("alerta" in item for item in focus["meta"]))
        self.assertEqual(len(focus["checklist"]), 3)

    def test_build_cycle_easy_guidance_changes_with_books_phase(self):
        guidance = admin_guidance.build_cycle_easy_guidance(
            {"phase": "books", "meeting": None, "winner": None}
        )

        self.assertIn("propuestas", guidance["summary"].lower())
        self.assertTrue(any(link["url"] == "/admin/ciclo" for link in guidance["links"]))

    def test_build_bot_context_previews_returns_snapshot_and_admin_card(self):
        set_state(
            winner={"title": "Dune", "author": "Frank Herbert"},
            meeting={"id": 7, "name": "Debate Dune", "final_date": "2026-04-18 19:30"},
            dashboard_state={
                "step": "meeting_scheduled",
                "step_label": "Reunion programada",
                "step_desc": "La reunion ya tiene fecha.",
            },
        )

        previews = admin_guidance.build_bot_context_previews("2026-04")

        self.assertEqual(previews["snapshot"]["cycle"], "2026-04")
        self.assertEqual(len(previews["cards"]), 4)
        self.assertTrue(any("/admin_ayuda" in card["text"] for card in previews["cards"]))


if __name__ == "__main__":
    unittest.main()
