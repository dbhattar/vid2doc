import sqlite3

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'queued',   -- queued|processing|done|failed
    progress_stage TEXT,
    source_path TEXT NOT NULL,
    document_path TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def get_connection() -> sqlite3.Connection:
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    # WAL allows the api and worker containers to read/write the same file concurrently.
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    conn = get_connection()
    conn.execute(SCHEMA)
    conn.commit()
    conn.close()
