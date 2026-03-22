import logging
import os
import json
from contextlib import contextmanager
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, TypedDict

from app.db_migrations import apply_migrations
from app.services.identity_backfill import backfill_historical_user_identity
from app.services.input_limits import (
    normalize_admin_search_query,
    normalize_bug_description,
    normalize_theme_name,
)

logger = logging.getLogger(__name__)


# Tipos ligeros para documentar las formas mas usadas en la capa de persistencia.
# No reemplazan una ORM, pero evitan seguir pasando `dict` anonimos sin contexto.
class PublicPageAccessLogRow(TypedDict):
    id: int
    route: str
    method: str
    ip: str | None
    user_agent: str | None
    referrer: str | None
    query_string: str | None
    created_at: Any


class AdminBlockedIPState(TypedDict, total=False):
    ip: str
    failed_attempts: int
    first_failed_at: Any | None
    last_failed_at: Any | None
    blocked_at: Any | None
    block_reason: str | None
    is_blocked: bool
    just_blocked: bool


def _utcnow():
    """Retorna datetime UTC naive (sin tzinfo) sin deprecation warning."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

import psycopg2
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import Json, RealDictCursor

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Falta DATABASE_URL")

_pool_maxconn = int(os.getenv("DB_POOL_MAXCONN", "15"))
pool = SimpleConnectionPool(minconn=2, maxconn=_pool_maxconn, dsn=DATABASE_URL)


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
        apply_migrations(cur)


# =========================================================
# HELPERS
# =========================================================

def current_cycle_key(dt=None):
    dt = dt or _utcnow()
    return dt.strftime("%Y-%m")


def _coerce_user_id(user_id):
    if user_id in (None, ""):
        return None
    try:
        return int(user_id)
    except (TypeError, ValueError):
        return None


def _normalize_user_identity(user_name=None, user_id=None):
    normalized_user_id = _coerce_user_id(user_id)
    normalized_user_name = (user_name or "").strip()
    if not normalized_user_name and normalized_user_id is not None:
        normalized_user_name = str(normalized_user_id)
    return normalized_user_name or None, normalized_user_id

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


def get_json_config(key, default=None):
    raw = get_config(key)
    if raw in (None, ""):
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def set_json_config(key, value):
    set_config(key, json.dumps(value, ensure_ascii=False))


def ensure_cycle_record(cycle_key, *, is_active=None, active_theme=None, proposals_locked=None):
    cycle_key = (cycle_key or "").strip()
    if not cycle_key:
        return None

    updates = []
    values = [cycle_key]
    if is_active is not None:
        updates.append("is_active = EXCLUDED.is_active")
        values.append(bool(is_active))
    else:
        values.append(True)
    if active_theme is not None:
        updates.append("active_theme = EXCLUDED.active_theme")
        values.append(active_theme or None)
    else:
        values.append(None)
    if proposals_locked is not None:
        updates.append("proposals_locked = EXCLUDED.proposals_locked")
        values.append(bool(proposals_locked))
    else:
        values.append(False)

    with get_cursor(commit=True) as cur:
        if updates:
            updates.append("updated_at = NOW()")
            cur.execute(
                f"""
                INSERT INTO cycles (cycle_key, is_active, active_theme, proposals_locked)
                VALUES (%s,%s,%s,%s)
                ON CONFLICT (cycle_key) DO UPDATE
                SET {', '.join(updates)}
                RETURNING *
                """,
                tuple(values),
            )
        else:
            cur.execute(
                """
                INSERT INTO cycles (cycle_key)
                VALUES (%s)
                ON CONFLICT (cycle_key) DO UPDATE
                SET updated_at = cycles.updated_at
                RETURNING *
                """,
                (cycle_key,),
            )
        return dict(cur.fetchone())


def get_current_cycle_key():
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT cycle_key
            FROM cycles
            WHERE is_active = TRUE
            ORDER BY updated_at DESC, created_at DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
        if row:
            return row["cycle_key"]
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
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT cycle_key
            FROM cycles
            WHERE proposals_locked = TRUE
            ORDER BY updated_at DESC, created_at DESC
            """
        )
        rows = [row["cycle_key"] for row in cur.fetchall()]
    if rows:
        return rows
    raw = get_config("proposals_locked_for") or ""
    return _dedupe_text_values(raw.split(","))


def set_locked_cycle_keys(keys):
    normalized_keys = _dedupe_text_values(keys)
    with get_cursor(commit=True) as cur:
        cur.execute("UPDATE cycles SET proposals_locked = FALSE WHERE proposals_locked = TRUE")
        for cycle_key in normalized_keys:
            cur.execute(
                """
                INSERT INTO cycles (cycle_key, proposals_locked)
                VALUES (%s, TRUE)
                ON CONFLICT (cycle_key) DO UPDATE
                SET proposals_locked = TRUE, updated_at = NOW()
                """,
                (cycle_key,),
            )
    set_config("proposals_locked_for", ",".join(normalized_keys))


def lock_cycle_proposals(cycle_key):
    ensure_cycle_record(cycle_key, proposals_locked=True)
    keys = get_locked_cycle_keys()
    if cycle_key not in keys:
        keys.append(cycle_key)
    set_config("proposals_locked_for", ",".join(_dedupe_text_values(keys)))
    logger.info("Propuestas bloqueadas para ciclo=%s", cycle_key)


def unlock_cycle_proposals(cycle_key=None):
    if not cycle_key:
        with get_cursor(commit=True) as cur:
            cur.execute("UPDATE cycles SET proposals_locked = FALSE WHERE proposals_locked = TRUE")
        set_config("proposals_locked_for", "")
        logger.info("Propuestas desbloqueadas para todos los ciclos")
        return
    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE cycles SET proposals_locked = FALSE, updated_at = NOW() WHERE cycle_key = %s",
            (cycle_key,),
        )
    keys = [key for key in get_locked_cycle_keys() if key != cycle_key]
    set_config("proposals_locked_for", ",".join(_dedupe_text_values(keys)))
    ensure_cycle_record(cycle_key)
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


def insert_book(book, proposed_by="telegram", cycle_key=None, proposed_by_user_id=None, meeting_id=None):
    cycle_key = cycle_key or get_current_cycle_key()
    ensure_cycle_record(cycle_key)
    book_row  = create_or_get_book(book)
    proposed_by_name, proposed_by_user_id = _normalize_user_identity(proposed_by, proposed_by_user_id)
    with get_cursor(commit=True) as cur:
        cur.execute("""
        INSERT INTO book_proposals(book_id, proposed_by, proposed_by_user_id, cycle_key, meeting_id)
        VALUES(%s,%s,%s,%s,%s)
        ON CONFLICT (book_id, cycle_key) DO NOTHING
        RETURNING *
        """, (book_row["id"], proposed_by_name or "telegram", proposed_by_user_id, cycle_key, meeting_id))
        row = cur.fetchone()
        if row:
            logger.info("Libro propuesto: «%s» por %s en ciclo %s meeting_id=%s (book_id=%d, proposal_id=%d)",
                        book_row["title"], proposed_by_name, cycle_key, meeting_id, book_row["id"], row["id"])
            return {"inserted": True, **dict(row)}
        # Already proposed — return existing
        logger.warning("Libro duplicado ignorado: «%s» por %s en ciclo %s (book_id=%d)",
                       book_row["title"], proposed_by_name, cycle_key, book_row["id"])
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


