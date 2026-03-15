import logging
import os
import json
from contextlib import contextmanager
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _utcnow():
    """Retorna datetime UTC naive (sin tzinfo) sin deprecation warning."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

import psycopg2
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Falta DATABASE_URL")

pool = SimpleConnectionPool(minconn=1, maxconn=5, dsn=DATABASE_URL)


@contextmanager
def get_conn():
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)


@contextmanager
def get_cursor(commit=False):
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            yield cur
            if commit:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()


def init_db():
    with get_cursor(commit=True) as cur:
        cur.execute("""
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
        )""")
        cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_books_title_author ON books (title, author)
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS book_proposals(
            id SERIAL PRIMARY KEY,
            book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
            proposed_by TEXT NOT NULL,
            cycle_key TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            UNIQUE(book_id, cycle_key)
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS book_votes(
            id SERIAL PRIMARY KEY,
            proposal_id INTEGER NOT NULL REFERENCES book_proposals(id) ON DELETE CASCADE,
            user_name TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            UNIQUE(proposal_id, user_name)
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS themes(
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            cycle_key TEXT NOT NULL,
            created_by TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            UNIQUE(name, cycle_key)
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS theme_votes(
            id SERIAL PRIMARY KEY,
            theme_id INTEGER NOT NULL REFERENCES themes(id) ON DELETE CASCADE,
            user_name TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            UNIQUE(theme_id, user_name)
        )""")
        cur.execute("""
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
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS meeting_date_options(
            id SERIAL PRIMARY KEY,
            meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
            option_date TIMESTAMP NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            UNIQUE(meeting_id, option_date)
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS meeting_date_votes(
            id SERIAL PRIMARY KEY,
            option_id INTEGER NOT NULL REFERENCES meeting_date_options(id) ON DELETE CASCADE,
            user_name TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            UNIQUE(option_id, user_name)
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS meeting_attendance(
            id SERIAL PRIMARY KEY,
            meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
            user_name TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            UNIQUE(meeting_id, user_name)
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS book_ratings(
            id SERIAL PRIMARY KEY,
            book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
            user_name TEXT NOT NULL,
            score INTEGER NOT NULL CHECK (score BETWEEN 1 AND 5),
            review TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            UNIQUE(book_id, user_name)
        )""")
        # Tabla de encuestas Telegram con tipo y meeting_id opcional
        cur.execute("""
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
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS app_config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP NOT NULL DEFAULT NOW()
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS reading_progress (
            id SERIAL PRIMARY KEY,
            user_name TEXT NOT NULL,
            book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
            pages_read INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
            UNIQUE(user_name, book_id)
        )""")
        # Tabla de plantillas de mensajes editables desde admin
        cur.execute("""
        CREATE TABLE IF NOT EXISTS message_templates (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP NOT NULL DEFAULT NOW()
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS sent_messages (
            id SERIAL PRIMARY KEY,
            message_type TEXT NOT NULL DEFAULT 'custom',
            chat_id BIGINT NOT NULL,
            message_id BIGINT,
            text TEXT NOT NULL,
            sent_at TIMESTAMP NOT NULL DEFAULT NOW()
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_messages (
            id SERIAL PRIMARY KEY,
            text TEXT NOT NULL,
            send_at TIMESTAMP NOT NULL,
            sent BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )""")
        cur.execute("""
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
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS club_members (
            user_id BIGINT PRIMARY KEY,
            first_name TEXT,
            username TEXT,
            last_seen TIMESTAMP NOT NULL DEFAULT NOW()
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS app_events (
            id SERIAL PRIMARY KEY,
            event_type VARCHAR(30) NOT NULL,
            category VARCHAR(40),
            description TEXT NOT NULL,
            actor TEXT,
            extra JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS bug_reports (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            username TEXT,
            description TEXT NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'open',
            admin_notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""")


# =========================================================
# HELPERS
# =========================================================

def current_cycle_key(dt=None):
    dt = dt or _utcnow()
    return dt.strftime("%Y-%m")

def get_config(key, default=None):
    try:
        with get_cursor() as cur:
            cur.execute("SELECT value FROM app_config WHERE key = %s", (key,))
            row = cur.fetchone()
            return row["value"] if row else default
    except Exception:
        return default

def set_config(key, value):
    with get_cursor(commit=True) as cur:
        cur.execute("""
        INSERT INTO app_config(key, value) VALUES(%s,%s)
        ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()
        """, (key, str(value)))

def get_current_cycle_key():
    stored = get_config("active_cycle_key")
    return stored if stored else current_cycle_key()


def _dedupe_text_values(values):
    unique = []
    seen = set()
    for value in values:
        item = (value or "").strip()
        if not item or item in seen:
            continue
        unique.append(item)
        seen.add(item)
    return unique


def get_locked_cycle_keys():
    raw = get_config("proposals_locked_for") or ""
    return _dedupe_text_values(raw.split(","))


def set_locked_cycle_keys(keys):
    set_config("proposals_locked_for", ",".join(_dedupe_text_values(keys)))


def lock_cycle_proposals(cycle_key):
    keys = get_locked_cycle_keys()
    if cycle_key not in keys:
        keys.append(cycle_key)
        set_locked_cycle_keys(keys)
    logger.info("Propuestas bloqueadas para ciclo=%s", cycle_key)


def unlock_cycle_proposals(cycle_key=None):
    if not cycle_key:
        set_locked_cycle_keys([])
        logger.info("Propuestas desbloqueadas para todos los ciclos")
        return
    keys = [key for key in get_locked_cycle_keys() if key != cycle_key]
    set_locked_cycle_keys(keys)
    logger.info("Propuestas desbloqueadas para ciclo=%s", cycle_key)


# =========================================================
# BOOKS
# =========================================================

def _get_book_by_title_author(title, author):
    with get_cursor() as cur:
        cur.execute("""
        SELECT * FROM books
        WHERE title = %s AND author IS NOT DISTINCT FROM %s
        LIMIT 1
        """, (title, author))
        return cur.fetchone()


def create_or_get_book(book):
    title  = (book.get("title") or "").strip()
    author = (book.get("author") or "").strip() or None
    existing = _get_book_by_title_author(title, author)
    if existing:
        return dict(existing)
    with get_cursor(commit=True) as cur:
        cur.execute("""
        INSERT INTO books(title, author, description, cover, pages, language_code, source, source_id)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *
        """, (title, author, book.get("description"), book.get("cover"),
              book.get("pages"), book.get("language_code"), book.get("source"), book.get("source_id")))
        return dict(cur.fetchone())


def insert_book(book, proposed_by="telegram", cycle_key=None):
    cycle_key = cycle_key or get_current_cycle_key()
    book_row  = create_or_get_book(book)
    with get_cursor(commit=True) as cur:
        cur.execute("""
        INSERT INTO book_proposals(book_id, proposed_by, cycle_key)
        VALUES(%s,%s,%s)
        ON CONFLICT (book_id, cycle_key) DO NOTHING
        RETURNING *
        """, (book_row["id"], proposed_by, cycle_key))
        row = cur.fetchone()
        if row:
            logger.info("Libro propuesto: «%s» por %s en ciclo %s (book_id=%d, proposal_id=%d)",
                        book_row["title"], proposed_by, cycle_key, book_row["id"], row["id"])
            return {"inserted": True, **dict(row)}
        # Already proposed — return existing
        logger.warning("Libro duplicado ignorado: «%s» por %s en ciclo %s (book_id=%d)",
                       book_row["title"], proposed_by, cycle_key, book_row["id"])
        cur.execute(
            "SELECT * FROM book_proposals WHERE book_id=%s AND cycle_key=%s",
            (book_row["id"], cycle_key)
        )
        return {"inserted": False, **dict(cur.fetchone())}


