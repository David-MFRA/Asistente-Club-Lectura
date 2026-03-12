import os
from contextlib import contextmanager
from datetime import datetime

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
        # Migrar columna poll_type si la tabla ya existía sin ella
        cur.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='telegram_polls' AND column_name='poll_type'
            ) THEN
                ALTER TABLE telegram_polls ADD COLUMN poll_type TEXT NOT NULL DEFAULT 'books';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='telegram_polls' AND column_name='meeting_id'
            ) THEN
                ALTER TABLE telegram_polls ADD COLUMN meeting_id INTEGER REFERENCES meetings(id) ON DELETE SET NULL;
            END IF;
        END$$;
        """)


# =========================================================
# HELPERS
# =========================================================

def current_cycle_key(dt=None):
    dt = dt or datetime.utcnow()
    return dt.strftime("%Y-%m")

def get_current_cycle_key():
    return current_cycle_key()


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
    cycle_key = cycle_key or current_cycle_key()
    book_row  = create_or_get_book(book)
    with get_cursor(commit=True) as cur:
        cur.execute("""
        INSERT INTO book_proposals(book_id, proposed_by, cycle_key)
        VALUES(%s,%s,%s)
        ON CONFLICT (book_id, cycle_key) DO UPDATE SET proposed_by = EXCLUDED.proposed_by
        RETURNING *
        """, (book_row["id"], proposed_by, cycle_key))
        return dict(cur.fetchone())


def remove_book_proposal(proposal_id):
    """Elimina una propuesta del ciclo (el admin puede quitarla)."""
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM book_proposals WHERE id = %s", (proposal_id,))


def get_books(cycle_key=None):
    cycle_key = cycle_key or current_cycle_key()
    with get_cursor() as cur:
        cur.execute("""
        SELECT
            bp.id AS proposal_id, b.id, b.title, b.author,
            b.description, b.cover, b.pages, bp.proposed_by,
            COUNT(bv.id)::int AS votes
        FROM book_proposals bp
        JOIN books b ON b.id = bp.book_id
        LEFT JOIN book_votes bv ON bv.proposal_id = bp.id
        WHERE bp.cycle_key = %s AND bp.is_active = TRUE
        GROUP BY bp.id, b.id, b.title, b.author, b.description, b.cover, b.pages, bp.proposed_by
        ORDER BY votes DESC, b.title ASC
        """, (cycle_key,))
        return [dict(r) for r in cur.fetchall()]


def get_book_proposals(cycle_key=None):
    return get_books(cycle_key)


def get_proposal_by_id(proposal_id):
    with get_cursor() as cur:
        cur.execute("""
        SELECT bp.id AS proposal_id, b.id, b.title, b.author, b.description, b.cover, b.pages,
               bp.proposed_by, COUNT(bv.id)::int AS votes
        FROM book_proposals bp
        JOIN books b ON b.id = bp.book_id
        LEFT JOIN book_votes bv ON bv.proposal_id = bp.id
        WHERE bp.id = %s
        GROUP BY bp.id, b.id, b.title, b.author, b.description, b.cover, b.pages, bp.proposed_by
        """, (proposal_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def vote_book(proposal_id, user_name):
    with get_cursor(commit=True) as cur:
        cur.execute("""
        INSERT INTO book_votes(proposal_id, user_name)
        VALUES(%s,%s) ON CONFLICT (proposal_id, user_name) DO NOTHING RETURNING id
        """, (proposal_id, user_name))
        return cur.fetchone() is not None


def get_cycle_results(cycle_key=None):
    return get_books(cycle_key)


def close_cycle_proposals(cycle_key=None):
    cycle_key = cycle_key or current_cycle_key()
    with get_cursor(commit=True) as cur:
        cur.execute("UPDATE book_proposals SET is_active = FALSE WHERE cycle_key = %s", (cycle_key,))


def get_winner_book(cycle_key=None):
    books = get_books(cycle_key)
    return books[0] if books else None


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
    cycle_key = cycle_key or current_cycle_key()
    with get_cursor(commit=True) as cur:
        cur.execute("""
        INSERT INTO themes(name, cycle_key, created_by)
        VALUES(%s,%s,%s) ON CONFLICT (name, cycle_key) DO NOTHING RETURNING *
        """, (name.strip(), cycle_key, created_by))
        row = cur.fetchone()
        return dict(row) if row else None


def get_themes(cycle_key=None):
    cycle_key = cycle_key or current_cycle_key()
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


def vote_theme(theme_id, user_name):
    with get_cursor(commit=True) as cur:
        cur.execute("""
        INSERT INTO theme_votes(theme_id, user_name)
        VALUES(%s,%s) ON CONFLICT (theme_id, user_name) DO NOTHING RETURNING id
        """, (theme_id, user_name))
        return cur.fetchone() is not None


def get_top_theme(cycle_key=None):
    themes = get_themes(cycle_key)
    return themes[0] if themes else None


# =========================================================
# MEETINGS
# =========================================================

def create_meeting(name, final_date=None, cycle_key=None, created_by=None, book_id=None, status="draft"):
    cycle_key = cycle_key or current_cycle_key()
    with get_cursor(commit=True) as cur:
        cur.execute("""
        INSERT INTO meetings(name, cycle_key, final_date, created_by, book_id, status)
        VALUES(%s,%s,%s,%s,%s,%s) RETURNING *
        """, (name.strip(), cycle_key, final_date, created_by, book_id, status))
        return dict(cur.fetchone())


def get_meetings(limit=50):
    with get_cursor() as cur:
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


def get_latest_scheduled_meeting():
    with get_cursor() as cur:
        cur.execute("""
        SELECT * FROM meetings
        WHERE status IN ('scheduled', 'draft')
        ORDER BY COALESCE(final_date, created_at) DESC LIMIT 1
        """)
        row = cur.fetchone()
        return dict(row) if row else None


def add_meeting_date_option(meeting_id, option_date):
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
    with get_cursor(commit=True) as cur:
        cur.execute("""
        UPDATE meetings SET final_date=%s, status='scheduled', updated_at=NOW()
        WHERE id=%s
        """, (final_date, meeting_id))


def update_meeting(meeting_id, name=None, final_date=None, summary=None, status=None, book_id=None):
    fields, values = [], []
    if name is not None:       fields.append("name = %s");       values.append(name)
    if final_date is not None: fields.append("final_date = %s"); values.append(final_date)
    if summary is not None:    fields.append("summary = %s");    values.append(summary)
    if status is not None:     fields.append("status = %s");     values.append(status)
    if book_id is not None:    fields.append("book_id = %s");    values.append(book_id)
    if not fields:
        return
    fields.append("updated_at = NOW()")
    values.append(meeting_id)
    with get_cursor(commit=True) as cur:
        cur.execute(f"UPDATE meetings SET {', '.join(fields)} WHERE id = %s", tuple(values))


def delete_meeting(meeting_id):
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM meetings WHERE id = %s", (meeting_id,))


def add_attendance(meeting_id, user_name):
    with get_cursor(commit=True) as cur:
        cur.execute("""
        INSERT INTO meeting_attendance(meeting_id, user_name)
        VALUES(%s,%s) ON CONFLICT (meeting_id, user_name) DO NOTHING RETURNING id
        """, (meeting_id, user_name))
        return cur.fetchone() is not None


def remove_attendance(meeting_id, user_name):
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
    cycle_key = cycle_key or current_cycle_key()
    with get_cursor(commit=True) as cur:
        cur.execute("""
        INSERT INTO telegram_polls(cycle_key, chat_id, message_id, poll_id, poll_type, meeting_id)
        VALUES(%s,%s,%s,%s,%s,%s) RETURNING *
        """, (cycle_key, chat_id, message_id, poll_id, poll_type, meeting_id))
        row = cur.fetchone()
        return dict(row) if row else None


def get_open_poll(poll_type="books", cycle_key=None, meeting_id=None):
    cycle_key = cycle_key or current_cycle_key()
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


def get_poll_by_id(poll_db_id):
    with get_cursor() as cur:
        cur.execute("SELECT * FROM telegram_polls WHERE id=%s", (poll_db_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def close_poll(poll_db_id):
    with get_cursor(commit=True) as cur:
        cur.execute("UPDATE telegram_polls SET is_closed=TRUE WHERE id=%s", (poll_db_id,))


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
# DB VIEWER (admin — whitelisted tables only)
# =========================================================

ALLOWED_TABLES = [
    "books", "book_proposals", "book_votes",
    "themes", "theme_votes",
    "meetings", "meeting_date_options", "meeting_date_votes",
    "meeting_attendance", "book_ratings", "telegram_polls",
]


def get_table_names():
    return list(ALLOWED_TABLES)


def get_table_rows(table_name, limit=200):
    if table_name not in ALLOWED_TABLES:
        raise ValueError(f"Tabla no permitida: {table_name}")
    with get_cursor() as cur:
        cur.execute(f"SELECT * FROM {table_name} ORDER BY id DESC LIMIT %s", (limit,))
        rows = cur.fetchall()
        if not rows:
            return [], []
        cols = list(rows[0].keys())
        return cols, [list(r.values()) for r in rows]


def delete_table_row(table_name, row_id):
    if table_name not in ALLOWED_TABLES:
        raise ValueError(f"Tabla no permitida: {table_name}")
    with get_cursor(commit=True) as cur:
        cur.execute(f"DELETE FROM {table_name} WHERE id = %s", (row_id,))


def truncate_table(table_name):
    if table_name not in ALLOWED_TABLES:
        raise ValueError(f"Tabla no permitida: {table_name}")
    with get_cursor(commit=True) as cur:
        cur.execute(f"TRUNCATE TABLE {table_name} CASCADE")