def vote_book(proposal_id, user_name=None, user_id=None):
    user_name, user_id = _normalize_user_identity(user_name, user_id)
    with get_cursor(commit=True) as cur:
        cur.execute("""
        INSERT INTO book_votes(proposal_id, user_name, user_id)
        VALUES(%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id
        """, (proposal_id, user_name, user_id))
        ok = cur.fetchone() is not None
        if ok:
            logger.info("Voto libro registrado: proposal_id=%d, user=%s user_id=%s", proposal_id, user_name, user_id)
        else:
            logger.warning("Voto libro duplicado ignorado: proposal_id=%d, user=%s user_id=%s", proposal_id, user_name, user_id)
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
    name = normalize_theme_name(name)
    ensure_cycle_record(cycle_key)
    with get_cursor(commit=True) as cur:
        cur.execute("""
        INSERT INTO themes(name, cycle_key, created_by)
        VALUES(%s,%s,%s) ON CONFLICT (name, cycle_key) DO NOTHING RETURNING *
        """, (name, cycle_key, created_by))
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


def vote_theme(theme_id, user_name=None, user_id=None):
    user_name, user_id = _normalize_user_identity(user_name, user_id)
    with get_cursor(commit=True) as cur:
        cur.execute("""
        INSERT INTO theme_votes(theme_id, user_name, user_id)
        VALUES(%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id
        """, (theme_id, user_name, user_id))
        ok = cur.fetchone() is not None
        if ok:
            logger.info("Voto temática registrado: theme_id=%d, user=%s user_id=%s", theme_id, user_name, user_id)
        else:
            logger.warning("Voto temática duplicado ignorado: theme_id=%d, user=%s user_id=%s", theme_id, user_name, user_id)
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

def create_meeting(name, final_date=None, cycle_key=None, created_by=None, book_id=None, status="draft", voting_state="none", meeting_time=None, extras=None):
    cycle_key = cycle_key or get_current_cycle_key()
    ensure_cycle_record(cycle_key)
    with get_cursor(commit=True) as cur:
        cur.execute("""
        INSERT INTO meetings(name, cycle_key, final_date, created_by, book_id, status, voting_state, meeting_time, extras)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
        """, (name.strip(), cycle_key, final_date, created_by, book_id, status, voting_state, meeting_time, extras))
        row = cur.fetchone()
        meeting_id = row["id"]
        logger.info("Reunión creada: «%s» (id=%d) en ciclo %s por %s", name, meeting_id, cycle_key, created_by)
        return meeting_id


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


def get_open_voting_meeting():
    """Returns the first meeting with voting_state='open'."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM meetings WHERE voting_state = 'open' ORDER BY created_at DESC LIMIT 1"
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_current_book():
    """Returns the book linked to the nearest upcoming meeting that has a book_id.
    Falls back to get_winner_book() if none found."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT b.*, bp.votes
            FROM meetings m
            JOIN books b ON b.id = m.book_id
            LEFT JOIN (
                SELECT book_id, COUNT(*) as votes FROM book_votes bv
                JOIN book_proposals bp2 ON bp2.id = bv.proposal_id
                GROUP BY book_id
            ) bp ON bp.book_id = b.id
            WHERE m.book_id IS NOT NULL AND m.status != 'closed'
            ORDER BY
                CASE WHEN m.final_date IS NOT NULL THEN 0 ELSE 1 END,
                m.final_date ASC,
                m.created_at ASC
            LIMIT 1
            """
        )
        row = cur.fetchone()
        if row:
            return dict(row)
        return get_winner_book()


def get_upcoming_meetings_list(limit=10):
    """Returns all upcoming non-closed meetings ordered by date."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT m.*, b.title as book_title, b.author as book_author, b.cover as book_cover
            FROM meetings m
            LEFT JOIN books b ON b.id = m.book_id
            WHERE m.status != 'closed'
            ORDER BY
                CASE WHEN m.final_date IS NOT NULL THEN 0 ELSE 1 END,
                m.final_date ASC,
                m.created_at ASC
            LIMIT %s
            """,
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


def open_meeting_voting(meeting_id):
    """Sets voting_state='open' on a meeting."""
    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE meetings SET voting_state='open', updated_at=NOW() WHERE id=%s",
            (meeting_id,),
        )


def close_meeting_voting(meeting_id):
    """Sets voting_state='closed' on a meeting."""
    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE meetings SET voting_state='closed', updated_at=NOW() WHERE id=%s",
            (meeting_id,),
        )


def get_book_proposals_for_meeting(meeting_id):
    """Returns book proposals linked to a specific meeting_id."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT bp.id as proposal_id, bp.book_id, bp.proposed_by, bp.created_at,
                   b.title, b.author, b.cover, b.pages,
                   COALESCE(v.votes,0) as votes
            FROM book_proposals bp
            JOIN books b ON b.id = bp.book_id
            LEFT JOIN (SELECT proposal_id, COUNT(*) as votes FROM book_votes GROUP BY proposal_id) v
                ON v.proposal_id = bp.id
            WHERE bp.meeting_id = %s AND bp.is_active = TRUE
            ORDER BY votes DESC, bp.created_at ASC
            """,
            (meeting_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def get_all_polls_for_meeting(meeting_id, poll_type='books'):
    """Returns all polls linked to a meeting_id."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT * FROM telegram_polls
            WHERE meeting_id = %s AND poll_type = %s
            ORDER BY created_at ASC
            """,
            (meeting_id, poll_type),
        )
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


def update_meeting(meeting_id, name=None, final_date=None, summary=None, status=None, book_id=None, location=None, notes=None, voting_state=None, meeting_time=None, extras=None):
    fields, values = [], []
    if name is not None:          fields.append("name = %s");          values.append(name)
    if final_date is not None:    fields.append("final_date = %s");    values.append(final_date)
    if summary is not None:       fields.append("summary = %s");       values.append(summary)
    if status is not None:        fields.append("status = %s");        values.append(status)
    if book_id is not None:       fields.append("book_id = %s");       values.append(book_id)
    if location is not None:      fields.append("location = %s");      values.append(location or None)
    if notes is not None:         fields.append("notes = %s");         values.append(notes or None)
    if voting_state is not None:  fields.append("voting_state = %s");  values.append(voting_state)
    if meeting_time is not None:  fields.append("meeting_time = %s");  values.append(meeting_time or None)
    if extras is not None:        fields.append("extras = %s");        values.append(extras or None)
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


def add_attendance(meeting_id, user_name=None, user_id=None):
    user_name, user_id = _normalize_user_identity(user_name, user_id)
    with get_cursor(commit=True) as cur:
        cur.execute("""
        INSERT INTO meeting_attendance(meeting_id, user_name, user_id)
        VALUES(%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id
        """, (meeting_id, user_name, user_id))
        ok = cur.fetchone() is not None
        if ok:
            logger.info("Asistencia añadida: %s user_id=%s a reunion_id=%d", user_name, user_id, meeting_id)
        else:
            logger.warning("Asistencia duplicada ignorada: %s user_id=%s ya en reunion_id=%d", user_name, user_id, meeting_id)
        return ok


def remove_attendance(meeting_id, user_name=None, user_id=None):
    user_name, user_id = _normalize_user_identity(user_name, user_id)
    logger.info("Asistencia eliminada: %s user_id=%s de reunion_id=%d", user_name, user_id, meeting_id)
    with get_cursor(commit=True) as cur:
        if user_id is not None:
            cur.execute(
                """
                DELETE FROM meeting_attendance
                WHERE meeting_id=%s AND (user_id=%s OR (user_id IS NULL AND user_name=%s))
                """,
                (meeting_id, user_id, user_name),
            )
            return
        cur.execute("""
        DELETE FROM meeting_attendance WHERE meeting_id=%s AND user_name=%s
        """, (meeting_id, user_name))


def get_attendance(meeting_id=None):
    with get_cursor() as cur:
        if meeting_id is None:
            cur.execute(
                """
                SELECT
                    ma.meeting_id,
                    COALESCE(cm.first_name, cm.username, ma.user_name) AS user_name,
                    ma.user_id
                FROM meeting_attendance ma
                LEFT JOIN club_members cm ON cm.user_id = ma.user_id
                ORDER BY ma.meeting_id DESC, user_name ASC
                """
            )
            return [dict(r) for r in cur.fetchall()]
        cur.execute("""
        SELECT COALESCE(cm.first_name, cm.username, ma.user_name) AS user_name
        FROM meeting_attendance ma
        LEFT JOIN club_members cm ON cm.user_id = ma.user_id
        WHERE ma.meeting_id=%s ORDER BY user_name ASC
        """, (meeting_id,))
        return [r["user_name"] for r in cur.fetchall()]


def get_attendance_members(meeting_id):
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                ma.user_id,
                COALESCE(cm.first_name, cm.username, ma.user_name) AS user_name
            FROM meeting_attendance ma
            LEFT JOIN club_members cm ON cm.user_id = ma.user_id
            WHERE ma.meeting_id=%s
            ORDER BY user_name ASC
            """,
            (meeting_id,),
        )
        return [dict(row) for row in cur.fetchall()]


