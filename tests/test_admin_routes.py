import copy
import html
import importlib
import os
import re
import sys
import types
import unittest
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = ROOT / "tests" / "snapshots"
MODULES_TO_RESET = [
    "app.admin_panel",
    "app.services.admin_audit",
    "app.services.admin_guidance",
    "app.services.bot_context",
    "app.web.admin.routes",
    "app.web.admin.catalog",
    "app.web.admin.monitoring",
    "app.web.admin.messaging",
    "app.web.admin.site",
    "app.web.admin.insights",
    "app.web.admin.demo",
]


def _default_state():
    winner = {
        "id": 1,
        "proposal_id": 11,
        "title": "Dune",
        "author": "Frank Herbert",
        "votes": 5,
        "pages": 412,
        "cover": "",
        "cycle_key": "2026-04",
    }
    meeting = {
        "id": 7,
        "name": "Debate Dune",
        "cycle_key": "2026-04",
        "status": "scheduled",
        "final_date": "2026-04-18 19:30",
        "book_id": 1,
        "location": "Biblioteca central",
    }
    return {
        "cycle": "2026-04",
        "active_cycles": ["2026-04", "2026-03"],
        "all_cycles": ["2026-04", "2026-03"],
        "books": [winner],
        "book_ranking": [winner],
        "meetings": [meeting],
        "meeting": meeting,
        "latest_meeting": {
            "id": 6,
            "name": "Cierre Dune",
            "status": "closed",
            "summary": "Buen debate",
            "final_date": "2026-03-01 19:30",
        },
        "themes": [{"id": 21, "name": "Desiertos", "cycle_key": "2026-04", "created_by": "admin", "is_active": True}],
        "public_proposals": [winner],
        "top_theme": {"id": 21, "name": "Desiertos", "votes": 4},
        "gallery": [],
        "winner": winner,
        "dashboard_state": {
            "step": "meeting_scheduled",
            "step_label": "Reunion programada",
            "step_desc": "La reunion ya tiene fecha y falta comunicarla.",
            "step_action": "Anunciar fecha al grupo",
            "step_url": "/admin/wizard/announce-date",
        },
        "cycle_states": [
            {
                "cycle": "2026-04",
                "step": "meeting_scheduled",
                "step_label": "Reunion programada",
                "step_desc": "La reunion ya tiene fecha y falta comunicarla.",
                "step_action": "Anunciar fecha al grupo",
                "step_url": "/admin/wizard/announce-date",
                "is_default": True,
                "winner": winner,
            }
        ],
        "open_theme_poll": None,
        "open_book_polls": [],
        "open_dates_poll": None,
        "tied_books": [],
        "operational_alerts": [
            {
                "level": "warning",
                "title": "Recordatorio semanal desactivado",
                "message": "Revisa el programador para activarlo.",
                "action_url": "/admin/scheduler",
                "action_label": "Abrir programador",
            }
        ],
        "audit": [
            {
                "action": "admin_login",
                "actor": "Tester",
                "status": "ok",
                "created_at": "2026-03-15 10:00",
            }
        ],
        "events": [
            {
                "id": 1,
                "event_type": "admin",
                "category": "auth",
                "description": "Inicio de sesion",
                "actor": "Tester",
                "created_at": "2026-03-15 10:00",
            }
        ],
        "public_access_logs": [],
        "blocked_admin_ips": {},
        "bugs": [
            {
                "id": 3,
                "username": "maria",
                "status": "open",
                "description": "No carga el panel",
                "admin_notes": None,
                "created_at": "2026-03-15 11:00",
            },
            {
                "id": 4,
                "username": "luis",
                "status": "resolved",
                "description": "Error puntual en /ayuda",
                "admin_notes": "Arreglado",
                "created_at": "2026-03-14 11:00",
            },
        ],
        "scheduled_messages": [
            {"id": 1, "text": "Recordatorio de prueba", "send_at": datetime(2026, 3, 20, 10, 0), "sent": False}
        ],
        "custom_reminders": [
            {
                "id": "read24",
                "title": "Lectura",
                "message": "Avanza 25 paginas",
                "schedule_type": "interval",
                "enabled": True,
                "interval_hours": 24,
            }
        ],
        "config": {
            "reminder_weekly_enabled": "1",
            "reminder_reading_enabled": "1",
            "reminder_daybefore_enabled": "1",
            "reminder_keepalive_enabled": "1",
            "last_webhook_received_at": "2026-03-14T10:00:00",
        },
        "attendance": ["Marta", "Luis"],
        "date_options": [{"id": 1, "option_date": "2026-04-18 19:30"}],
        "settings": {
            "private_highlights": [],
            "group_highlights": [],
            "hidden_commands": [],
            "context_note": "",
            "help_note": "",
            "soft_mode_enabled": True,
        },
        "tables": {
            "books": [{"id": 1, "title": "Dune", "author": "Frank Herbert"}],
            "meetings": [{"id": 7, "name": "Debate Dune", "status": "scheduled"}],
        },
        "admin_audit_rows": [],
        "db_sql_calls": [],
        "db_delete_calls": [],
        "db_truncate_calls": [],
    }


