import os
import psycopg2

DATABASE_URL = os.getenv("DATABASE_URL")

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()


def init_db():
    cur.execute("""
    CREATE TABLE IF NOT EXISTS books(
        id SERIAL PRIMARY KEY,
        title TEXT,
        author TEXT,
        description TEXT,
        cover TEXT,
        proposed_by TEXT,
        votes INT DEFAULT 0
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS votes(
        user_name TEXT,
        book_id INT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS meetings(
        id SERIAL PRIMARY KEY,
        date TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS attendance(
        user_name TEXT,
        meeting_id INT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS ratings(
        user_name TEXT,
        book_id INT,
        score INT,
        review TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS themes(
        id SERIAL PRIMARY KEY,
        theme TEXT,
        votes INT DEFAULT 0
    )
    """)

    conn.commit()


def insert_book(book, proposed_by="telegram"):
    cur.execute("""
    INSERT INTO books(title, author, description, cover, proposed_by, votes)
    VALUES(%s, %s, %s, %s, %s, %s)
    """, (
        book.get("title", ""),
        book.get("author", ""),
        book.get("description", ""),
        book.get("cover", ""),
        proposed_by,
        0
    ))
    conn.commit()


def get_books():
    cur.execute("""
    SELECT id, title, author, description, cover, proposed_by, votes
    FROM books
    ORDER BY votes DESC, id ASC
    """)
    rows = cur.fetchall()

    return [
        {
            "id": r[0],
            "title": r[1],
            "author": r[2],
            "description": r[3],
            "cover": r[4],
            "proposed_by": r[5],
            "votes": r[6]
        }
        for r in rows
    ]


def get_book_by_id(book_id):
    cur.execute("""
    SELECT id, title, author, description, cover, proposed_by, votes
    FROM books
    WHERE id = %s
    """, (book_id,))
    r = cur.fetchone()

    if not r:
        return None

    return {
        "id": r[0],
        "title": r[1],
        "author": r[2],
        "description": r[3],
        "cover": r[4],
        "proposed_by": r[5],
        "votes": r[6]
    }


def vote_book(user_name, book_id):
    cur.execute("""
    SELECT 1
    FROM votes
    WHERE user_name = %s AND book_id = %s
    """, (user_name, book_id))
    exists = cur.fetchone()

    if exists:
        return False

    cur.execute("""
    INSERT INTO votes(user_name, book_id)
    VALUES(%s, %s)
    """, (user_name, book_id))

    cur.execute("""
    UPDATE books
    SET votes = votes + 1
    WHERE id = %s
    """, (book_id,))

    conn.commit()
    return True


def get_winner_book():
    cur.execute("""
    SELECT id, title, votes
    FROM books
    ORDER BY votes DESC, id ASC
    LIMIT 1
    """)
    row = cur.fetchone()

    if not row:
        return None

    return {
        "id": row[0],
        "title": row[1],
        "votes": row[2]
    }