def get_meeting_attendance_count(meeting_id):
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*)::int AS total FROM meeting_attendance WHERE meeting_id=%s", (meeting_id,))
        return cur.fetchone()["total"]


# =========================================================
# RATINGS
# =========================================================

def rate_book(book_id, user_name, score, review=None, user_id=None):
    user_name, user_id = _normalize_user_identity(user_name, user_id)
    logger.info("Valoración libro: book_id=%d user=%s user_id=%s score=%d", book_id, user_name, user_id, score)
    with get_cursor(commit=True) as cur:
        if user_id is not None:
            cur.execute(
                """
                SELECT id FROM book_ratings
                WHERE book_id=%s AND (user_id=%s OR (user_id IS NULL AND user_name=%s))
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (book_id, user_id, user_name),
            )
            row = cur.fetchone()
            if row:
                cur.execute(
                    """
                    UPDATE book_ratings
                    SET user_name=%s, user_id=%s, score=%s, review=%s
                    WHERE id=%s
                    RETURNING *
                    """,
                    (user_name, user_id, score, review, row["id"]),
                )
                return dict(cur.fetchone())
        cur.execute("""
        INSERT INTO book_ratings(book_id, user_name, user_id, score, review)
        VALUES(%s,%s,%s,%s,%s)
        ON CONFLICT (book_id, user_name) DO UPDATE
            SET user_id=EXCLUDED.user_id, score=EXCLUDED.score, review=EXCLUDED.review
        RETURNING *
        """, (book_id, user_name, user_id, score, review))
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
    ensure_cycle_record(cycle_key)
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


def close_poll(poll_db_id) -> bool:
    """Marca la encuesta como cerrada. Devuelve True solo si este llamador la cerró
    (la fila estaba abierta). Devuelve False si ya estaba cerrada → el llamador no
    debe procesar el resultado para evitar doble anuncio de ganador."""
    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE telegram_polls SET is_closed=TRUE WHERE id=%s AND is_closed=FALSE",
            (poll_db_id,),
        )
        closed_now = cur.rowcount > 0
    if closed_now:
        logger.info("Encuesta cerrada: db_id=%d", poll_db_id)
    else:
        logger.warning("close_poll: db_id=%d ya estaba cerrada (llamada duplicada ignorada)", poll_db_id)
    return closed_now


def get_poll_by_telegram_id(telegram_poll_id):
    """Find a poll by its Telegram poll_id string."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM telegram_polls WHERE poll_id=%s ORDER BY created_at DESC LIMIT 1",
            (telegram_poll_id,)
        )
        row = cur.fetchone()
        return dict(row) if row else None


def set_poll_option_mapping(poll_id, entity_type, entity_ids):
    entity_ids = list(entity_ids or [])
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM poll_option_mappings WHERE poll_id=%s", (poll_id,))
        for option_index, entity_id in enumerate(entity_ids):
            cur.execute(
                """
                INSERT INTO poll_option_mappings(poll_id, option_index, entity_type, entity_id)
                VALUES(%s,%s,%s,%s)
                ON CONFLICT (poll_id, option_index) DO UPDATE
                SET entity_type=EXCLUDED.entity_type, entity_id=EXCLUDED.entity_id
                """,
                (poll_id, option_index, entity_type, int(entity_id)),
            )


def get_poll_option_mapping(poll_id):
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT option_index, entity_type, entity_id
            FROM poll_option_mappings
            WHERE poll_id=%s
            ORDER BY option_index ASC
            """,
            (poll_id,),
        )
        rows = cur.fetchall()
    return [row["entity_id"] for row in rows]


def set_poll_user_selection(poll_id, user_id, option_ids):
    normalized_user_id = _coerce_user_id(user_id)
    if normalized_user_id is None:
        raise ValueError("user_id invalido para guardar seleccion de encuesta")
    payload = [int(option_id) for option_id in list(option_ids or [])]
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO poll_user_selections(poll_id, user_id, selected_option_ids, updated_at)
            VALUES(%s,%s,%s,NOW())
            ON CONFLICT (poll_id, user_id) DO UPDATE
            SET selected_option_ids=EXCLUDED.selected_option_ids, updated_at=NOW()
            """,
            (poll_id, normalized_user_id, Json(payload)),
        )


def get_poll_user_selection(poll_id, user_id):
    normalized_user_id = _coerce_user_id(user_id)
    if normalized_user_id is None:
        return []
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT selected_option_ids
            FROM poll_user_selections
            WHERE poll_id=%s AND user_id=%s
            LIMIT 1
            """,
            (poll_id, normalized_user_id),
        )
        row = cur.fetchone()
    return list(row["selected_option_ids"] or []) if row else []


def remove_book_vote(proposal_id, user_name=None, user_id=None):
    """Remove a specific user's vote for a book."""
    user_name, user_id = _normalize_user_identity(user_name, user_id)
    with get_cursor(commit=True) as cur:
        if user_id is not None:
            cur.execute(
                """
                DELETE FROM book_votes
                WHERE proposal_id=%s AND (user_id=%s OR (user_id IS NULL AND user_name=%s))
                """,
                (proposal_id, user_id, user_name),
            )
            return
        cur.execute(
            "DELETE FROM book_votes WHERE proposal_id=%s AND user_name=%s",
            (proposal_id, user_name)
        )