class FakeDb(types.ModuleType):
    def __init__(self, state):
        super().__init__("db")
        self.state = state

    def __getattr__(self, name):
        raise AttributeError(f"FakeDb missing attribute: {name}")

    def init_db(self):
        return None

    def get_current_cycle_key(self):
        return self.state["cycle"]

    def get_books(self, cycle_key=None):
        return copy.deepcopy(self.state["books"])

    def get_book_ranking(self):
        return copy.deepcopy(self.state["book_ranking"])

    def get_meetings(self, limit=50, cycle_key=None):
        return copy.deepcopy(self.state["meetings"][:limit])

    def get_themes(self, cycle_key=None):
        return copy.deepcopy(self.state["themes"])

    def get_book_proposals(self, cycle_key=None):
        return copy.deepcopy(self.state["public_proposals"])

    def get_top_theme(self, cycle_key=None):
        return copy.deepcopy(self.state["top_theme"])

    def get_galeria_data(self, limit=3):
        return copy.deepcopy(self.state["gallery"][:limit])

    def get_open_polls(self, poll_type="books", cycle_key=None):
        return copy.deepcopy(self.state["open_book_polls"]) if poll_type == "books" else []

    def get_open_poll(self, poll_type="books", cycle_key=None, meeting_id=None):
        mapping = {
            "themes": self.state["open_theme_poll"],
            "books": self.state["open_book_polls"][0] if self.state["open_book_polls"] else None,
            "dates": self.state["open_dates_poll"],
        }
        return copy.deepcopy(mapping.get(poll_type))

    def get_active_cycle_states(self):
        return copy.deepcopy(self.state["cycle_states"])

    def get_tied_books(self, cycle_key=None):
        return copy.deepcopy(self.state["tied_books"])

    def get_active_cycle_keys(self):
        return list(self.state["active_cycles"])

    def get_all_cycle_keys(self):
        return list(self.state["all_cycles"])

    def get_operational_alerts(self):
        return copy.deepcopy(self.state["operational_alerts"])

    def get_admin_audit_logs(self, limit=200, action=None, status=None):
        rows = list(self.state["audit"])
        if action:
            rows = [row for row in rows if row["action"] == action]
        if status:
            rows = [row for row in rows if row["status"] == status]
        return copy.deepcopy(rows[:limit])

    def get_events(self, limit=300, event_type=None, category=None):
        rows = list(self.state["events"])
        if event_type:
            rows = [row for row in rows if row["event_type"] == event_type]
        if category:
            rows = [row for row in rows if row["category"] == category]
        return copy.deepcopy(rows[:limit])

    def get_bug_reports(self, status=None):
        rows = list(self.state["bugs"])
        if status:
            rows = [row for row in rows if row["status"] == status]
        return copy.deepcopy(rows)

    def log_public_page_access(self, **kwargs):
        row = {
            "id": len(self.state["public_access_logs"]) + 1,
            "route": kwargs.get("route", "/publico"),
            "method": kwargs.get("method", "GET"),
            "ip": kwargs.get("ip"),
            "user_agent": kwargs.get("user_agent"),
            "referrer": kwargs.get("referrer"),
            "query_string": kwargs.get("query_string"),
            "created_at": "2026-03-15 12:30",
        }
        self.state["public_access_logs"].insert(0, row)

    def get_public_page_access_logs(self, limit=300, ip=None):
        rows = list(self.state["public_access_logs"])
        if ip:
            rows = [row for row in rows if row["ip"] == ip]
        return copy.deepcopy(rows[:limit])

    def is_admin_ip_blocked(self, ip):
        row = self.state["blocked_admin_ips"].get((ip or "").strip())
        return bool(row and row.get("blocked_at"))

    def register_admin_login_failure(self, ip, block_after=3):
        key = (ip or "").strip() or "unknown"
        row = dict(self.state["blocked_admin_ips"].get(key) or {})
        attempts = int(row.get("failed_attempts") or 0) + 1
        is_blocked = attempts >= block_after
        updated = {
            "ip": key,
            "failed_attempts": attempts,
            "first_failed_at": row.get("first_failed_at") or "2026-03-15 11:58",
            "last_failed_at": "2026-03-15 12:00",
            "blocked_at": "2026-03-15 12:00" if is_blocked else None,
            "block_reason": f"admin_login_failed_{block_after}x" if is_blocked else None,
        }
        self.state["blocked_admin_ips"][key] = updated
        return {
            **copy.deepcopy(updated),
            "is_blocked": is_blocked,
            "just_blocked": is_blocked and not row.get("blocked_at"),
        }

    def clear_admin_login_failures(self, ip):
        key = (ip or "").strip()
        row = self.state["blocked_admin_ips"].get(key)
        if not row or row.get("blocked_at"):
            return 0
        self.state["blocked_admin_ips"].pop(key, None)
        return 1

    def get_admin_ip_state(self, ip):
        row = self.state["blocked_admin_ips"].get((ip or "").strip())
        return copy.deepcopy(row) if row else None

    def get_blocked_admin_ips(self, limit=200):
        rows = [row for row in self.state["blocked_admin_ips"].values() if row.get("blocked_at")]
        rows.sort(key=lambda row: (row.get("blocked_at") or "", row.get("last_failed_at") or ""), reverse=True)
        return copy.deepcopy(rows[:limit])

    def unblock_admin_ip(self, ip):
        key = (ip or "").strip()
        row = self.state["blocked_admin_ips"].get(key)
        if not row or not row.get("blocked_at"):
            return None
        released = copy.deepcopy(row)
        self.state["blocked_admin_ips"].pop(key, None)
        return released

    def update_bug_report(self, report_id, status, admin_notes=None):
        for row in self.state["bugs"]:
            if row["id"] == report_id:
                row["status"] = status
                row["admin_notes"] = admin_notes
                return

    def get_all_scheduled_messages(self):
        return copy.deepcopy(self.state["scheduled_messages"])

    def get_custom_reminders(self):
        return copy.deepcopy(self.state["custom_reminders"])

    def get_config(self, key, default=None):
        return self.state["config"].get(key, default)

    def get_message_template_scoped(self, key, audience=None, phase=None, cycle_key=None):
        return None, None

    def set_config(self, key, value):
        self.state["config"][key] = value

    def get_latest_scheduled_meeting(self, cycle_key=None):
        return copy.deepcopy(self.state["meeting"])

    def get_winner_book(self, cycle_key=None):
        return copy.deepcopy(self.state["winner"])

    def get_cycle_dashboard_state(self, cycle=None, _proposals_locked_for=None):
        return copy.deepcopy(self.state["dashboard_state"])

    def get_latest_meeting(self):
        return copy.deepcopy(self.state["latest_meeting"])

    def get_cycle_bot_settings(self, cycle_key=None):
        return copy.deepcopy(self.state["settings"])

    def get_attendance(self, meeting_id=None):
        return list(self.state["attendance"])

    def get_meeting_date_options(self, meeting_id):
        return copy.deepcopy(self.state["date_options"])

    def get_cycle_state(self, cycle_key):
        for row in self.state["cycle_states"]:
            if row["cycle"] == cycle_key:
                return copy.deepcopy(row)
        return copy.deepcopy(self.state["cycle_states"][0])

    def get_table_names(self):
        return list(self.state["tables"].keys())

    def get_table_rows(self, table_name, limit=200):
        rows = copy.deepcopy(self.state["tables"][table_name][:limit])
        cols = list(rows[0].keys()) if rows else []
        return cols, rows, cols[0] if cols else None

    def get_table_columns(self, table_name):
        rows = self.state["tables"][table_name]
        first = rows[0] if rows else {}
        columns = []
        for name, value in first.items():
            columns.append(
                {
                    "name": name,
                    "data_type": type(value).__name__ if value is not None else "text",
                    "is_json": False,
                    "is_array": False,
                    "is_textarea": isinstance(value, str) and len(str(value)) > 30,
                    "is_nullable": True,
                    "is_boolean": isinstance(value, bool),
                }
            )
        return columns

    def get_table_row(self, table_name, pk_column, pk_value):
        for row in self.state["tables"][table_name]:
            if str(row.get(pk_column)) == str(pk_value):
                return copy.deepcopy(row)
        return None

    def format_table_value_for_form(self, value):
        return "" if value is None else str(value)

    def delete_table_row(self, table_name, pk_column, pk_value):
        self.state["db_delete_calls"].append((table_name, pk_column, pk_value))
        rows = self.state["tables"][table_name]
        before = len(rows)
        self.state["tables"][table_name] = [row for row in rows if str(row.get(pk_column)) != str(pk_value)]
        return before - len(self.state["tables"][table_name])

    def update_table_row(self, table_name, pk_column, pk_value, updates):
        for row in self.state["tables"][table_name]:
            if str(row.get(pk_column)) != str(pk_value):
                continue
            for column, payload in updates.items():
                row[column] = None if payload["set_null"] else payload["value"]
            return 1
        return 0

    def truncate_table(self, table_name):
        self.state["db_truncate_calls"].append(table_name)
        self.state["tables"][table_name] = []

    def execute_raw_sql(self, sql):
        self.state["db_sql_calls"].append(sql)
        if sql.strip().lower().startswith("select"):
            rows = copy.deepcopy(self.state["tables"]["books"])
            cols = list(rows[0].keys()) if rows else []
            return cols, rows, len(rows), True
        return [], [], 1, False

    def log_admin_audit(self, action, **kwargs):
        self.state["admin_audit_rows"].append({"action": action, **kwargs})

    def log_event(self, event_type, description, category=None, actor=None, extra=None):
        self.state["events"].insert(
            0,
            {
                "id": len(self.state["events"]) + 1,
                "event_type": event_type,
                "category": category,
                "description": description,
                "actor": actor,
                "created_at": "2026-03-15 12:00",
            },
        )


