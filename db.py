import sqlite3
from config import DB_PATH


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS recordings (
            id TEXT PRIMARY KEY,
            original_filename TEXT NOT NULL,
            stored_filename TEXT NOT NULL,
            file_size INTEGER,
            duration_seconds REAL,
            transcript TEXT,
            model TEXT,
            status TEXT DEFAULT 'uploaded',
            created_at TEXT DEFAULT (datetime('now')),
            transcribed_at TEXT
        )
    """)
    # Add columns if they don't exist (migrations for existing DBs)
    for col in ["model TEXT", "display_name TEXT"]:
        try:
            conn.execute(f"ALTER TABLE recordings ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass  # column already exists
    # Reset any recordings stuck as 'transcribing' from a previous crash/restart
    conn.execute("UPDATE recordings SET status = 'uploaded', transcript = NULL WHERE status = 'transcribing'")
    conn.commit()
    conn.close()