def remove_theme_vote(theme_id, user_name=None, user_id=None):
    """Remove a specific user's vote for a theme."""
    user_name, user_id = _normalize_user_identity(user_name, user_id)
    with get_cursor(commit=True) as cur:
        if user_id is not None:
            cur.execute(
                """
                DELETE FROM theme_votes
                WHERE theme_id=%s AND (user_id=%s OR (user_id IS NULL AND user_name=%s))
                """,
                (theme_id, user_id, user_name),
            )
            return
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

def get_all_books_history(limit: int = 250):
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
        LIMIT %s
        """, (limit,))
        return [dict(r) for r in cur.fetchall()]


def get_all_themes_history(limit: int = 250):
    """All themes across all cycles."""
    with get_cursor() as cur:
        cur.execute("""
        SELECT t.id, t.name, t.cycle_key, t.created_by, t.is_active,
               COUNT(tv.id)::int AS votes
        FROM themes t
        LEFT JOIN theme_votes tv ON tv.theme_id = t.id
        GROUP BY t.id, t.name, t.cycle_key, t.created_by, t.is_active
        ORDER BY t.cycle_key DESC, votes DESC
        LIMIT %s
        """, (limit,))
        return [dict(r) for r in cur.fetchall()]


def get_all_polls_history(limit: int = 250):
    """All Telegram polls across all cycles."""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM telegram_polls ORDER BY created_at DESC LIMIT %s", (limit,))
        return [dict(r) for r in cur.fetchall()]


def get_all_meetings_history(limit: int = 250):
    """All meetings with attendee count."""
    with get_cursor() as cur:
        cur.execute("""
        SELECT m.*, b.title AS book_title,
               COUNT(ma.id)::int AS attendee_count
        FROM meetings m
        LEFT JOIN books b ON b.id = m.book_id
        LEFT JOIN meeting_attendance ma ON ma.meeting_id = m.id
        GROUP BY m.id, b.title
        ORDER BY COALESCE(m.final_date, m.created_at) DESC
        LIMIT %s
        """, (limit,))
        return [dict(r) for r in cur.fetchall()]


# =========================================================
# CONFIG & CYCLE MANAGEMENT
# =========================================================

def get_active_cycle_keys():
    """Lista de ciclos actualmente abiertos (no cerrados)."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT cycle_key
            FROM cycles
            WHERE is_active = TRUE
            ORDER BY updated_at DESC, created_at DESC
            """
        )
        rows = [row["cycle_key"] for row in cur.fetchall()]
    if rows:
        return rows
    raw = get_config("active_cycles") or ""
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        ck = get_config("active_cycle_key")
        if ck:
            keys = [ck]
    return keys


def add_active_cycle(key):
    key = (key or "").strip()
    if not key:
        return
    ensure_cycle_record(key, is_active=True)
    keys = [key] + [cycle_key for cycle_key in get_active_cycle_keys() if cycle_key != key]
    keys = _dedupe_text_values(keys)
    set_config("active_cycles", ",".join(keys))
    set_config("active_cycle_key", key)


def remove_active_cycle(key):
    key = (key or "").strip()
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE cycles
            SET is_active = FALSE, proposals_locked = FALSE, updated_at = NOW()
            WHERE cycle_key = %s
            """,
            (key,),
        )
    keys = [k for k in get_active_cycle_keys() if k != key]
    set_config("active_cycles", ",".join(keys))
    set_config("active_cycle_key", keys[0] if keys else "")


def cycle_exists(cycle_key):
    cycle_key = (cycle_key or "").strip()
    if not cycle_key:
        return False
    with get_cursor() as cur:
        cur.execute("SELECT 1 FROM cycles WHERE cycle_key=%s LIMIT 1", (cycle_key,))
        row = cur.fetchone()
    return bool(row) or cycle_key in set(get_all_cycle_keys()) or cycle_key in set(get_active_cycle_keys())


def get_cycle_theme(cycle_key=None):
    cycle_key = (cycle_key or get_current_cycle_key() or "").strip()
    if not cycle_key:
        return ""
    with get_cursor() as cur:
        cur.execute("SELECT active_theme FROM cycles WHERE cycle_key=%s LIMIT 1", (cycle_key,))
        row = cur.fetchone()
    return (row["active_theme"] or "") if row and row["active_theme"] is not None else ""


def set_cycle_theme(cycle_key, theme):
    cycle_key = (cycle_key or "").strip()
    if not cycle_key:
        raise ValueError("Falta cycle_key")
    ensure_cycle_record(cycle_key, active_theme=(theme or "").strip() or None)


def rename_cycle_key(old_key, new_key):
    old_key = (old_key or "").strip()
    new_key = (new_key or "").strip()
    if not old_key or not new_key:
        raise ValueError("Nombre de ciclo inválido")
    if old_key == new_key:
        return {}

    active_cycles = [new_key if key == old_key else key for key in get_active_cycle_keys()]
    locked_cycles = [new_key if key == old_key else key for key in get_locked_cycle_keys()]
    current_cycle = get_current_cycle_key()
    current_theme_value = get_cycle_theme(old_key)
    summary = {}

    with get_cursor(commit=True) as cur:
        for table_name in ("book_proposals", "themes", "meetings", "telegram_polls", "book_waitlist"):
            cur.execute(f"UPDATE {table_name} SET cycle_key=%s WHERE cycle_key=%s", (new_key, old_key))
            summary[table_name] = cur.rowcount

        cur.execute(
            """
            UPDATE cycles
            SET cycle_key=%s, updated_at=NOW()
            WHERE cycle_key=%s
            """,
            (new_key, old_key),
        )
        summary["cycles"] = cur.rowcount

        # Update app_config and cycles.proposals_locked inside the same transaction
        # so all changes are atomic — no partial state if the process crashes mid-way.
        def _upsert_config(key, value):
            cur.execute(
                """
                INSERT INTO app_config(key, value) VALUES(%s,%s)
                ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()
                """,
                (key, str(value)),
            )

        _upsert_config("active_cycles", ",".join(_dedupe_text_values(active_cycles)))
        if current_cycle == old_key:
            _upsert_config("active_cycle_key", new_key)

        normalized_locked = _dedupe_text_values(locked_cycles)
        cur.execute("UPDATE cycles SET proposals_locked = FALSE WHERE proposals_locked = TRUE")
        for lk in normalized_locked:
            cur.execute(
                """
                INSERT INTO cycles (cycle_key, proposals_locked)
                VALUES (%s, TRUE)
                ON CONFLICT (cycle_key) DO UPDATE
                SET proposals_locked = TRUE, updated_at = NOW()
                """,
                (lk,),
            )
        _upsert_config("proposals_locked_for", ",".join(normalized_locked))

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
    winner = books[0] if books else None

    is_locked = cycle_key in set(get_locked_cycle_keys())

    active_theme = get_cycle_theme(cycle_key)

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
            SELECT cycle_key FROM cycles
            UNION SELECT cycle_key FROM book_proposals
            UNION SELECT cycle_key FROM themes
            UNION SELECT cycle_key FROM meetings
        ) t ORDER BY cycle_key DESC
        """)
        return [r["cycle_key"] for r in cur.fetchall()]


# =========================================================
# READING PROGRESS
# =========================================================

def log_reading_progress(user_name, book_id, pages_read, user_id=None):
    user_name, user_id = _normalize_user_identity(user_name, user_id)
    with get_cursor(commit=True) as cur:
        if user_id is not None:
            cur.execute(
                """
                SELECT id
                FROM reading_progress
                WHERE book_id=%s AND (user_id=%s OR (user_id IS NULL AND user_name=%s))
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (book_id, user_id, user_name),
            )
            row = cur.fetchone()
            if row:
                cur.execute(
                    """
                    UPDATE reading_progress
                    SET user_name=%s, user_id=%s, pages_read=%s, updated_at=NOW()
                    WHERE id=%s
                    RETURNING *
                    """,
                    (user_name, user_id, pages_read, row["id"]),
                )
                updated = cur.fetchone()
                return dict(updated) if updated else None
        cur.execute("""
        INSERT INTO reading_progress(user_name, user_id, book_id, pages_read, updated_at)
        VALUES(%s,%s,%s,%s,NOW())
        ON CONFLICT(user_name, book_id) DO UPDATE
            SET user_id=EXCLUDED.user_id, pages_read=EXCLUDED.pages_read, updated_at=NOW()
        RETURNING *
        """, (user_name, user_id, book_id, pages_read))
        row = cur.fetchone()
        return dict(row) if row else None