class FakeObservability:
    def record_request(self, *args, **kwargs):
        return None

    def snapshot(self):
        return {
            "requests": {"count": 12, "errors": 0, "avg_duration_ms": 18},
            "recent_errors": [],
        }


def build_test_app(state_overrides=None):
    state = _default_state()
    if state_overrides:
        state.update(copy.deepcopy(state_overrides))
    fake_db = FakeDb(state)
    sys.modules["db"] = fake_db
    for module_name in [
        "flask",
        "flask.app",
        "flask.testing",
        "flask.templating",
        "werkzeug",
        "werkzeug.serving",
        "werkzeug.local",
        "werkzeug.test",
        "telegram",
        "telegram.ext",
    ]:
        sys.modules.pop(module_name, None)
    for module_name in MODULES_TO_RESET:
        sys.modules.pop(module_name, None)
    real_flask = importlib.import_module("flask")
    admin_panel = importlib.import_module("app.admin_panel")

    app = real_flask.Flask(
        "admin-test",
        template_folder=str(ROOT / "templates"),
        static_folder=str(ROOT / "static"),
    )
    app.secret_key = "test-secret"
    app.testing = True

    async def _noop_send(*args, **kwargs):
        return True

    class _Webhook:
        def handle_request(self, request):
            return {"ok": True}, 200

    admin_panel.install_admin_panel(
        app,
        admin_secret="supersecret",
        webhook_url="https://club.example.com",
        observability=FakeObservability(),
        run_async=lambda result: result,
        send_to_group=_noop_send,
        send_and_pin=_noop_send,
        send_meeting_reminder=_noop_send,
        send_reading_reminder=_noop_send,
        announce_winner=_noop_send,
        logger=importlib.import_module("logging").getLogger("admin-test"),
        telegram_app=types.SimpleNamespace(bot=types.SimpleNamespace()),
        telegram_chat_id="-100123",
        default_messages={},
        group_invite_link="https://t.me/test",
        reload_custom_reminders=lambda: None,
        utcnow=lambda: importlib.import_module("datetime").datetime(2026, 3, 15, 10, 0, 0),
        admin_search_limiter=types.SimpleNamespace(allow=lambda *args, **kwargs: True),
        poll_formatting={"bold": lambda value: value, "italic": lambda value: value, "esc": lambda value: value},
        webhook_handler=_Webhook(),
    )
    return app, fake_db


