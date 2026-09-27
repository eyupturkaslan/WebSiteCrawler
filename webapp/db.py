import sqlite3
import time

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    -- bumped on password change / "log out everywhere"; invalidates older session cookies
    session_version INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,            -- login_ok, login_fail, signup
    username TEXT,
    ip TEXT,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_auth_events_lookup ON auth_events (kind, ts);

CREATE TABLE IF NOT EXISTS crawls (
    id TEXT PRIMARY KEY,           -- random, not guessable
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    options TEXT NOT NULL,
    status TEXT NOT NULL,          -- queued, running, done, failed
    error TEXT,
    pages_crawled INTEGER,
    health_score INTEGER,
    errors INTEGER,
    warnings INTEGER,
    report_html TEXT,
    report_json TEXT,
    created_at REAL NOT NULL,
    finished_at REAL
);
CREATE INDEX IF NOT EXISTS idx_crawls_user ON crawls (user_id, created_at);
"""


def connect(path):
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(path):
    with connect(path) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        # Jobs run in-process; anything unfinished was lost when the server stopped.
        conn.execute(
            "UPDATE crawls SET status = 'failed', error = 'Sunucu yeniden başlatıldı', finished_at = ? "
            "WHERE status IN ('queued', 'running')",
            (time.time(),),
        )