def get_reading_progress(book_id):
    with get_cursor() as cur:
        cur.execute("""
        SELECT COALESCE(cm.first_name, cm.username, rp.user_name) AS user_name, rp.pages_read, rp.updated_at
        FROM reading_progress rp
        LEFT JOIN club_members cm ON cm.user_id = rp.user_id
        WHERE rp.book_id=%s
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


def build_scoped_message_key(base_key, audience=None, phase=None, cycle_key=None):
    parts = [base_key]
    if audience:
        parts.append(f"aud:{audience}")
    if phase:
        parts.append(f"phase:{phase}")
    if cycle_key:
        parts.append(f"cycle:{cycle_key}")
    return "|".join(parts)


def get_scoped_message_variants(base_key, audience=None, phase=None, cycle_key=None):
    candidates = []
    scopes = []
    if audience:
        scopes.append(("aud", audience))
    if phase:
        scopes.append(("phase", phase))
    if cycle_key:
        scopes.append(("cycle", cycle_key))
    for mask in range((1 << len(scopes)) - 1, 0, -1):
        parts = [base_key]
        for idx, (scope_key, scope_value) in enumerate(scopes):
            if mask & (1 << idx):
                parts.append(f"{scope_key}:{scope_value}")
        candidates.append("|".join(parts))
    candidates.append(base_key)
    seen = []
    for key in candidates:
        if key not in seen:
            seen.append(key)
    return seen


def get_message_template_scoped(base_key, audience=None, phase=None, cycle_key=None):
    keys = get_scoped_message_variants(
        base_key,
        audience=audience,
        phase=phase,
        cycle_key=cycle_key,
    )
    with get_cursor() as cur:
        cur.execute(
            "SELECT key, value FROM message_templates WHERE key = ANY(%s)",
            (keys,),
        )
        rows = {row["key"]: row["value"] for row in cur.fetchall()}
    for key in keys:
        if key in rows:
            return rows[key], key
    return None, base_key


def get_scoped_message_templates():
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT key, value, updated_at
            FROM message_templates
            WHERE key LIKE '%%|%%'
            ORDER BY updated_at DESC, key ASC
            """
        )
        return [dict(r) for r in cur.fetchall()]


def get_cycle_bot_settings(cycle_key=None):
    cycle_key = cycle_key or get_current_cycle_key()
    defaults = {
        "private_highlights": [],
        "group_highlights": [],
        "hidden_commands": [],
        "context_note": "",
        "help_note": "",
        "soft_mode_enabled": True,
    }
    data = get_json_config(f"bot_context:{cycle_key}", {}) or {}
    settings = {**defaults, **data}
    for key in ("private_highlights", "group_highlights", "hidden_commands"):
        value = settings.get(key) or []
        if isinstance(value, str):
            value = [item.strip() for item in value.split(",") if item.strip()]
        settings[key] = [str(item).strip() for item in value if str(item).strip()]
    settings["soft_mode_enabled"] = str(settings.get("soft_mode_enabled", True)).lower() not in {"0", "false", "no"}
    return settings


def set_cycle_bot_settings(cycle_key, settings):
    payload = {
        "private_highlights": settings.get("private_highlights") or [],
        "group_highlights": settings.get("group_highlights") or [],
        "hidden_commands": settings.get("hidden_commands") or [],
        "context_note": (settings.get("context_note") or "").strip(),
        "help_note": (settings.get("help_note") or "").strip(),
        "soft_mode_enabled": bool(settings.get("soft_mode_enabled", True)),
    }
    set_json_config(f"bot_context:{cycle_key}", payload)


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


def get_custom_reminders():
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                id, title, message, schedule_type, day_of_week,
                hour, minute, interval_hours, enabled, created_at, updated_at
            FROM custom_reminders
            ORDER BY created_at ASC, id ASC
            """
        )
        rows = []
        for row in cur.fetchall():
            item = dict(row)
            item["hours"] = item.get("interval_hours")
            rows.append(item)
    return rows


def upsert_custom_reminder(
    *,
    reminder_id,
    title,
    message,
    schedule_type="interval",
    day_of_week=None,
    hour=None,
    minute=None,
    interval_hours=None,
    enabled=True,
):
    reminder_id = str(reminder_id or "").strip()
    if not reminder_id:
        raise ValueError("Falta el id del recordatorio")
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO custom_reminders (
                id, title, message, schedule_type, day_of_week,
                hour, minute, interval_hours, enabled, updated_at
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
            ON CONFLICT (id) DO UPDATE
            SET
                title=EXCLUDED.title,
                message=EXCLUDED.message,
                schedule_type=EXCLUDED.schedule_type,
                day_of_week=EXCLUDED.day_of_week,
                hour=EXCLUDED.hour,
                minute=EXCLUDED.minute,
                interval_hours=EXCLUDED.interval_hours,
                enabled=EXCLUDED.enabled,
                updated_at=NOW()
            RETURNING *
            """,
            (
                reminder_id,
                (title or "").strip() or "Recordatorio",
                (message or "").strip(),
                (schedule_type or "interval").strip() or "interval",
                (day_of_week or "").strip() or None,
                int(hour) if hour not in (None, "") else None,
                int(minute) if minute not in (None, "") else None,
                int(interval_hours) if interval_hours not in (None, "") else None,
                bool(enabled),
            ),
        )
        return dict(cur.fetchone())


def delete_custom_reminder(reminder_id):
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM custom_reminders WHERE id=%s", (str(reminder_id),))
        return cur.rowcount