def login(client):
    response = client.post(
        "/admin/login",
        data={"display_name": "Tester", "secret": "supersecret"},
        follow_redirects=False,
    )
    if response.status_code != 302:
        raise AssertionError(f"Login failed with {response.status_code}")


def get_csrf_token(client):
    with client.session_transaction() as session:
        return session["csrf_token"]


def build_visual_outline(html_text):
    content = re.sub(r"<(script|style).*?</\1>", "", html_text, flags=re.S | re.I)
    content = re.sub(r"<[^>]+>", "\n", content)
    lines = []
    seen = set()
    for raw_line in content.splitlines():
        line = " ".join(html.unescape(raw_line).split())
        if not line or line in seen:
            continue
        if len(line) > 110:
            continue
        seen.add(line)
        lines.append(line)
    return "\n".join(lines[:70]).strip() + "\n"


class AdminRoutesTests(unittest.TestCase):
    def assert_matches_snapshot(self, name, html_text):
        SNAPSHOT_DIR.mkdir(exist_ok=True)
        outline = build_visual_outline(html_text)
        snapshot_path = SNAPSHOT_DIR / f"{name}.txt"
        if os.getenv("UPDATE_SNAPSHOTS") == "1":
            snapshot_path.write_text(outline, encoding="utf-8")
        expected = snapshot_path.read_text(encoding="utf-8")
        self.assertEqual(outline, expected)

    def test_login_page_renders(self):
        app, _ = build_test_app()
        with app.test_client() as client:
            response = client.get("/admin/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Panel de administracion", response.get_data(as_text=True))
        self.assertEqual(
            response.headers.get("X-Robots-Tag"),
            "noindex, nofollow, noarchive",
        )

    def test_dashboard_route_renders_and_legacy_admin_redirects(self):
        app, _ = build_test_app()
        with app.test_client() as client:
            login(client)
            dashboard_response = client.get("/dashboard", follow_redirects=False)
            legacy_response = client.get("/admin", follow_redirects=False)
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertIn("Torre de control", dashboard_response.get_data(as_text=True))
        self.assertEqual(legacy_response.status_code, 301)
        self.assertEqual(legacy_response.headers["Location"], "/dashboard")

    def test_cycle_scheduler_and_bugs_routes_render(self):
        app, _ = build_test_app()
        with app.test_client() as client:
            login(client)
            cycle_response = client.get("/admin/ciclo")
            scheduler_response = client.get("/admin/scheduler")
            bugs_response = client.get("/admin/bugs?status=open")
            public_settings_response = client.get("/admin/public-settings")
        self.assertEqual(cycle_response.status_code, 200)
        self.assertIn("Lectura de", cycle_response.get_data(as_text=True))
        self.assertEqual(scheduler_response.status_code, 200)
        self.assertIn("Recordatorio de prueba", scheduler_response.get_data(as_text=True))
        self.assertEqual(bugs_response.status_code, 200)
        self.assertIn("No carga el panel", bugs_response.get_data(as_text=True))
        self.assertNotIn("Error puntual", bugs_response.get_data(as_text=True))
        self.assertEqual(public_settings_response.status_code, 200)
        self.assertIn("URL canonica", public_settings_response.get_data(as_text=True))

    def test_public_root_is_canonical_and_publico_redirects(self):
        app, fake_db = build_test_app()
        with app.test_client() as client:
            response = client.get(
                "/?utm=web",
                headers={
                    "X-Forwarded-For": "203.0.113.10",
                    "Referer": "https://club.example.com/",
                    "User-Agent": "CodexTest/1.0",
                },
            )
            legacy_response = client.get("/publico", follow_redirects=False)
            login(client)
            logs_response = client.get("/admin/public-access")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(legacy_response.status_code, 301)
        self.assertEqual(legacy_response.headers["Location"], "/")
        self.assertEqual(logs_response.status_code, 200)
        self.assertEqual(fake_db.state["public_access_logs"][0]["ip"], "203.0.113.10")
        self.assertEqual(fake_db.state["public_access_logs"][0]["route"], "/")
        self.assertIn("203.0.113.10", logs_response.get_data(as_text=True))
        self.assertIn("CodexTest/1.0", logs_response.get_data(as_text=True))
        public_html = response.get_data(as_text=True)
        self.assertIn("data:image/svg+xml;base64,", public_html)
        self.assertNotIn("api.qrserver.com", public_html)
        self.assertIn('<link rel="canonical" href="http://localhost/">', public_html)

    def test_admin_ip_is_blocked_after_three_failed_logins(self):
        app, fake_db = build_test_app()
        with app.test_client() as client:
            headers = {"X-Forwarded-For": "198.51.100.8"}
            first = client.post("/admin/login", data={"display_name": "Tester", "secret": "wrong-1"}, headers=headers)
            second = client.post("/admin/login", data={"display_name": "Tester", "secret": "wrong-2"}, headers=headers)
            third = client.post("/admin/login", data={"display_name": "Tester", "secret": "wrong-3"}, headers=headers)
            fourth = client.post("/admin/login", data={"display_name": "Tester", "secret": "supersecret"}, headers=headers)
        self.assertEqual(first.status_code, 403)
        self.assertEqual(second.status_code, 403)
        self.assertEqual(third.status_code, 423)
        self.assertEqual(fourth.status_code, 423)
        self.assertTrue(fake_db.is_admin_ip_blocked("198.51.100.8"))
        blocked_rows = [row for row in fake_db.state["admin_audit_rows"] if row.get("status") == "blocked"]
        self.assertTrue(blocked_rows)
        self.assertIn("bloqueada", fourth.get_data(as_text=True).lower())

    def test_admin_security_page_can_unblock_ips(self):
        app, fake_db = build_test_app()
        fake_db.state["blocked_admin_ips"]["198.51.100.8"] = {
            "ip": "198.51.100.8",
            "failed_attempts": 3,
            "first_failed_at": "2026-03-15 11:58",
            "last_failed_at": "2026-03-15 12:00",
            "blocked_at": "2026-03-15 12:00",
            "block_reason": "admin_login_failed_3x",
        }
        with app.test_client() as client:
            login(client)
            security_page = client.get("/admin/security")
            token = get_csrf_token(client)
            unblock_response = client.post(
                "/admin/security/unblock",
                data={"ip": "198.51.100.8", "csrf_token": token},
                follow_redirects=True,
            )
        self.assertEqual(security_page.status_code, 200)
        self.assertIn("198.51.100.8", security_page.get_data(as_text=True))
        self.assertEqual(unblock_response.status_code, 200)
        self.assertNotIn("198.51.100.8", fake_db.state["blocked_admin_ips"])
        self.assertIn("desbloqueada", unblock_response.get_data(as_text=True).lower())
        self.assertTrue(
            any(row["action"] == "admin_ip_unblock" for row in fake_db.state["admin_audit_rows"])
        )

    def test_db_page_respects_read_only_policy_and_blocks_sql(self):
        os.environ["ADMIN_DB_READ_ONLY"] = "1"
        os.environ["ADMIN_DB_ALLOW_RAW_SQL"] = "0"
        app, fake_db = build_test_app()
        with app.test_client() as client:
            login(client)
            response = client.get("/admin/db")
            token = get_csrf_token(client)
            sql_response = client.post("/admin/db/sql", data={"sql": "SELECT * FROM books", "csrf_token": token})
            delete_response = client.post(
                "/admin/db/books/delete",
                data={"pk_name": "id", "pk_value": "1", "csrf_token": token},
                follow_redirects=True,
            )
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Solo lectura", body)
        self.assertIn("SQL desactivado", body)
        self.assertEqual(sql_response.status_code, 403)
        self.assertEqual(fake_db.state["db_delete_calls"], [])
        self.assertIn("modo lectura", delete_response.get_data(as_text=True).lower())
        os.environ.pop("ADMIN_DB_READ_ONLY", None)
        os.environ.pop("ADMIN_DB_ALLOW_RAW_SQL", None)

    def test_db_sql_allows_select_when_enabled(self):
        os.environ["ADMIN_DB_READ_ONLY"] = "1"
        os.environ["ADMIN_DB_ALLOW_RAW_SQL"] = "1"
        app, fake_db = build_test_app()
        with app.test_client() as client:
            login(client)
            token = get_csrf_token(client)
            response = client.post("/admin/db/sql", data={"sql": "SELECT * FROM books", "csrf_token": token})
        self.assertEqual(response.status_code, 200)
        self.assertIn("SELECT * FROM books", fake_db.state["db_sql_calls"][0])
        os.environ.pop("ADMIN_DB_READ_ONLY", None)
        os.environ.pop("ADMIN_DB_ALLOW_RAW_SQL", None)

    def test_simulator_renders_selected_scenario(self):
        app, _ = build_test_app()
        with app.test_client() as client:
            login(client)
            response = client.get("/admin/simulator?scenario=tie")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Escenario activo", body)
        self.assertIn("Empate", body)

    def test_visual_snapshots(self):
        app, _ = build_test_app()
        with app.test_client() as client:
            login_page = client.get("/admin/login").get_data(as_text=True)
            login(client)
            dashboard = client.get("/dashboard").get_data(as_text=True)
            simulator = client.get("/admin/simulator?scenario=tie").get_data(as_text=True)
        self.assert_matches_snapshot("admin_dashboard", dashboard)
        self.assert_matches_snapshot("admin_simulator_tie", simulator)
        self.assert_matches_snapshot("admin_login", login_page)


if __name__ == "__main__":
    unittest.main()
