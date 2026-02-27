import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "feedback.db")


def _connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = _connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tweets (
            tweet_id       TEXT PRIMARY KEY,
            author_name    TEXT,
            author_handle  TEXT,
            text           TEXT,
            tweet_url      TEXT,
            source_type    TEXT,
            source_detail  TEXT,
            parent_text    TEXT DEFAULT '',
            parent_url     TEXT DEFAULT '',
            likes          INTEGER DEFAULT 0,
            retweets       INTEGER DEFAULT 0,
            replies        INTEGER DEFAULT 0,
            tweet_created_at TEXT,
            collected_at   TEXT
        )
    """)
    for col, default in [
        ("parent_text", "''"),
        ("parent_url", "''"),
    ]:
        try:
            conn.execute(f"ALTER TABLE tweets ADD COLUMN {col} TEXT DEFAULT {default}")
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()


def tweet_exists(tweet_id: str) -> bool:
    conn = _connect()
    row = conn.execute(
        "SELECT 1 FROM tweets WHERE tweet_id = ?", (tweet_id,)
    ).fetchone()
    conn.close()
    return row is not None


def insert_tweet(data: dict) -> bool:
    """Insert a tweet if it doesn't already exist. Returns True if inserted."""
    if tweet_exists(data["tweet_id"]):
        return False
    conn = _connect()
    conn.execute(
        """
        INSERT INTO tweets
            (tweet_id, author_name, author_handle, text, tweet_url,
             source_type, source_detail, parent_text, parent_url,
             likes, retweets, replies,
             tweet_created_at, collected_at)
        VALUES
            (:tweet_id, :author_name, :author_handle, :text, :tweet_url,
             :source_type, :source_detail, :parent_text, :parent_url,
             :likes, :retweets, :replies,
             :tweet_created_at, :collected_at)
        """,
        data,
    )
    conn.commit()
    conn.close()
    return True


def query_tweets(
    since_iso: str | None = None,
    until_iso: str | None = None,
) -> list[dict]:
    """Query tweets with optional date range filter."""
    conn = _connect()
    clauses = []
    params: list = []

    if since_iso:
        clauses.append("tweet_created_at >= ?")
        params.append(since_iso)
    if until_iso:
        clauses.append("tweet_created_at <= ?")
        params.append(until_iso)

    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM tweets{where} ORDER BY tweet_created_at DESC", params
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