def toggle_custom_reminder(reminder_id):
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE custom_reminders
            SET enabled = NOT enabled, updated_at = NOW()
            WHERE id=%s
            RETURNING *
            """,
            (str(reminder_id),),
        )
        row = cur.fetchone()
        return dict(row) if row else None


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
    active_theme = get_cycle_theme(cycle)
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
    default_cycle = active_cycle_keys[0]

    states = []
    for ck in active_cycle_keys:
        state = get_cycle_dashboard_state(cycle=ck)
        state["is_default"] = (ck == default_cycle)
        states.append(state)
    return states


# =========================================================
# USER STATS
# =========================================================

def get_user_stats(user_name=None, user_id=None):
    stats = {}
    cycle = get_current_cycle_key()
    user_name, user_id = _normalize_user_identity(user_name, user_id)
    with get_cursor() as cur:
        if user_id is not None:
            cur.execute(
                """
                SELECT COUNT(*)::int AS n
                FROM book_proposals
                WHERE proposed_by_user_id=%s OR (proposed_by_user_id IS NULL AND proposed_by=%s)
                """,
                (user_id, user_name),
            )
        else:
            cur.execute("SELECT COUNT(*)::int AS n FROM book_proposals WHERE proposed_by=%s", (user_name,))
        stats["proposals_total"] = cur.fetchone()["n"]
        if user_id is not None:
            cur.execute(
                """
                SELECT COUNT(*)::int AS n
                FROM book_proposals
                WHERE cycle_key=%s
                  AND (proposed_by_user_id=%s OR (proposed_by_user_id IS NULL AND proposed_by=%s))
                """,
                (cycle, user_id, user_name),
            )
        else:
            cur.execute("SELECT COUNT(*)::int AS n FROM book_proposals WHERE proposed_by=%s AND cycle_key=%s", (user_name, cycle))
        stats["proposals_cycle"] = cur.fetchone()["n"]
        if user_id is not None:
            cur.execute(
                """
                SELECT COUNT(*)::int AS n
                FROM book_votes
                WHERE user_id=%s OR (user_id IS NULL AND user_name=%s)
                """,
                (user_id, user_name),
            )
        else:
            cur.execute("SELECT COUNT(*)::int AS n FROM book_votes WHERE user_name=%s", (user_name,))
        stats["book_votes"] = cur.fetchone()["n"]
        if user_id is not None:
            cur.execute(
                """
                SELECT COUNT(*)::int AS n
                FROM theme_votes
                WHERE user_id=%s OR (user_id IS NULL AND user_name=%s)
                """,
                (user_id, user_name),
            )
        else:
            cur.execute("SELECT COUNT(*)::int AS n FROM theme_votes WHERE user_name=%s", (user_name,))
        stats["theme_votes"] = cur.fetchone()["n"]
        if user_id is not None:
            cur.execute(
                """
                SELECT COUNT(*)::int AS n
                FROM meeting_attendance
                WHERE user_id=%s OR (user_id IS NULL AND user_name=%s)
                """,
                (user_id, user_name),
            )
        else:
            cur.execute("SELECT COUNT(*)::int AS n FROM meeting_attendance WHERE user_name=%s", (user_name,))
        stats["meetings"] = cur.fetchone()["n"]
        if user_id is not None:
            cur.execute(
                """
                SELECT COUNT(*)::int AS n, ROUND(AVG(score)::numeric,1) AS avg
                FROM book_ratings
                WHERE user_id=%s OR (user_id IS NULL AND user_name=%s)
                """,
                (user_id, user_name),
            )
        else:
            cur.execute("SELECT COUNT(*)::int AS n, ROUND(AVG(score)::numeric,1) AS avg FROM book_ratings WHERE user_name=%s", (user_name,))
        row = cur.fetchone()
        stats["ratings"] = row["n"]
        stats["avg_score"] = float(row["avg"]) if row["avg"] else None
        if user_id is not None:
            cur.execute(
                """
                SELECT rp.pages_read, b.pages AS total, b.title
                FROM reading_progress rp
                JOIN books b ON b.id=rp.book_id
                WHERE rp.user_id=%s OR (rp.user_id IS NULL AND rp.user_name=%s)
                ORDER BY rp.updated_at DESC
                LIMIT 1
                """,
                (user_id, user_name),
            )
        else:
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
    "book_waitlist", "club_members", "app_events", "admin_audit_log", "bug_reports",
]


def get_table_names():
    return list(ALLOWED_TABLES)


def get_table_columns(table_name):
    if table_name not in ALLOWED_TABLES:
        raise ValueError(f"Tabla no permitida: {table_name}")
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                column_name,
                data_type,
                udt_name,
                is_nullable,
                column_default
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position
            """,
            (table_name,),
        )
        columns = []
        for row in cur.fetchall():
            data_type = row["data_type"]
            udt_name = row["udt_name"] or ""
            columns.append(
                {
                    "name": row["column_name"],
                    "data_type": data_type,
                    "udt_name": udt_name,
                    "is_nullable": row["is_nullable"] == "YES",
                    "has_default": row["column_default"] is not None,
                    "is_boolean": data_type == "boolean",
                    "is_json": data_type in ("json", "jsonb"),
                    "is_array": udt_name.startswith("_"),
                    "is_textarea": data_type in ("text", "json", "jsonb") or udt_name.startswith("_"),
                }
            )
        return columns


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
    columns = get_table_columns(table_name)
    column_names = [column["name"] for column in columns]
    with get_cursor() as cur:
        column_name_set = set(column_names)
        order_column = None
        for candidate in ("id", "created_at", "updated_at", "key", "user_id"):
            if candidate in column_name_set:
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
            return column_names, [], primary_key
        return column_names, rows, primary_key


def _coerce_table_value(raw_value, column_meta, *, set_null=False):
    name = column_meta["name"]
    data_type = column_meta["data_type"]
    udt_name = column_meta["udt_name"]
    is_nullable = column_meta["is_nullable"]

    if set_null:
        if not is_nullable:
            raise ValueError(f"La columna {name} no admite NULL")
        return None

    if raw_value is None:
        if is_nullable:
            return None
        raise ValueError(f"Falta un valor para la columna {name}")

    if not isinstance(raw_value, str):
        return raw_value

    raw_text = raw_value
    stripped = raw_text.strip()

    if data_type == "boolean":
        if stripped == "":
            if is_nullable:
                return None
            raise ValueError(f"La columna {name} no puede estar vacia")
        normalized = stripped.lower()
        if normalized in {"1", "true", "t", "yes", "y", "si", "s", "on"}:
            return True
        if normalized in {"0", "false", "f", "no", "n", "off"}:
            return False
        raise ValueError(f"Valor booleano invalido en {name}: {raw_text!r}")

    if data_type in {"smallint", "integer", "bigint"}:
        if stripped == "":
            if is_nullable:
                return None
            raise ValueError(f"La columna {name} no puede estar vacia")
        try:
            return int(stripped)
        except ValueError as exc:
            raise ValueError(f"Valor entero invalido en {name}: {raw_text!r}") from exc

    if data_type in {"numeric", "real", "double precision", "decimal"}:
        if stripped == "":
            if is_nullable:
                return None
            raise ValueError(f"La columna {name} no puede estar vacia")
        try:
            return Decimal(stripped)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"Valor numerico invalido en {name}: {raw_text!r}") from exc

    if data_type in {"json", "jsonb"}:
        if stripped == "":
            if is_nullable:
                return None
            raise ValueError(f"La columna {name} no puede estar vacia")
        try:
            return Json(json.loads(raw_text))
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON invalido en {name}: {exc.msg}") from exc

    if udt_name.startswith("_"):
        if stripped == "":
            if is_nullable:
                return None
            raise ValueError(f"La columna {name} no puede estar vacia")
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Array invalido en {name}: {exc.msg}") from exc
        if not isinstance(parsed, list):
            raise ValueError(f"La columna {name} debe recibir un array JSON")
        return parsed

    if data_type in {"date", "time without time zone", "time with time zone", "timestamp without time zone", "timestamp with time zone"}:
        if stripped == "":
            if is_nullable:
                return None
            raise ValueError(f"La columna {name} no puede estar vacia")
        return stripped

    return raw_text


