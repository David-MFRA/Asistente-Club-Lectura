from __future__ import annotations

import json
import logging

from app.services.identity_backfill import backfill_historical_user_identity

logger = logging.getLogger(__name__)


def _dedupe_text_values(values):
    seen = set()
    ordered = []
    for raw in values:
        value = (raw or "").strip()
        if not value:
            continue
        marker = value.casefold()
        if marker in seen:
            continue
        seen.add(marker)
        ordered.append(value)
    return ordered


def apply_migrations(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    cur.execute("SELECT version FROM schema_migrations ORDER BY version")
    applied = {row["version"] for row in cur.fetchall()}

    migrations = [
        ("001_baseline_schema", _migration_001_baseline_schema),
        ("002_identity_and_indexes", _migration_002_identity_and_indexes),
        ("003_cycles_and_reminders_backfill", _migration_003_cycles_and_reminders_backfill),
    ]
    for version, func in migrations:
        if version in applied:
            continue
        func(cur)
        cur.execute(
            "INSERT INTO schema_migrations(version) VALUES (%s) ON CONFLICT (version) DO NOTHING",
            (version,),
        )
        logger.info("Migracion aplicada: %s", version)


def _migration_001_baseline_schema(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS books(
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            author TEXT,
            description TEXT,
            cover TEXT,
            pages INTEGER,
            language_code TEXT,
            source TEXT,
            source_id TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_books_title_author ON books (title, author)")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS book_proposals(
            id SERIAL PRIMARY KEY,
            book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
            proposed_by TEXT NOT NULL,
            cycle_key TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            UNIQUE(book_id, cycle_key)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS book_votes(
            id SERIAL PRIMARY KEY,
            proposal_id INTEGER NOT NULL REFERENCES book_proposals(id) ON DELETE CASCADE,
            user_name TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            UNIQUE(proposal_id, user_name)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS themes(
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            cycle_key TEXT NOT NULL,
            created_by TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            UNIQUE(name, cycle_key)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS theme_votes(
            id SERIAL PRIMARY KEY,
            theme_id INTEGER NOT NULL REFERENCES themes(id) ON DELETE CASCADE,
            user_name TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            UNIQUE(theme_id, user_name)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS meetings(
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            cycle_key TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            book_id INTEGER REFERENCES books(id) ON DELETE SET NULL,
            final_date TIMESTAMP NULL,
            summary TEXT,
            notes TEXT,
            location TEXT,
            created_by TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS meeting_date_options(
            id SERIAL PRIMARY KEY,
            meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
            option_date TIMESTAMP NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            UNIQUE(meeting_id, option_date)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS meeting_date_votes(
            id SERIAL PRIMARY KEY,
            option_id INTEGER NOT NULL REFERENCES meeting_date_options(id) ON DELETE CASCADE,
            user_name TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            UNIQUE(option_id, user_name)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS meeting_attendance(
            id SERIAL PRIMARY KEY,
            meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
            user_name TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            UNIQUE(meeting_id, user_name)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS book_ratings(
            id SERIAL PRIMARY KEY,
            book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
            user_name TEXT NOT NULL,
            score INTEGER NOT NULL CHECK (score BETWEEN 1 AND 5),
            review TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            UNIQUE(book_id, user_name)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_polls(
            id SERIAL PRIMARY KEY,
            cycle_key TEXT NOT NULL,
            chat_id BIGINT NOT NULL,
            message_id BIGINT NOT NULL,
            poll_id TEXT NOT NULL,
            poll_type TEXT NOT NULL DEFAULT 'books',
            meeting_id INTEGER REFERENCES meetings(id) ON DELETE SET NULL,
            is_closed BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS app_config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS reading_progress (
            id SERIAL PRIMARY KEY,
            user_name TEXT NOT NULL,
            book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
            pages_read INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
            UNIQUE(user_name, book_id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS message_templates (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sent_messages (
            id SERIAL PRIMARY KEY,
            message_type TEXT NOT NULL DEFAULT 'custom',
            chat_id BIGINT NOT NULL,
            message_id BIGINT,
            text TEXT NOT NULL,
            sent_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS scheduled_messages (
            id SERIAL PRIMARY KEY,
            text TEXT NOT NULL,
            send_at TIMESTAMP NOT NULL,
            sent BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS book_waitlist (
            id SERIAL PRIMARY KEY,
            book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
            cycle_key TEXT NOT NULL,
            cycle_theme TEXT,
            position_at_time INTEGER,
            votes_at_time INTEGER,
            added_by TEXT NOT NULL DEFAULT 'auto',
            notes TEXT,
            added_at TIMESTAMP NOT NULL DEFAULT NOW(),
            UNIQUE(book_id, cycle_key)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS club_members (
            user_id BIGINT PRIMARY KEY,
            first_name TEXT,
            username TEXT,
            last_seen TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS app_events (
            id SERIAL PRIMARY KEY,
            event_type VARCHAR(30) NOT NULL,
            category VARCHAR(40),
            description TEXT NOT NULL,
            actor TEXT,
            extra JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_audit_log (
            id SERIAL PRIMARY KEY,
            actor TEXT,
            action TEXT NOT NULL,
            route TEXT,
            method VARCHAR(10),
            ip TEXT,
            target_type TEXT,
            target_id TEXT,
            status VARCHAR(20) NOT NULL DEFAULT 'ok',
            result TEXT,
            before_data JSONB,
            after_data JSONB,
            extra JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS bug_reports (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            username TEXT,
            description TEXT NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'open',
            admin_notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS cycles (
            cycle_key TEXT PRIMARY KEY,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            active_theme TEXT,
            proposals_locked BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS poll_option_mappings (
            id SERIAL PRIMARY KEY,
            poll_id TEXT NOT NULL,
            option_index INTEGER NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id BIGINT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(poll_id, option_index)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS poll_user_selections (
            id SERIAL PRIMARY KEY,
            poll_id TEXT NOT NULL,
            user_id BIGINT NOT NULL,
            selected_option_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(poll_id, user_id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS custom_reminders (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            schedule_type TEXT NOT NULL DEFAULT 'interval',
            day_of_week TEXT,
            hour INTEGER,
            minute INTEGER,
            interval_hours INTEGER,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )


def _migration_002_identity_and_indexes(cur):
    cur.execute("ALTER TABLE book_proposals ADD COLUMN IF NOT EXISTS proposed_by_user_id BIGINT")
    cur.execute("ALTER TABLE book_votes ADD COLUMN IF NOT EXISTS user_id BIGINT")
    cur.execute("ALTER TABLE theme_votes ADD COLUMN IF NOT EXISTS user_id BIGINT")
    cur.execute("ALTER TABLE meeting_attendance ADD COLUMN IF NOT EXISTS user_id BIGINT")
    cur.execute("ALTER TABLE reading_progress ADD COLUMN IF NOT EXISTS user_id BIGINT")
    cur.execute("ALTER TABLE book_ratings ADD COLUMN IF NOT EXISTS user_id BIGINT")

    identity_backfill_summary = backfill_historical_user_identity(cur)
    if any(identity_backfill_summary.values()):
        logger.info("Migracion identidad historica aplicada: %s", identity_backfill_summary)

    cur.execute("CREATE INDEX IF NOT EXISTS ix_book_proposals_cycle_active_created ON book_proposals (cycle_key, is_active, created_at DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_book_proposals_proposed_by_user_id ON book_proposals (proposed_by_user_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_book_votes_proposal_id ON book_votes (proposal_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_book_votes_user_id ON book_votes (user_id)")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_book_votes_proposal_user_id ON book_votes (proposal_id, user_id) WHERE user_id IS NOT NULL")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_themes_cycle_active_created ON themes (cycle_key, is_active, created_at DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_theme_votes_theme_id ON theme_votes (theme_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_theme_votes_user_id ON theme_votes (user_id)")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_theme_votes_theme_user_id ON theme_votes (theme_id, user_id) WHERE user_id IS NOT NULL")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_meetings_cycle_status_final_date ON meetings (cycle_key, status, final_date)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_meeting_attendance_meeting_id ON meeting_attendance (meeting_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_meeting_attendance_user_id ON meeting_attendance (user_id)")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_meeting_attendance_meeting_user_id ON meeting_attendance (meeting_id, user_id) WHERE user_id IS NOT NULL")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_telegram_polls_cycle_type_closed_created ON telegram_polls (cycle_key, poll_type, is_closed, created_at DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_telegram_polls_poll_id ON telegram_polls (poll_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_scheduled_messages_sent_send_at ON scheduled_messages (sent, send_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_app_events_type_category_created ON app_events (event_type, category, created_at DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_admin_audit_action_status_created ON admin_audit_log (action, status, created_at DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_bug_reports_status_created ON bug_reports (status, created_at DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_reading_progress_user_id_book_id ON reading_progress (user_id, book_id)")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_reading_progress_book_user_id ON reading_progress (book_id, user_id) WHERE user_id IS NOT NULL")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_book_ratings_book_id ON book_ratings (book_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_book_ratings_user_id ON book_ratings (user_id)")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_book_ratings_book_user_id ON book_ratings (book_id, user_id) WHERE user_id IS NOT NULL")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_cycles_active_updated ON cycles (is_active, updated_at DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_cycles_locked_updated ON cycles (proposals_locked, updated_at DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_poll_option_mappings_poll_id ON poll_option_mappings (poll_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_poll_user_selections_poll_id ON poll_user_selections (poll_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_custom_reminders_enabled_updated ON custom_reminders (enabled, updated_at DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_books_created_at ON books (created_at DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_meetings_created_at ON meetings (created_at DESC)")


def _migration_003_cycles_and_reminders_backfill(cur):
    cur.execute("SELECT value FROM app_config WHERE key = 'active_cycles'")
    active_cycles_row = cur.fetchone()
    active_cycles = _dedupe_text_values((active_cycles_row["value"] if active_cycles_row else "").split(","))

    cur.execute("SELECT value FROM app_config WHERE key = 'active_cycle_key'")
    active_cycle_row = cur.fetchone()
    active_cycle = (active_cycle_row["value"] if active_cycle_row else "") or ""
    if active_cycle and active_cycle not in active_cycles:
        active_cycles.insert(0, active_cycle)

    for cycle_key in active_cycles:
        cur.execute(
            """
            INSERT INTO cycles (cycle_key, is_active, updated_at)
            VALUES (%s, TRUE, NOW())
            ON CONFLICT (cycle_key) DO UPDATE
            SET is_active = TRUE, updated_at = NOW()
            """,
            (cycle_key,),
        )

    cur.execute("SELECT key, value FROM app_config WHERE key LIKE 'active_theme:%'")
    for row in cur.fetchall():
        cycle_key = row["key"].split("active_theme:", 1)[1].strip()
        if not cycle_key:
            continue
        cur.execute(
            """
            INSERT INTO cycles (cycle_key, active_theme, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (cycle_key) DO UPDATE
            SET active_theme = EXCLUDED.active_theme, updated_at = NOW()
            """,
            (cycle_key, row["value"] or None),
        )

    cur.execute("SELECT value FROM app_config WHERE key = 'proposals_locked_for'")
    locked_row = cur.fetchone()
    locked_cycles = _dedupe_text_values((locked_row["value"] if locked_row else "").split(","))
    for cycle_key in locked_cycles:
        cur.execute(
            """
            INSERT INTO cycles (cycle_key, proposals_locked, updated_at)
            VALUES (%s, TRUE, NOW())
            ON CONFLICT (cycle_key) DO UPDATE
            SET proposals_locked = TRUE, updated_at = NOW()
            """,
            (cycle_key,),
        )

    cur.execute("SELECT COUNT(*) AS total FROM custom_reminders")
    custom_reminders_total = cur.fetchone()["total"]
    if custom_reminders_total != 0:
        return
    cur.execute("SELECT value FROM app_config WHERE key = 'custom_reminders'")
    reminders_row = cur.fetchone()
    reminders_raw = reminders_row["value"] if reminders_row else ""
    try:
        legacy_reminders = json.loads(reminders_raw or "[]")
    except Exception:
        legacy_reminders = []
    for reminder in legacy_reminders:
        reminder_id = str(reminder.get("id") or "").strip()
        if not reminder_id:
            continue
        schedule_type = (reminder.get("schedule_type") or "interval").strip() or "interval"
        cur.execute(
            """
            INSERT INTO custom_reminders (
                id, title, message, schedule_type, day_of_week,
                hour, minute, interval_hours, enabled, updated_at
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
            ON CONFLICT (id) DO UPDATE
            SET
                title = EXCLUDED.title,
                message = EXCLUDED.message,
                schedule_type = EXCLUDED.schedule_type,
                day_of_week = EXCLUDED.day_of_week,
                hour = EXCLUDED.hour,
                minute = EXCLUDED.minute,
                interval_hours = EXCLUDED.interval_hours,
                enabled = EXCLUDED.enabled,
                updated_at = NOW()
            """,
            (
                reminder_id,
                (reminder.get("title") or "").strip() or "Recordatorio",
                (reminder.get("message") or "").strip(),
                schedule_type,
                (reminder.get("day_of_week") or "").strip() or None,
                int(reminder["hour"]) if reminder.get("hour") not in (None, "") else None,
                int(reminder["minute"]) if reminder.get("minute") not in (None, "") else None,
                int(reminder["hours"]) if reminder.get("hours") not in (None, "") else None,
                bool(reminder.get("enabled", True)),
            ),
        )
