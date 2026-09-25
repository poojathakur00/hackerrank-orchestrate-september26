"""SQLite read/write access for the per-user financial state cache.

This is the only module that speaks SQL. Everything else (ledger, planner)
calls functions here instead of touching sqlite3 directly.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.db.schema import SCHEMA

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "app_cache.db"


def get_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


RAW_EVENT_COLUMNS = (
    "event_id", "user_id", "event_type", "description", "category", "direction",
    "amount", "currency", "event_date", "settlement_date", "status",
    "linked_event_id", "flexibility", "minimum_allowed_amount",
)


def upsert_raw_events(conn: sqlite3.Connection, rows: list[dict]) -> None:
    """Land financial_events rows exactly as received; same event_id overwrites."""
    now = datetime.now(timezone.utc).isoformat()
    placeholders = ", ".join("?" for _ in range(len(RAW_EVENT_COLUMNS) + 1))
    columns = ", ".join(RAW_EVENT_COLUMNS + ("ingested_at",))
    conn.executemany(
        f"INSERT OR REPLACE INTO raw_financial_events ({columns}) VALUES ({placeholders})",
        [tuple(r[c] for c in RAW_EVENT_COLUMNS) + (now,) for r in rows],
    )


def fetch_raw_events(conn: sqlite3.Connection, user_id: str) -> list[dict]:
    columns = ", ".join(RAW_EVENT_COLUMNS)
    rows = conn.execute(
        f"SELECT {columns} FROM raw_financial_events WHERE user_id = ? ORDER BY event_id",
        (user_id,),
    ).fetchall()
    return [dict(zip(RAW_EVENT_COLUMNS, r)) for r in rows]


def save_profile(conn: sqlite3.Connection, profile: dict) -> None:
    conn.execute(
        """
        INSERT INTO user_profile (
            user_id, home_currency, current_available_balance, minimum_balance_to_keep,
            financial_priorities, expense_categories_to_protect,
            expense_categories_user_is_willing_to_reduce,
            expense_categories_user_is_willing_to_stop,
            payment_methods_user_will_consider, max_installment_months
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            home_currency=excluded.home_currency,
            current_available_balance=excluded.current_available_balance,
            minimum_balance_to_keep=excluded.minimum_balance_to_keep,
            financial_priorities=excluded.financial_priorities,
            expense_categories_to_protect=excluded.expense_categories_to_protect,
            expense_categories_user_is_willing_to_reduce=excluded.expense_categories_user_is_willing_to_reduce,
            expense_categories_user_is_willing_to_stop=excluded.expense_categories_user_is_willing_to_stop,
            payment_methods_user_will_consider=excluded.payment_methods_user_will_consider,
            max_installment_months=excluded.max_installment_months
        """,
        (
            profile["user_id"],
            profile["home_currency"],
            float(profile["current_available_balance"]),
            float(profile["minimum_balance_to_keep"]),
            profile.get("financial_priorities") or "",
            profile.get("expense_categories_to_protect") or "",
            profile.get("expense_categories_user_is_willing_to_reduce") or "",
            profile.get("expense_categories_user_is_willing_to_stop") or "",
            profile.get("payment_methods_user_will_consider") or "",
            int(profile["max_installment_months"]) if profile.get("max_installment_months") else None,
        ),
    )


def fetch_profile(conn: sqlite3.Connection, user_id: str) -> dict:
    row = conn.execute(
        "SELECT * FROM user_profile WHERE user_id = ?", (user_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"no cached profile for {user_id}; run ingestion first")
    columns = [d[0] for d in conn.execute("SELECT * FROM user_profile LIMIT 0").description]
    return dict(zip(columns, row))