def remove_book_proposal(proposal_id):
    """Elimina una propuesta del ciclo (el admin puede quitarla)."""
    logger.info("Propuesta eliminada: proposal_id=%d", proposal_id)
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM book_proposals WHERE id = %s", (proposal_id,))


def get_books(cycle_key=None):
    cycle_key = cycle_key or get_current_cycle_key()
    with get_cursor() as cur:
        cur.execute("""
        SELECT ROW_NUMBER() OVER (ORDER BY sub.votes DESC, sub.title ASC)::int AS cycle_position, sub.*
        FROM (
            SELECT
                bp.id AS proposal_id, bp.cycle_key, b.id, b.title, b.author,
                b.description, b.cover, b.pages, bp.proposed_by,
                COUNT(bv.id)::int AS votes
            FROM book_proposals bp
            JOIN books b ON b.id = bp.book_id
            LEFT JOIN book_votes bv ON bv.proposal_id = bp.id
            WHERE bp.cycle_key = %s AND bp.is_active = TRUE
            GROUP BY bp.id, bp.cycle_key, b.id, b.title, b.author, b.description, b.cover, b.pages, bp.proposed_by
        ) sub
        ORDER BY sub.votes DESC, sub.title ASC
        """, (cycle_key,))
        return [dict(r) for r in cur.fetchall()]


def get_book_proposals(cycle_key=None):
    return get_books(cycle_key)