def get_table_row(table_name, pk_column, pk_value):
    if table_name not in ALLOWED_TABLES:
        raise ValueError(f"Tabla no permitida: {table_name}")
    real_pk = get_table_primary_key(table_name)
    if not real_pk:
        raise ValueError(f"La tabla {table_name} no tiene una clave utilizable")
    if pk_column != real_pk:
        raise ValueError(f"Clave invalida para {table_name}: {pk_column}")

    columns = {column["name"]: column for column in get_table_columns(table_name)}
    if real_pk not in columns:
        raise ValueError(f"La columna clave {real_pk} no existe en {table_name}")
    lookup_value = _coerce_table_value(pk_value, columns[real_pk])

    with get_cursor() as cur:
        cur.execute(f"SELECT * FROM {table_name} WHERE {real_pk} = %s LIMIT 1", (lookup_value,))
        row = cur.fetchone()
        return dict(row) if row else None


def format_table_value_for_form(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat(timespec="seconds")
    return str(value)


def update_table_row(table_name, pk_column, pk_value, updates):
    if table_name not in ALLOWED_TABLES:
        raise ValueError(f"Tabla no permitida: {table_name}")
    real_pk = get_table_primary_key(table_name)
    if not real_pk:
        raise ValueError(f"La tabla {table_name} no tiene una clave utilizable para editar filas")
    if pk_column != real_pk:
        raise ValueError(f"Clave invalida para {table_name}: {pk_column}")

    columns = {column["name"]: column for column in get_table_columns(table_name)}
    if real_pk not in columns:
        raise ValueError(f"La columna clave {real_pk} no existe en {table_name}")

    assignments = []
    values = []
    for column_name, payload in updates.items():
        if column_name == real_pk:
            continue
        column_meta = columns.get(column_name)
        if not column_meta:
            raise ValueError(f"La columna {column_name} no existe en {table_name}")
        assignments.append(f"{column_name} = %s")
        values.append(
            _coerce_table_value(
                payload.get("value"),
                column_meta,
                set_null=bool(payload.get("set_null")),
            )
        )

    if not assignments:
        raise ValueError("No hay columnas editables para guardar")

    lookup_value = _coerce_table_value(pk_value, columns[real_pk])
    values.append(lookup_value)

    with get_cursor(commit=True) as cur:
        cur.execute(
            f"UPDATE {table_name} SET {', '.join(assignments)} WHERE {real_pk} = %s",
            tuple(values),
        )
        return cur.rowcount


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


def execute_raw_sql(sql):
    """Execute arbitrary SQL. Returns (columns, rows, rowcount, is_select)."""
    sql = sql.strip()
    is_select = sql.upper().startswith("SELECT")
    with get_cursor(commit=not is_select) as cur:
        cur.execute(sql)
        if is_select:
            rows = [dict(r) for r in cur.fetchall()]
            cols = list(rows[0].keys()) if rows else (
                [desc[0] for desc in cur.description] if cur.description else []
            )
            return cols, rows, len(rows), True
        else:
            return [], [], cur.rowcount, False


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


def log_public_page_access(
    *,
    route: str,
    method: str = "GET",
    ip: str = None,
    user_agent: str = None,
    referrer: str = None,
    query_string: str = None,
):
    """Guarda trafico de la web publica aparte para no mezclarlo con logs operativos."""
    try:
        with get_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO public_page_access_log (route, method, ip, user_agent, referrer, query_string)
                VALUES (%s,%s,%s,%s,%s,%s)
                """,
                (
                    (route or "").strip() or "/publico",
                    (method or "GET").strip().upper()[:10],
                    (ip or "").strip() or None,
                    (user_agent or "").strip()[:500] or None,
                    (referrer or "").strip()[:500] or None,
                    (query_string or "").strip()[:500] or None,
                ),
            )
    except Exception as exc:
        logger.warning("log_public_page_access DB write failed: %s", exc)


def get_public_page_access_logs(limit: int = 300, ip: str = None) -> list[PublicPageAccessLogRow]:
    with get_cursor() as cur:
        conds, params = [], []
        if ip:
            conds.append("ip = %s"); params.append(ip)
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        params.append(limit)
        cur.execute(
            f"SELECT * FROM public_page_access_log {where} ORDER BY created_at DESC LIMIT %s",
            params,
        )
        return [dict(r) for r in cur.fetchall()]


def is_admin_ip_blocked(ip: str) -> bool:
    ip = (ip or "").strip()
    if not ip:
        return False
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM admin_blocked_ips
            WHERE ip = %s AND blocked_at IS NOT NULL
            """,
            (ip,),
        )
        return cur.fetchone() is not None


def register_admin_login_failure(ip: str, *, block_after: int = 3) -> AdminBlockedIPState:
    """
    Persiste los fallos de login admin por IP.

    Se guarda en PostgreSQL para que el bloqueo sobreviva reinicios y siga funcionando
    aunque la app tenga varios workers.
    """
    ip = (ip or "").strip() or "unknown"
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO admin_blocked_ips (
                ip, failed_attempts, first_failed_at, last_failed_at, block_reason
            )
            VALUES (%s, 1, NOW(), NOW(), NULL)
            ON CONFLICT (ip) DO UPDATE
            SET
                failed_attempts = admin_blocked_ips.failed_attempts + 1,
                last_failed_at = NOW()
            RETURNING ip, failed_attempts, blocked_at, block_reason
            """,
            (ip,),
        )
        row = dict(cur.fetchone())
        just_blocked = False
        if not row.get("blocked_at") and row["failed_attempts"] >= block_after:
            cur.execute(
                """
                UPDATE admin_blocked_ips
                SET blocked_at = NOW(), block_reason = %s
                WHERE ip = %s
                RETURNING ip, failed_attempts, blocked_at, block_reason
                """,
                (f"admin_login_failed_{block_after}x", ip),
            )
            row = dict(cur.fetchone())
            just_blocked = True
    row["is_blocked"] = bool(row.get("blocked_at"))
    row["just_blocked"] = just_blocked
    return row


def clear_admin_login_failures(ip: str):
    """Limpia solo los intentos aun no bloqueados; los bloqueos requieren accion manual."""
    ip = (ip or "").strip()
    if not ip:
        return 0
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            DELETE FROM admin_blocked_ips
            WHERE ip = %s AND blocked_at IS NULL
            """,
            (ip,),
        )
        return cur.rowcount


