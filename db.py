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