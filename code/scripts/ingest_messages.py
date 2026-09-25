"""One-time script: load dataset/messages.csv into the raw_messages table.

Values are stored exactly as they appear in the CSV (all text, blanks kept as
empty strings). Safe to re-run: rows with the same message_id are replaced.

Usage (from the repo root):
    python3 code/scripts/ingest_messages.py
"""
from __future__ import annotations

import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent.parent
CSV_PATH = CODE_DIR.parent / "dataset" / "messages.csv"
DB_PATH = CODE_DIR / "app_cache.db"

COLUMNS = (
    "message_id", "user_id", "request_id", "related_event_id",
    "sent_at", "source_type", "message_text",
)

DDL = """
CREATE TABLE IF NOT EXISTS raw_messages (
    message_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    request_id TEXT,
    related_event_id TEXT,
    sent_at TEXT,
    source_type TEXT,
    message_text TEXT,
    ingested_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_raw_messages_user ON raw_messages (user_id);
"""


def main() -> None:
    with open(CSV_PATH, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    now = datetime.now(timezone.utc).isoformat()
    placeholders = ", ".join("?" for _ in range(len(COLUMNS) + 1))
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(DDL)
        conn.executemany(
            f"INSERT OR REPLACE INTO raw_messages ({', '.join(COLUMNS)}, ingested_at) "
            f"VALUES ({placeholders})",
            [tuple(r[c] for c in COLUMNS) + (now,) for r in rows],
        )
        conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM raw_messages").fetchone()[0]
    finally:
        conn.close()

    print(f"read {len(rows)} rows from {CSV_PATH.name}; raw_messages now has {total} rows")


if __name__ == "__main__":
    main()