def get_admin_ip_state(ip: str) -> AdminBlockedIPState | None:
    ip = (ip or "").strip()
    if not ip:
        return None
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT ip, failed_attempts, first_failed_at, last_failed_at, blocked_at, block_reason
            FROM admin_blocked_ips
            WHERE ip = %s
            """,
            (ip,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_blocked_admin_ips(limit: int = 200) -> list[AdminBlockedIPState]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT ip, failed_attempts, first_failed_at, last_failed_at, blocked_at, block_reason
            FROM admin_blocked_ips
            WHERE blocked_at IS NOT NULL
            ORDER BY blocked_at DESC, last_failed_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]


def unblock_admin_ip(ip: str) -> AdminBlockedIPState | None:
    """
    El desbloqueo elimina la fila para que la IP vuelva a un estado limpio y no
    arrastre intentos historicos a la siguiente autenticacion.
    """
    ip = (ip or "").strip()
    if not ip:
        return None
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            DELETE FROM admin_blocked_ips
            WHERE ip = %s AND blocked_at IS NOT NULL
            RETURNING ip, failed_attempts, first_failed_at, last_failed_at, blocked_at, block_reason
            """,
            (ip,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def log_admin_audit(
    action: str,
    *,
    actor: str = None,
    route: str = None,
    method: str = None,
    ip: str = None,
    target_type: str = None,
    target_id: str = None,
    status: str = "ok",
    result: str = None,
    before: dict = None,
    after: dict = None,
    extra: dict = None,
):
    logger.info(
        "ADMIN AUDIT [%s/%s] actor=%s route=%s target=%s:%s",
        action,
        status,
        actor or "-",
        route or "-",
        target_type or "-",
        target_id or "-",
    )
    try:
        with get_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO admin_audit_log (
                    actor, action, route, method, ip,
                    target_type, target_id, status, result,
                    before_data, after_data, extra
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    actor,
                    action,
                    route,
                    method,
                    ip,
                    target_type,
                    target_id,
                    status,
                    result,
                    Json(before) if before is not None else None,
                    Json(after) if after is not None else None,
                    Json(extra) if extra is not None else None,
                ),
            )
    except Exception as exc:
        logger.warning("log_admin_audit DB write failed: %s", exc)


def get_admin_audit_logs(limit: int = 200, action: str = None, status: str = None):
    with get_cursor() as cur:
        conds, params = [], []
        if action:
            conds.append("action = %s"); params.append(action)
        if status:
            conds.append("status = %s"); params.append(status)
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        params.append(limit)
        cur.execute(f"SELECT * FROM admin_audit_log {where} ORDER BY created_at DESC LIMIT %s", params)
        return [dict(r) for r in cur.fetchall()]


def search_admin(query, limit_per_section: int = 6):
    term = normalize_admin_search_query(query) if query else ""
    if not term:
        return {
            "books": [],
            "meetings": [],
            "cycles": [],
            "users": [],
            "bugs": [],
            "messages": [],
        }
    pattern = f"%{term}%"
    results = {}
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT b.id, b.title, b.author, bp.cycle_key
            FROM books b
            LEFT JOIN book_proposals bp ON bp.book_id = b.id
            WHERE b.title ILIKE %s OR COALESCE(b.author, '') ILIKE %s
            ORDER BY b.created_at DESC
            LIMIT %s
            """,
            (pattern, pattern, limit_per_section),
        )
        results["books"] = [dict(r) for r in cur.fetchall()]

        cur.execute(
            """
            SELECT id, name, cycle_key, final_date, status
            FROM meetings
            WHERE name ILIKE %s OR COALESCE(location, '') ILIKE %s
            ORDER BY COALESCE(final_date, created_at) DESC
            LIMIT %s
            """,
            (pattern, pattern, limit_per_section),
        )
        results["meetings"] = [dict(r) for r in cur.fetchall()]

        cur.execute(
            """
            SELECT user_id, first_name, username, last_seen
            FROM club_members
            WHERE COALESCE(first_name, '') ILIKE %s
               OR COALESCE(username, '') ILIKE %s
               OR CAST(user_id AS TEXT) ILIKE %s
            ORDER BY last_seen DESC
            LIMIT %s
            """,
            (pattern, pattern, pattern, limit_per_section),
        )
        results["users"] = [dict(r) for r in cur.fetchall()]

        cur.execute(
            """
            SELECT id, username, status, description, created_at
            FROM bug_reports
            WHERE COALESCE(username, '') ILIKE %s OR description ILIKE %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (pattern, pattern, limit_per_section),
        )
        results["bugs"] = [dict(r) for r in cur.fetchall()]

        cur.execute(
            """
            (
                SELECT 'template' AS kind, key AS ref, value AS text, updated_at AS ts
                FROM message_templates
                WHERE key ILIKE %s OR value ILIKE %s
            )
            UNION ALL
            (
                SELECT 'sent' AS kind, CAST(id AS TEXT) AS ref, text, sent_at AS ts
                FROM sent_messages
                WHERE text ILIKE %s
            )
            UNION ALL
            (
                SELECT 'scheduled' AS kind, CAST(id AS TEXT) AS ref, text, send_at AS ts
                FROM scheduled_messages
                WHERE text ILIKE %s
            )
            ORDER BY ts DESC
            LIMIT %s
            """,
            (pattern, pattern, pattern, pattern, limit_per_section),
        )
        results["messages"] = [dict(r) for r in cur.fetchall()]

    needle = term.casefold()
    results["cycles"] = [
        {"cycle_key": cycle}
        for cycle in get_all_cycle_keys()
        if needle in cycle.casefold()
    ][:limit_per_section]
    return results


def get_operational_alerts():
    alerts = []
    current_cycle = get_current_cycle_key()
    winner = get_winner_book(current_cycle)
    next_meeting = get_latest_scheduled_meeting(cycle_key=current_cycle)
    open_theme_poll = get_open_poll("themes", cycle_key=current_cycle)
    open_book_polls = get_open_polls("books", cycle_key=current_cycle)
    open_dates_poll = None
    if next_meeting:
        open_dates_poll = get_open_poll("dates", cycle_key=current_cycle, meeting_id=next_meeting["id"])

    if winner and (not next_meeting or not next_meeting.get("final_date")):
        alerts.append(
            {
                "level": "warning",
                "title": "Reunion sin fecha cerrada",
                "message": f"El ciclo {current_cycle} ya tiene libro ganador pero la reunion aun no tiene fecha confirmada.",
                "action_label": "Gestionar reunion",
                "action_url": f"/meeting/{next_meeting['id']}" if next_meeting else "/meetings",
            }
        )

    for key, title in (
        ("reminder_weekly_enabled", "Recordatorio semanal desactivado"),
        ("reminder_reading_enabled", "Recordatorio de lectura desactivado"),
        ("reminder_daybefore_enabled", "Aviso de hoy/manana desactivado"),
    ):
        if get_config(key, "1") == "0":
            alerts.append(
                {
                    "level": "warning",
                    "title": title,
                    "message": "Revisa el programador para reactivarlo o dejar constancia del motivo.",
                    "action_label": "Abrir programador",
                    "action_url": "/admin/scheduler",
                }
            )

    stale_polls = []
    all_open_polls = ([open_theme_poll] if open_theme_poll else []) + open_book_polls + ([open_dates_poll] if open_dates_poll else [])
    for poll in all_open_polls:
        created_at = poll.get("created_at")
        if created_at and isinstance(created_at, datetime):
            age_hours = (_utcnow() - created_at.replace(tzinfo=None)).total_seconds() / 3600
            if age_hours >= 48:
                stale_polls.append((poll, int(age_hours)))
    for poll, age_hours in stale_polls[:3]:
        alerts.append(
            {
                "level": "danger",
                "title": "Encuesta abierta demasiado tiempo",
                "message": f"La encuesta {poll.get('poll_type')} lleva unas {age_hours}h abierta.",
                "action_label": "Revisar panel",
                "action_url": "/admin",
            }
        )

    return alerts


# =========================================================
# BUG REPORTS
# =========================================================

def create_bug_report(user_id: int, username: str, description: str) -> int:
    description = normalize_bug_description(description)
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