def get_proposal_by_id(proposal_id):
    with get_cursor() as cur:
        cur.execute("""
        SELECT bp.id AS proposal_id, bp.cycle_key, b.id, b.title, b.author, b.description, b.cover, b.pages,
               bp.proposed_by, COUNT(bv.id)::int AS votes
        FROM book_proposals bp
        JOIN books b ON b.id = bp.book_id
        LEFT JOIN book_votes bv ON bv.proposal_id = bp.id
        WHERE bp.id = %s
        GROUP BY bp.id, bp.cycle_key, b.id, b.title, b.author, b.description, b.cover, b.pages, bp.proposed_by
        """, (proposal_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def vote_book(proposal_id, user_name):
    with get_cursor(commit=True) as cur:
        cur.execute("""
        INSERT INTO book_votes(proposal_id, user_name)
        VALUES(%s,%s) ON CONFLICT (proposal_id, user_name) DO NOTHING RETURNING id
        """, (proposal_id, user_name))
        ok = cur.fetchone() is not None
        if ok:
            logger.info("Voto libro registrado: proposal_id=%d, user=%s", proposal_id, user_name)
        else:
            logger.warning("Voto libro duplicado ignorado: proposal_id=%d, user=%s", proposal_id, user_name)
        return ok


def get_cycle_results(cycle_key=None):
    return get_books(cycle_key)


def close_cycle_proposals(cycle_key=None):
    cycle_key = cycle_key or get_current_cycle_key()
    with get_cursor(commit=True) as cur:
        cur.execute("UPDATE book_proposals SET is_active = FALSE WHERE cycle_key = %s", (cycle_key,))


def get_winner_book(cycle_key=None):
    books = get_books(cycle_key)
    return books[0] if books else None


def get_tied_books(cycle_key=None):
    """Returns list of books tied at the top. Empty list if no tie."""
    books = get_books(cycle_key)
    if len(books) < 2:
        return []
    max_votes = books[0].get('votes', 0)
    if max_votes == 0:
        return []
    tied = [b for b in books if b.get('votes', 0) == max_votes]
    return tied if len(tied) > 1 else []


def get_book_by_id(book_id):
    with get_cursor() as cur:
        cur.execute("SELECT * FROM books WHERE id = %s", (book_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_votes():
    books = get_books()
    return [{"title": b["title"], "votes": b["votes"]} for b in books]


# =========================================================
# THEMES
# =========================================================

def create_theme(name, created_by=None, cycle_key=None):
    cycle_key = cycle_key or get_current_cycle_key()
    with get_cursor(commit=True) as cur:
        cur.execute("""
        INSERT INTO themes(name, cycle_key, created_by)
        VALUES(%s,%s,%s) ON CONFLICT (name, cycle_key) DO NOTHING RETURNING *
        """, (name.strip(), cycle_key, created_by))
        row = cur.fetchone()
        if row:
            logger.info("Temática creada: «%s» por %s en ciclo %s (id=%d)", name, created_by, cycle_key, row["id"])
        else:
            logger.warning("Temática duplicada ignorada: «%s» en ciclo %s", name, cycle_key)
        return dict(row) if row else None


def get_themes(cycle_key=None):
    cycle_key = cycle_key or get_current_cycle_key()
    with get_cursor() as cur:
        cur.execute("""
        SELECT t.id, t.name, t.cycle_key, COUNT(tv.id)::int AS votes
        FROM themes t
        LEFT JOIN theme_votes tv ON tv.theme_id = t.id
        WHERE t.cycle_key = %s AND t.is_active = TRUE
        GROUP BY t.id, t.name, t.cycle_key
        ORDER BY votes DESC, t.name ASC
        """, (cycle_key,))
        return [dict(r) for r in cur.fetchall()]


def get_theme_by_id(theme_id):
    with get_cursor() as cur:
        cur.execute("SELECT * FROM themes WHERE id = %s", (theme_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def vote_theme(theme_id, user_name):
    with get_cursor(commit=True) as cur:
        cur.execute("""
        INSERT INTO theme_votes(theme_id, user_name)
        VALUES(%s,%s) ON CONFLICT (theme_id, user_name) DO NOTHING RETURNING id
        """, (theme_id, user_name))
        ok = cur.fetchone() is not None
        if ok:
            logger.info("Voto temática registrado: theme_id=%d, user=%s", theme_id, user_name)
        else:
            logger.warning("Voto temática duplicado ignorado: theme_id=%d, user=%s", theme_id, user_name)
        return ok


def get_top_theme(cycle_key=None):
    themes = get_themes(cycle_key)
    return themes[0] if themes else None


def get_tied_themes(cycle_key=None):
    """Returns list of themes tied at the top vote count. Empty if no tie."""
    themes = get_themes(cycle_key)
    if len(themes) < 2:
        return []
    max_votes = themes[0].get("votes", 0)
    if max_votes == 0:
        return []
    tied = [t for t in themes if t.get("votes", 0) == max_votes]
    return tied if len(tied) > 1 else []


def get_theme_previous_cycles(name):
    """Devuelve los ciclos anteriores donde esta temática fue usada."""
    current = get_current_cycle_key()
    with get_cursor() as cur:
        cur.execute("""
        SELECT cycle_key, COUNT(tv.id)::int AS votes
        FROM themes t
        LEFT JOIN theme_votes tv ON tv.theme_id = t.id
        WHERE LOWER(t.name) = LOWER(%s) AND t.cycle_key != %s
        GROUP BY t.cycle_key
        ORDER BY t.cycle_key DESC
        """, (name.strip(), current))
        return [dict(r) for r in cur.fetchall()]


# =========================================================
# MEETINGS
# =========================================================

def create_meeting(name, final_date=None, cycle_key=None, created_by=None, book_id=None, status="draft"):
    cycle_key = cycle_key or get_current_cycle_key()
    with get_cursor(commit=True) as cur:
        cur.execute("""
        INSERT INTO meetings(name, cycle_key, final_date, created_by, book_id, status)
        VALUES(%s,%s,%s,%s,%s,%s) RETURNING *
        """, (name.strip(), cycle_key, final_date, created_by, book_id, status))
        row = dict(cur.fetchone())
        logger.info("Reunión creada: «%s» (id=%d) en ciclo %s por %s", name, row["id"], cycle_key, created_by)
        return row


def get_meetings(limit=50, cycle_key=None):
    with get_cursor() as cur:
        if cycle_key:
            cur.execute("""
            SELECT m.*, b.title AS book_title
            FROM meetings m
            LEFT JOIN books b ON b.id = m.book_id
            WHERE m.cycle_key = %s
            ORDER BY COALESCE(m.final_date, m.created_at) DESC
            LIMIT %s
            """, (cycle_key, limit))
        else:
            cur.execute("""
            SELECT m.*, b.title AS book_title
            FROM meetings m
            LEFT JOIN books b ON b.id = m.book_id
            ORDER BY COALESCE(m.final_date, m.created_at) DESC
            LIMIT %s
            """, (limit,))
        return [dict(r) for r in cur.fetchall()]


def get_meeting(meeting_id):
    with get_cursor() as cur:
        cur.execute("""
        SELECT m.*, b.title AS book_title
        FROM meetings m
        LEFT JOIN books b ON b.id = m.book_id
        WHERE m.id = %s
        """, (meeting_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_latest_meeting():
    with get_cursor() as cur:
        cur.execute("""
        SELECT * FROM meetings
        ORDER BY COALESCE(final_date, created_at) DESC LIMIT 1
        """)
        row = cur.fetchone()
        return dict(row) if row else None


def get_latest_scheduled_meeting(cycle_key=None):
    """Devuelve la PRÓXIMA reunión (soonest future date). Si no hay con fecha futura, la más reciente."""
    with get_cursor() as cur:
        params = []
        cycle_sql = ""
        if cycle_key:
            cycle_sql = " AND cycle_key = %s"
            params.append(cycle_key)
        # Próxima reunión futura (la más cercana)
        cur.execute("""
        SELECT * FROM meetings
        WHERE status IN ('scheduled', 'draft')
        """ + cycle_sql + """
          AND (final_date IS NULL OR final_date > NOW())
        ORDER BY final_date ASC NULLS LAST, created_at ASC
        LIMIT 1
        """, tuple(params))
        row = cur.fetchone()
        if row:
            return dict(row)
        # Fallback: la más reciente si no hay fechas futuras
        cur.execute("""
        SELECT * FROM meetings
        WHERE status IN ('scheduled', 'draft')
        """ + cycle_sql + """
        ORDER BY COALESCE(final_date, created_at) DESC LIMIT 1
        """, tuple(params))
        row = cur.fetchone()
        return dict(row) if row else None


def add_meeting_date_option(meeting_id, option_date):
    logger.info("Opción de fecha añadida: meeting_id=%d fecha=%s", meeting_id, option_date)
    with get_cursor(commit=True) as cur:
        cur.execute("""
        INSERT INTO meeting_date_options(meeting_id, option_date)
        VALUES(%s,%s) ON CONFLICT (meeting_id, option_date) DO NOTHING RETURNING *
        """, (meeting_id, option_date))
        row = cur.fetchone()
        return dict(row) if row else None


def get_meeting_date_options(meeting_id):
    with get_cursor() as cur:
        cur.execute("""
        SELECT mdo.id, mdo.option_date, COUNT(mdv.id)::int AS votes
        FROM meeting_date_options mdo
        LEFT JOIN meeting_date_votes mdv ON mdv.option_id = mdo.id
        WHERE mdo.meeting_id = %s
        GROUP BY mdo.id, mdo.option_date
        ORDER BY votes DESC, mdo.option_date ASC
        """, (meeting_id,))
        return [dict(r) for r in cur.fetchall()]


def vote_meeting_date(option_id, user_name):
    with get_cursor(commit=True) as cur:
        cur.execute("""
        INSERT INTO meeting_date_votes(option_id, user_name)
        VALUES(%s,%s) ON CONFLICT (option_id, user_name) DO NOTHING RETURNING id
        """, (option_id, user_name))
        return cur.fetchone() is not None


def set_meeting_final_date(meeting_id, final_date):
    logger.info("Fecha reunión fijada: meeting_id=%d → %s", meeting_id, final_date)
    with get_cursor(commit=True) as cur:
        cur.execute("""
        UPDATE meetings SET final_date=%s, status='scheduled', updated_at=NOW()
        WHERE id=%s
        """, (final_date, meeting_id))


def update_meeting(meeting_id, name=None, final_date=None, summary=None, status=None, book_id=None, location=None, notes=None):
    fields, values = [], []
    if name is not None:       fields.append("name = %s");       values.append(name)
    if final_date is not None: fields.append("final_date = %s"); values.append(final_date)
    if summary is not None:    fields.append("summary = %s");    values.append(summary)
    if status is not None:     fields.append("status = %s");     values.append(status)
    if book_id is not None:    fields.append("book_id = %s");    values.append(book_id)
    if location is not None:   fields.append("location = %s");   values.append(location or None)
    if notes is not None:      fields.append("notes = %s");      values.append(notes or None)
    if not fields:
        return
    fields.append("updated_at = NOW()")
    values.append(meeting_id)
    with get_cursor(commit=True) as cur:
        cur.execute(f"UPDATE meetings SET {', '.join(fields)} WHERE id = %s", tuple(values))


def delete_meeting(meeting_id):
    logger.info("Reunión eliminada: meeting_id=%d", meeting_id)
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM meetings WHERE id = %s", (meeting_id,))


def add_attendance(meeting_id, user_name):
    with get_cursor(commit=True) as cur:
        cur.execute("""
        INSERT INTO meeting_attendance(meeting_id, user_name)
        VALUES(%s,%s) ON CONFLICT (meeting_id, user_name) DO NOTHING RETURNING id
        """, (meeting_id, user_name))
        ok = cur.fetchone() is not None
        if ok:
            logger.info("Asistencia añadida: %s a reunion_id=%d", user_name, meeting_id)
        else:
            logger.warning("Asistencia duplicada ignorada: %s ya en reunion_id=%d", user_name, meeting_id)
        return ok


def remove_attendance(meeting_id, user_name):
    logger.info("Asistencia eliminada: %s de reunion_id=%d", user_name, meeting_id)
    with get_cursor(commit=True) as cur:
        cur.execute("""
        DELETE FROM meeting_attendance WHERE meeting_id=%s AND user_name=%s
        """, (meeting_id, user_name))


def get_attendance(meeting_id=None):
    with get_cursor() as cur:
        if meeting_id is None:
            cur.execute("SELECT meeting_id, user_name FROM meeting_attendance ORDER BY meeting_id DESC, user_name ASC")
            return [dict(r) for r in cur.fetchall()]
        cur.execute("""
        SELECT user_name FROM meeting_attendance
        WHERE meeting_id=%s ORDER BY user_name ASC
        """, (meeting_id,))
        return [r["user_name"] for r in cur.fetchall()]


def get_meeting_attendance_count(meeting_id):
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*)::int AS total FROM meeting_attendance WHERE meeting_id=%s", (meeting_id,))
        return cur.fetchone()["total"]


# =========================================================
# RATINGS
# =========================================================

def rate_book(book_id, user_name, score, review=None):
    logger.info("Valoración libro: book_id=%d user=%s score=%d", book_id, user_name, score)
    with get_cursor(commit=True) as cur:
        cur.execute("""
        INSERT INTO book_ratings(book_id, user_name, score, review)
        VALUES(%s,%s,%s,%s)
        ON CONFLICT (book_id, user_name) DO UPDATE SET score=EXCLUDED.score, review=EXCLUDED.review
        RETURNING *
        """, (book_id, user_name, score, review))
        return dict(cur.fetchone())


def get_book_ranking():
    with get_cursor() as cur:
        cur.execute("""
        SELECT b.id, b.title, b.author,
               ROUND(AVG(br.score)::numeric, 2) AS avg_score,
               COUNT(br.id)::int AS total_reviews
        FROM book_ratings br
        JOIN books b ON b.id = br.book_id
        GROUP BY b.id, b.title, b.author
        ORDER BY avg_score DESC NULLS LAST, total_reviews DESC, b.title ASC
        """)
        return [dict(r) for r in cur.fetchall()]


def get_book_ratings_for_book(book_id):
    with get_cursor() as cur:
        cur.execute("""
        SELECT user_name, score, review, created_at FROM book_ratings
        WHERE book_id=%s ORDER BY created_at DESC
        """, (book_id,))
        return [dict(r) for r in cur.fetchall()]


# =========================================================
# TELEGRAM POLLS
# =========================================================

def save_poll(chat_id, message_id, poll_id, poll_type="books", cycle_key=None, meeting_id=None):
    cycle_key = cycle_key or get_current_cycle_key()
    with get_cursor(commit=True) as cur:
        cur.execute("""
        INSERT INTO telegram_polls(cycle_key, chat_id, message_id, poll_id, poll_type, meeting_id)
        VALUES(%s,%s,%s,%s,%s,%s) RETURNING *
        """, (cycle_key, chat_id, message_id, poll_id, poll_type, meeting_id))
        row = cur.fetchone()
        if row:
            logger.info("Encuesta guardada: tipo=%s ciclo=%s poll_id=%s db_id=%d", poll_type, cycle_key, poll_id, row["id"])
        return dict(row) if row else None


def get_open_poll(poll_type="books", cycle_key=None, meeting_id=None):
    cycle_key = cycle_key or get_current_cycle_key()
    with get_cursor() as cur:
        if meeting_id is not None:
            cur.execute("""
            SELECT * FROM telegram_polls
            WHERE cycle_key=%s AND poll_type=%s AND meeting_id=%s AND is_closed=FALSE
            ORDER BY created_at DESC LIMIT 1
            """, (cycle_key, poll_type, meeting_id))
        else:
            cur.execute("""
            SELECT * FROM telegram_polls
            WHERE cycle_key=%s AND poll_type=%s AND is_closed=FALSE
            ORDER BY created_at DESC LIMIT 1
            """, (cycle_key, poll_type))
        row = cur.fetchone()
        return dict(row) if row else None


def get_open_polls(poll_type="books", cycle_key=None):
    """Devuelve TODAS las encuestas abiertas de un tipo para un ciclo."""
    cycle_key = cycle_key or get_current_cycle_key()
    with get_cursor() as cur:
        cur.execute("""
        SELECT * FROM telegram_polls
        WHERE cycle_key=%s AND poll_type=%s AND is_closed=FALSE
        ORDER BY created_at ASC
        """, (cycle_key, poll_type))
        return [dict(r) for r in cur.fetchall()]


def get_all_polls_for_cycle(poll_type="books", cycle_key=None):
    """Devuelve TODAS las encuestas (abiertas y cerradas) de un tipo para un ciclo."""
    cycle_key = cycle_key or get_current_cycle_key()
    with get_cursor() as cur:
        cur.execute("""
        SELECT * FROM telegram_polls
        WHERE cycle_key=%s AND poll_type=%s
        ORDER BY created_at ASC
        """, (cycle_key, poll_type))
        return [dict(r) for r in cur.fetchall()]


def get_poll_by_id(poll_db_id):
    with get_cursor() as cur:
        cur.execute("SELECT * FROM telegram_polls WHERE id=%s", (poll_db_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def close_poll(poll_db_id):
    logger.info("Encuesta cerrada: db_id=%d", poll_db_id)
    with get_cursor(commit=True) as cur:
        cur.execute("UPDATE telegram_polls SET is_closed=TRUE WHERE id=%s", (poll_db_id,))


def get_poll_by_telegram_id(telegram_poll_id):
    """Find a poll by its Telegram poll_id string."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM telegram_polls WHERE poll_id=%s ORDER BY created_at DESC LIMIT 1",
            (telegram_poll_id,)
        )
        row = cur.fetchone()
        return dict(row) if row else None


def remove_book_vote(proposal_id, user_name):
    """Remove a specific user's vote for a book."""
    with get_cursor(commit=True) as cur:
        cur.execute(
            "DELETE FROM book_votes WHERE proposal_id=%s AND user_name=%s",
            (proposal_id, user_name)
        )


def remove_theme_vote(theme_id, user_name):
    """Remove a specific user's vote for a theme."""
    with get_cursor(commit=True) as cur:
        cur.execute(
            "DELETE FROM theme_votes WHERE theme_id=%s AND user_name=%s",
            (theme_id, user_name)
        )


# =========================================================
# THEMES MANAGEMENT (admin)
# =========================================================

def delete_theme(theme_id):
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM themes WHERE id = %s", (theme_id,))


def update_theme(theme_id, name):
    with get_cursor(commit=True) as cur:
        cur.execute("UPDATE themes SET name = %s WHERE id = %s", (name.strip(), theme_id))


# =========================================================
# HISTORICAL DATA (all cycles)
# =========================================================

def get_all_books_history():
    """All book proposals across all cycles, newest first."""
    with get_cursor() as cur:
        cur.execute("""
        SELECT bp.id AS proposal_id, bp.cycle_key, b.id AS book_id,
               b.title, b.author, b.cover, b.pages, bp.proposed_by,
               COUNT(bv.id)::int AS votes
        FROM book_proposals bp
        JOIN books b ON b.id = bp.book_id
        LEFT JOIN book_votes bv ON bv.proposal_id = bp.id
        GROUP BY bp.id, bp.cycle_key, b.id, b.title, b.author, b.cover, b.pages, bp.proposed_by
        ORDER BY bp.cycle_key DESC, votes DESC
        """)
        return [dict(r) for r in cur.fetchall()]


def get_all_themes_history():
    """All themes across all cycles."""
    with get_cursor() as cur:
        cur.execute("""
        SELECT t.id, t.name, t.cycle_key, t.created_by, t.is_active,
               COUNT(tv.id)::int AS votes
        FROM themes t
        LEFT JOIN theme_votes tv ON tv.theme_id = t.id
        GROUP BY t.id, t.name, t.cycle_key, t.created_by, t.is_active
        ORDER BY t.cycle_key DESC, votes DESC
        """)
        return [dict(r) for r in cur.fetchall()]


def get_all_polls_history():
    """All Telegram polls across all cycles."""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM telegram_polls ORDER BY created_at DESC")
        return [dict(r) for r in cur.fetchall()]


def get_all_meetings_history():
    """All meetings with attendee count."""
    with get_cursor() as cur:
        cur.execute("""
        SELECT m.*, b.title AS book_title,
               (SELECT COUNT(*)::int FROM meeting_attendance ma WHERE ma.meeting_id = m.id) AS attendee_count
        FROM meetings m
        LEFT JOIN books b ON b.id = m.book_id
        ORDER BY COALESCE(m.final_date, m.created_at) DESC
        """)
        return [dict(r) for r in cur.fetchall()]


# =========================================================
# CONFIG & CYCLE MANAGEMENT
# =========================================================

def get_active_cycle_keys():
    """Lista de ciclos actualmente abiertos (no cerrados)."""
    raw = get_config("active_cycles") or ""
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        # Backward compat: si la lista nueva no existe, usar el key individual
        ck = get_config("active_cycle_key")
        if ck:
            keys = [ck]
    return keys


def add_active_cycle(key):
    keys = get_active_cycle_keys()
    if key not in keys:
        keys.insert(0, key)
    keys = _dedupe_text_values(keys)
    set_config("active_cycles", ",".join(keys))
    set_config("active_cycle_key", keys[0])  # el más reciente como primario


def remove_active_cycle(key):
    keys = [k for k in get_active_cycle_keys() if k != key]
    set_config("active_cycles", ",".join(keys))
    set_config("active_cycle_key", keys[0] if keys else "")


def cycle_exists(cycle_key):
    cycle_key = (cycle_key or "").strip()
    if not cycle_key:
        return False
    return cycle_key in set(get_all_cycle_keys()) or cycle_key in set(get_active_cycle_keys())


def rename_cycle_key(old_key, new_key):
    old_key = (old_key or "").strip()
    new_key = (new_key or "").strip()
    if not old_key or not new_key:
        raise ValueError("Nombre de ciclo inválido")
    if old_key == new_key:
        return {}

    active_cycles = [new_key if key == old_key else key for key in get_active_cycle_keys()]
    locked_cycles = [new_key if key == old_key else key for key in get_locked_cycle_keys()]
    current_cycle = get_config("active_cycle_key")
    current_theme_value = get_config(f"active_theme:{old_key}")
    summary = {}

    with get_cursor(commit=True) as cur:
        for table_name in ("book_proposals", "themes", "meetings", "telegram_polls", "book_waitlist"):
            cur.execute(f"UPDATE {table_name} SET cycle_key=%s WHERE cycle_key=%s", (new_key, old_key))
            summary[table_name] = cur.rowcount

        if current_theme_value is not None:
            cur.execute("""
            INSERT INTO app_config(key, value) VALUES(%s,%s)
            ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()
            """, (f"active_theme:{new_key}", current_theme_value))
            cur.execute("DELETE FROM app_config WHERE key=%s", (f"active_theme:{old_key}",))
            summary["active_theme_config"] = 1

    set_config("active_cycles", ",".join(_dedupe_text_values(active_cycles)))
    if current_cycle == old_key:
        set_config("active_cycle_key", new_key)
    set_locked_cycle_keys(locked_cycles)

    logger.info(
        "Ciclo renombrado: %s -> %s (propuestas=%d, temas=%d, reuniones=%d, encuestas=%d, waitlist=%d)",
        old_key,
        new_key,
        summary.get("book_proposals", 0),
        summary.get("themes", 0),
        summary.get("meetings", 0),
        summary.get("telegram_polls", 0),
        summary.get("book_waitlist", 0),
    )
    return summary


def get_cycle_state(cycle_key):
    """Estado completo de un ciclo para la página de gestión."""
    books = get_books(cycle_key)
    themes = get_themes(cycle_key)
    winner = get_winner_book(cycle_key)

    proposals_locked_for = get_config("proposals_locked_for") or ""
    locked_cycles = {c.strip() for c in proposals_locked_for.split(",") if c.strip()}
    is_locked = cycle_key in locked_cycles

    active_theme = get_config(f"active_theme:{cycle_key}") or ""

    open_theme_poll = get_open_poll("themes", cycle_key=cycle_key)
    open_book_polls = get_open_polls("books", cycle_key=cycle_key)
    open_book_poll = open_book_polls[0] if open_book_polls else None  # for compat
    # winner only counts once voting is done (at least 1 vote cast)
    winner = winner if (winner and winner.get("votes", 0) > 0) else None

    with get_cursor() as cur:
        cur.execute("""
        SELECT m.*, b.title AS book_title FROM meetings m
        LEFT JOIN books b ON b.id = m.book_id
        WHERE m.cycle_key = %s
        ORDER BY COALESCE(m.final_date, m.created_at) DESC LIMIT 1
        """, (cycle_key,))
        row = cur.fetchone()
        meeting = dict(row) if row else None

    # Infer phase from DB state
    if winner:
        phase = "reading" if (meeting and meeting.get("final_date")) else "date_voting"
    elif is_locked or open_book_poll:
        phase = "book_voting"
    elif books:
        phase = "books"
    elif active_theme:
        # Theme already chosen → accept proposals
        phase = "books"
    elif open_theme_poll:
        phase = "theme_voting"
    elif themes:
        phase = "theme_voting"
    else:
        phase = "setup"

    return {
        "cycle_key": cycle_key,
        "books": books,
        "themes": themes,
        "winner": winner,
        "is_locked": is_locked,
        "active_theme": active_theme,
        "phase": phase,
        "open_theme_poll": open_theme_poll,
        "open_book_polls": open_book_polls,
        "open_book_poll": open_book_poll,  # compat: primera o None
        "meeting": meeting,
    }


def close_cycle(cycle_key=None):
    cycle_key = cycle_key or get_current_cycle_key()
    logger.info("Cerrando ciclo: %s", cycle_key)
    with get_cursor(commit=True) as cur:
        cur.execute("UPDATE book_proposals SET is_active=FALSE WHERE cycle_key=%s", (cycle_key,))
        cur.execute("UPDATE themes SET is_active=FALSE WHERE cycle_key=%s", (cycle_key,))
        # Cancel meetings from this cycle that haven't happened yet
        cur.execute("""
            UPDATE meetings SET status='cancelled'
            WHERE cycle_key=%s AND status IN ('scheduled','draft')
              AND (final_date IS NULL OR final_date > NOW())
        """, (cycle_key,))
    remove_active_cycle(cycle_key)
    logger.info("Ciclo cerrado: %s", cycle_key)


def get_all_cycle_keys():
    with get_cursor() as cur:
        cur.execute("""
        SELECT DISTINCT cycle_key FROM (
            SELECT cycle_key FROM book_proposals
            UNION SELECT cycle_key FROM themes
            UNION SELECT cycle_key FROM meetings
        ) t ORDER BY cycle_key DESC
        """)
        return [r["cycle_key"] for r in cur.fetchall()]


# =========================================================
# READING PROGRESS
# =========================================================

def log_reading_progress(user_name, book_id, pages_read):
    with get_cursor(commit=True) as cur:
        cur.execute("""
        INSERT INTO reading_progress(user_name, book_id, pages_read, updated_at)
        VALUES(%s,%s,%s,NOW())
        ON CONFLICT(user_name, book_id) DO UPDATE
            SET pages_read=EXCLUDED.pages_read, updated_at=NOW()
        RETURNING *
        """, (user_name, book_id, pages_read))
        row = cur.fetchone()
        return dict(row) if row else None

def get_reading_progress(book_id):
    with get_cursor() as cur:
        cur.execute("""
        SELECT user_name, pages_read, updated_at
        FROM reading_progress WHERE book_id=%s
        ORDER BY pages_read DESC
        """, (book_id,))
        return [dict(r) for r in cur.fetchall()]


# =========================================================
# MESSAGE TEMPLATES
# =========================================================

def get_message_template(key):
    """Obtiene plantilla personalizada de la BD. Devuelve None si no existe."""
    try:
        with get_cursor() as cur:
            cur.execute("SELECT value FROM message_templates WHERE key = %s", (key,))
            row = cur.fetchone()
            return row["value"] if row else None
    except Exception:
        return None

def set_message_template(key, value):
    with get_cursor(commit=True) as cur:
        cur.execute("""
        INSERT INTO message_templates(key, value) VALUES(%s,%s)
        ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()
        """, (key, str(value)))

def delete_message_template(key):
    """Elimina plantilla personalizada (vuelve al valor por defecto)."""
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM message_templates WHERE key = %s", (key,))

def get_all_message_templates():
    with get_cursor() as cur:
        cur.execute("SELECT key, value, updated_at FROM message_templates ORDER BY key ASC")
        return [dict(r) for r in cur.fetchall()]


# =========================================================
# SENT MESSAGES LOG
# =========================================================

def log_sent_message(message_type, chat_id, text, message_id=None):
    with get_cursor(commit=True) as cur:
        cur.execute("""
        INSERT INTO sent_messages(message_type, chat_id, message_id, text)
        VALUES(%s,%s,%s,%s)
        """, (message_type, int(chat_id), message_id, text[:2000]))

def get_sent_messages(limit=50):
    with get_cursor() as cur:
        cur.execute("SELECT * FROM sent_messages ORDER BY sent_at DESC LIMIT %s", (limit,))
        return [dict(r) for r in cur.fetchall()]


# =========================================================
# SCHEDULED MESSAGES
# =========================================================

def schedule_message(text, send_at):
    with get_cursor(commit=True) as cur:
        cur.execute("""
        INSERT INTO scheduled_messages(text, send_at) VALUES(%s,%s) RETURNING *
        """, (text, send_at))
        return dict(cur.fetchone())

def get_pending_scheduled_messages():
    with get_cursor() as cur:
        cur.execute("""
        SELECT * FROM scheduled_messages
        WHERE sent = FALSE AND send_at <= NOW() AT TIME ZONE 'Europe/Madrid'
        ORDER BY send_at ASC
        """)
        return [dict(r) for r in cur.fetchall()]

def get_all_scheduled_messages():
    with get_cursor() as cur:
        cur.execute("SELECT * FROM scheduled_messages ORDER BY send_at DESC LIMIT 50")
        return [dict(r) for r in cur.fetchall()]

def mark_scheduled_message_sent(msg_id):
    with get_cursor(commit=True) as cur:
        cur.execute("UPDATE scheduled_messages SET sent=TRUE WHERE id=%s", (msg_id,))

def delete_scheduled_message(msg_id):
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM scheduled_messages WHERE id=%s", (msg_id,))


# =========================================================
# UPCOMING MEETINGS
# =========================================================

def get_upcoming_meetings(limit=5, cycle_key=None):
    """Devuelve reuniones activas (draft/scheduled) con fecha futura o sin fecha, ordenadas por fecha ascendente."""
    with get_cursor() as cur:
        params = []
        cycle_sql = ""
        if cycle_key:
            cycle_sql = " AND m.cycle_key = %s"
            params.append(cycle_key)
        params.append(limit)
        cur.execute("""
        SELECT m.*, b.title AS book_title
        FROM meetings m
        LEFT JOIN books b ON b.id = m.book_id
        WHERE m.status IN ('draft', 'scheduled')
        """ + cycle_sql + """
          AND (m.final_date IS NULL OR m.final_date > NOW())
        ORDER BY m.final_date ASC NULLS LAST, m.created_at ASC
        LIMIT %s
        """, tuple(params))
        return [dict(r) for r in cur.fetchall()]


def get_cycle_dashboard_state(cycle=None, _proposals_locked_for=None):
    """Detecta en qué paso del ciclo estamos para el wizard del dashboard."""
    if cycle is None:
        cycle = get_current_cycle_key()
    locked_source = _proposals_locked_for if _proposals_locked_for is not None else ",".join(get_locked_cycle_keys())
    _locked_set = {x.strip() for x in (locked_source or "").split(",") if x.strip()}
    proposals_locked = cycle in _locked_set
    books = get_book_proposals(cycle)
    open_book_poll = get_open_poll(poll_type="books", cycle_key=cycle)
    winner = get_winner_book(cycle)
    themes = get_themes(cycle)
    active_theme = get_config(f"active_theme:{cycle}") or ""
    open_theme_poll = get_open_poll(poll_type="themes", cycle_key=cycle)
    next_meeting = get_latest_scheduled_meeting(cycle_key=cycle)
    open_dates_poll = None
    if next_meeting:
        open_dates_poll = get_open_poll(poll_type="dates", cycle_key=cycle, meeting_id=next_meeting["id"])

    if open_theme_poll:
        step = "poll_open"
        step_label = "Encuesta de temáticas abierta"
        step_desc = "La encuesta de temáticas está activa en Telegram. Ciérrala cuando haya suficientes votos."
        step_action = "Cerrar encuesta de temáticas"
        step_url = f"/admin/encuesta/temas/{open_theme_poll['id']}/cerrar"
        step_color = "danger"
    elif themes and not active_theme and not winner and not books:
        enough_themes = len(themes) >= 2
        step = "collecting_proposals"
        step_label = "Temáticas listas para votar" if enough_themes else "Faltan temáticas"
        step_desc = (
            f"Hay {len(themes)} temática(s) preparadas. Lanza la encuesta para elegir la del ciclo."
            if enough_themes
            else f"Solo hay {len(themes)} temática(s). Añade al menos 2 antes de votar."
        )
        step_action = "Lanzar encuesta de temáticas" if enough_themes else "Añadir más temáticas"
        step_url = "/admin/encuesta/temas/crear" if enough_themes else "#themes"
        step_color = "warning"
    elif not themes and not books and not proposals_locked and not winner:
        step = "new_cycle"
        step_label = "Nuevo ciclo"
        step_desc = "Crea el ciclo, define temáticas y prepara la primera votación."
        step_action = "Crear ciclo"
        step_url = "/admin/wizard/new-cycle"
        step_color = "primary"
    elif books and not proposals_locked and not open_book_poll and not winner:
        enough_books = len(books) >= 2
        step = "collecting_proposals"
        step_label = "Recogiendo propuestas"
        step_desc = (
            f"Hay {len(books)} propuesta(s). Cuando estés listo, cierra las propuestas y lanza la encuesta."
            if enough_books
            else f"Hay {len(books)} propuesta(s). Necesitas al menos 2 para abrir la votación."
        )
        step_action = "Cerrar propuestas y lanzar encuesta" if enough_books else "Añadir más propuestas"
        step_url = "/admin/wizard/lock-and-poll" if enough_books else "#books"
        step_color = "warning"
    elif open_book_poll:
        step = "poll_open"
        step_label = "Encuesta de libros abierta"
        step_desc = "La encuesta está activa en Telegram. Ciérrala cuando haya suficientes votos."
        step_action = f"Cerrar encuesta y anunciar ganador"
        step_url = f"/admin/encuesta/{open_book_poll['id']}/cerrar"
        step_color = "danger"
    elif winner and open_dates_poll:
        step = "dates_poll_open"
        step_label = "Encuesta de fechas activa"
        step_desc = "La encuesta de fechas está activa en Telegram."
        step_action = "Cerrar encuesta de fechas"
        step_url = f"/admin/encuesta/fechas/{next_meeting['id']}/cerrar/{open_dates_poll['id']}"
        step_color = "danger"
    elif winner and (not next_meeting or not next_meeting.get("final_date")):
        step = "awaiting_date"
        step_label = "Esperando fecha de reunión"
        step_desc = f"Libro: «{winner['title']}». Elige una fecha o lanza una encuesta de fechas."
        step_action = "Gestionar fecha de reunión"
        step_url = f"/meeting/{next_meeting['id']}" if next_meeting else "/meetings"
        step_color = "warning"
    elif winner and next_meeting and next_meeting.get("final_date"):
        step = "meeting_scheduled"
        step_label = "Reunión programada"
        step_desc = f"Reunión: {next_meeting['name']} — {str(next_meeting['final_date'])[:16]}"
        step_action = "Anunciar fecha al grupo"
        step_url = "/admin/wizard/announce-date"
        step_color = "success"
    else:
        step = "collecting_proposals"
        step_label = "Recogiendo propuestas"
        step_desc = "Añade propuestas de libros para este ciclo."
        step_action = "Gestionar propuestas"
        step_url = "#books"
        step_color = "primary"

    return {
        "cycle": cycle,
        "step": step,
        "step_label": step_label,
        "step_desc": step_desc,
        "step_action": step_action,
        "step_url": step_url,
        "step_color": step_color,
        "books_count": len(books),
        "proposals_locked": proposals_locked,
        "winner": winner,
        "next_meeting": next_meeting,
    }


def get_active_cycle_states():
    """Devuelve el estado del wizard solo para ciclos realmente activos (no cerrados)."""
    active_cycle_keys = get_active_cycle_keys()  # source of truth: active_cycles config
    if not active_cycle_keys:
        return []

    with get_cursor() as cur:
        cur.execute("SELECT value FROM app_config WHERE key='proposals_locked_for'")
        row = cur.fetchone()
    locked_for = (row["value"] if row else "") or ""
    default_cycle = active_cycle_keys[0]

    states = []
    for ck in active_cycle_keys:
        state = get_cycle_dashboard_state(cycle=ck, _proposals_locked_for=locked_for)
        state["is_default"] = (ck == default_cycle)
        states.append(state)
    return states


# =========================================================
# USER STATS
# =========================================================

def get_user_stats(user_name):
    stats = {}
    cycle = get_current_cycle_key()
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*)::int AS n FROM book_proposals WHERE proposed_by=%s", (user_name,))
        stats["proposals_total"] = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*)::int AS n FROM book_proposals WHERE proposed_by=%s AND cycle_key=%s", (user_name, cycle))
        stats["proposals_cycle"] = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*)::int AS n FROM book_votes WHERE user_name=%s", (user_name,))
        stats["book_votes"] = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*)::int AS n FROM theme_votes WHERE user_name=%s", (user_name,))
        stats["theme_votes"] = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*)::int AS n FROM meeting_attendance WHERE user_name=%s", (user_name,))
        stats["meetings"] = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*)::int AS n, ROUND(AVG(score)::numeric,1) AS avg FROM book_ratings WHERE user_name=%s", (user_name,))
        row = cur.fetchone()
        stats["ratings"] = row["n"]
        stats["avg_score"] = float(row["avg"]) if row["avg"] else None
        cur.execute("""
        SELECT rp.pages_read, b.pages AS total, b.title
        FROM reading_progress rp JOIN books b ON b.id=rp.book_id
        WHERE rp.user_name=%s ORDER BY rp.updated_at DESC LIMIT 1
        """, (user_name,))
        row = cur.fetchone()
        stats["last_progress"] = dict(row) if row else None
    return stats


# =========================================================
# BOOK MANAGEMENT (admin edit)
# =========================================================

def update_book(book_id, title=None, author=None, description=None, pages=None, cover=None):
    fields, values = [], []
    if title is not None:       fields.append("title=%s");       values.append(title)
    if author is not None:      fields.append("author=%s");      values.append(author or None)
    if description is not None: fields.append("description=%s"); values.append(description or None)
    if pages is not None:       fields.append("pages=%s");       values.append(int(pages) if pages else None)
    if cover is not None:       fields.append("cover=%s");       values.append(cover or None)
    if not fields:
        return
    values.append(book_id)
    with get_cursor(commit=True) as cur:
        cur.execute(f"UPDATE books SET {', '.join(fields)} WHERE id=%s", tuple(values))


# =========================================================
# DB VIEWER (admin — whitelisted tables only)
# =========================================================

ALLOWED_TABLES = [
    "books", "book_proposals", "book_votes",
    "themes", "theme_votes",
    "meetings", "meeting_date_options", "meeting_date_votes",
    "meeting_attendance", "book_ratings", "telegram_polls",
    "app_config", "reading_progress", "message_templates", "sent_messages", "scheduled_messages",
    "book_waitlist", "club_members", "app_events", "bug_reports",
]


def get_table_names():
    return list(ALLOWED_TABLES)


def get_table_primary_key(table_name):
    if table_name not in ALLOWED_TABLES:
        raise ValueError(f"Tabla no permitida: {table_name}")
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            WHERE tc.table_schema = 'public'
              AND tc.table_name = %s
              AND tc.constraint_type = 'PRIMARY KEY'
            ORDER BY kcu.ordinal_position
            """,
            (table_name,),
        )
        rows = [row["column_name"] for row in cur.fetchall()]
        if rows:
            return rows[0]

        cur.execute(
            """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            WHERE tc.table_schema = 'public'
              AND tc.table_name = %s
              AND tc.constraint_type = 'UNIQUE'
            GROUP BY tc.constraint_name, kcu.column_name
            HAVING COUNT(*) = 1
            ORDER BY MIN(kcu.ordinal_position)
            LIMIT 1
            """,
            (table_name,),
        )
        row = cur.fetchone()
        return row["column_name"] if row else None


def get_table_rows(table_name, limit=200):
    if table_name not in ALLOWED_TABLES:
        raise ValueError(f"Tabla no permitida: {table_name}")
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            """,
            (table_name,),
        )
        column_names = {row["column_name"] for row in cur.fetchall()}
        order_column = None
        for candidate in ("id", "created_at", "updated_at", "key", "user_id"):
            if candidate in column_names:
                order_column = candidate
                break
        primary_key = get_table_primary_key(table_name)

        query = f"SELECT * FROM {table_name}"
        if order_column:
            query += f" ORDER BY {order_column} DESC"
        query += " LIMIT %s"

        cur.execute(query, (limit,))
        rows = [dict(row) for row in cur.fetchall()]
        if not rows:
            return [], [], primary_key
        cols = list(rows[0].keys())
        return cols, rows, primary_key


def delete_table_row(table_name, pk_column, pk_value):
    if table_name not in ALLOWED_TABLES:
        raise ValueError(f"Tabla no permitida: {table_name}")
    real_pk = get_table_primary_key(table_name)
    if not real_pk:
        raise ValueError(f"La tabla {table_name} no tiene una clave utilizable para borrar filas")
    if pk_column != real_pk:
        raise ValueError(f"Clave inválida para {table_name}: {pk_column}")
    with get_cursor(commit=True) as cur:
        cur.execute(f"DELETE FROM {table_name} WHERE {real_pk} = %s", (pk_value,))
        return cur.rowcount


def truncate_table(table_name):
    if table_name not in ALLOWED_TABLES:
        raise ValueError(f"Tabla no permitida: {table_name}")
    with get_cursor(commit=True) as cur:
        cur.execute(f"TRUNCATE TABLE {table_name} CASCADE")


# =========================================================
# BOOK WAITLIST
# =========================================================

def add_to_waitlist(book_id, cycle_key, cycle_theme=None, position=None, votes=None, added_by='auto', notes=None):
    """Add a book to the waiting list."""
    with get_cursor(commit=True) as cur:
        cur.execute("""
        INSERT INTO book_waitlist(book_id, cycle_key, cycle_theme, position_at_time, votes_at_time, added_by, notes)
        VALUES(%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT(book_id, cycle_key) DO UPDATE SET notes=EXCLUDED.notes, added_by=EXCLUDED.added_by
        RETURNING *
        """, (book_id, cycle_key, cycle_theme, position, votes, added_by, notes))
        return dict(cur.fetchone())


def get_waitlist(theme=None):
    """Get waitlist books, optionally filtered by theme. Returns books with book info."""
    with get_cursor() as cur:
        if theme:
            cur.execute("""
            SELECT wl.*, b.title, b.author, b.description, b.cover, b.pages, b.language_code
            FROM book_waitlist wl JOIN books b ON b.id = wl.book_id
            WHERE LOWER(wl.cycle_theme) = LOWER(%s)
            ORDER BY wl.position_at_time ASC NULLS LAST, wl.votes_at_time DESC NULLS LAST, wl.added_at DESC
            """, (theme,))
        else:
            cur.execute("""
            SELECT wl.*, b.title, b.author, b.description, b.cover, b.pages, b.language_code
            FROM book_waitlist wl JOIN books b ON b.id = wl.book_id
            ORDER BY wl.cycle_theme NULLS LAST, wl.position_at_time ASC NULLS LAST, wl.votes_at_time DESC NULLS LAST
            """)
        return [dict(r) for r in cur.fetchall()]


def remove_from_waitlist(waitlist_id):
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM book_waitlist WHERE id = %s", (waitlist_id,))


def get_waitlist_themes():
    """Get distinct themes from waitlist."""
    with get_cursor() as cur:
        cur.execute("SELECT DISTINCT cycle_theme FROM book_waitlist WHERE cycle_theme IS NOT NULL ORDER BY cycle_theme")
        return [r['cycle_theme'] for r in cur.fetchall()]


def auto_add_runners_up_to_waitlist(cycle_key, cycle_theme=None):
    """After a cycle ends, add 2nd, 3rd place (runners-up) to waitlist automatically."""
    books = get_books(cycle_key)
    added = []
    for i, book in enumerate(books[1:4], start=2):  # positions 2, 3, 4
        try:
            add_to_waitlist(
                book_id=book['id'],
                cycle_key=cycle_key,
                cycle_theme=cycle_theme,
                position=i,
                votes=book.get('votes', 0),
                added_by='auto'
            )
            added.append(book)
        except Exception:
            pass
    return added


def propose_meeting_date(meeting_id, proposed_date, proposed_by):
    """User proposes a date option for a meeting."""
    with get_cursor(commit=True) as cur:
        cur.execute("""
        INSERT INTO meeting_date_options(meeting_id, option_date, created_at)
        VALUES(%s,%s,NOW())
        ON CONFLICT(meeting_id, option_date) DO NOTHING
        RETURNING *
        """, (meeting_id, proposed_date))
        row = cur.fetchone()
        return dict(row) if row else None


# =========================================================
# CLUB MEMBERS
# =========================================================

def save_member(user_id: int, first_name: str = None, username: str = None):
    """Guarda o actualiza un miembro del club cuando interactúa con el bot."""
    with get_cursor(commit=True) as cur:
        cur.execute("""
        INSERT INTO club_members (user_id, first_name, username, last_seen)
        VALUES (%s, %s, %s, NOW())
        ON CONFLICT (user_id) DO UPDATE SET
            first_name = EXCLUDED.first_name,
            username = EXCLUDED.username,
            last_seen = NOW()
        """, (user_id, first_name, username))

def get_all_members():
    """Devuelve todos los miembros registrados."""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM club_members ORDER BY last_seen DESC")
        return [dict(r) for r in cur.fetchall()]

def get_galeria_data(limit: int = None):
    """Devuelve reuniones cerradas con su libro, portada, asistentes y notas, ordenadas por fecha desc."""
    with get_cursor() as cur:
        sql = """
        SELECT
            m.id, m.name, m.cycle_key, m.final_date, m.summary, m.notes, m.location,
            b.id AS book_id, b.title AS book_title, b.author AS book_author,
            b.cover AS book_cover, b.pages AS book_pages, b.description AS book_description,
            COUNT(ma.id)::int AS attendee_count,
            ARRAY_AGG(ma.user_name ORDER BY ma.created_at)
                FILTER (WHERE ma.user_name IS NOT NULL) AS attendees
        FROM meetings m
        LEFT JOIN books b ON b.id = m.book_id
        LEFT JOIN meeting_attendance ma ON ma.meeting_id = m.id
        WHERE m.status = 'closed'
        GROUP BY m.id, b.id
        ORDER BY COALESCE(m.final_date, m.created_at) DESC
        """
        if limit:
            sql += f" LIMIT {int(limit)}"
        cur.execute(sql)
        rows = []
        for r in cur.fetchall():
            row = dict(r)
            if row.get('attendees') is None:
                row['attendees'] = []
            rows.append(row)
        return rows


# =========================================================
# EVENT LOG
# =========================================================

def log_event(event_type: str, description: str, category: str = None, actor: str = None, extra: dict = None):
    """Registra un evento en app_events. Nunca lanza excepción."""
    logger.info("EVENT [%s/%s] actor=%s — %s", event_type, category or "-", actor or "-", description)
    try:
        with get_cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO app_events (event_type, category, description, actor, extra) VALUES (%s,%s,%s,%s,%s)",
                (event_type, category, description, actor,
                 json.dumps(extra, ensure_ascii=False) if extra else None)
            )
    except Exception as e:
        logger.warning("log_event DB write failed: %s", e)


def get_events(limit: int = 300, event_type: str = None, category: str = None):
    with get_cursor() as cur:
        conds, params = [], []
        if event_type:
            conds.append("event_type = %s"); params.append(event_type)
        if category:
            conds.append("category = %s"); params.append(category)
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        params.append(limit)
        cur.execute(f"SELECT * FROM app_events {where} ORDER BY created_at DESC LIMIT %s", params)
        return [dict(r) for r in cur.fetchall()]


# =========================================================
# BUG REPORTS
# =========================================================

def create_bug_report(user_id: int, username: str, description: str) -> int:
    with get_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO bug_reports (user_id, username, description) VALUES (%s,%s,%s) RETURNING id",
            (user_id, username, description)
        )
        return cur.fetchone()["id"]


def get_bug_reports(status: str = None):
    with get_cursor() as cur:
        if status:
            cur.execute("SELECT * FROM bug_reports WHERE status = %s ORDER BY created_at DESC", (status,))
        else:
            cur.execute("SELECT * FROM bug_reports ORDER BY created_at DESC")
        return [dict(r) for r in cur.fetchall()]


def update_bug_report(report_id: int, status: str, admin_notes: str = None):
    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE bug_reports SET status=%s, admin_notes=%s, updated_at=NOW() WHERE id=%s",
            (status, admin_notes, report_id)
        )
