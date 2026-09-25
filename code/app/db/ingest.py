"""Ingestion: financial_profiles.csv -> user_profile,
financial_events.csv -> raw_financial_events (landing, exact copy).

This is the only step that reads the CSVs. Everything downstream —
build_income_credit_tables.py, build_expense_tables.py, the future
summarization/planning agent — reads only from the database.
"""
from __future__ import annotations

import sqlite3

from app.data_sources.csv_source import Dataset, load_dataset
from app.db.repository import get_connection, save_profile, upsert_raw_events


def ingest_all() -> tuple[int, int]:
    """Land raw events and profiles. Returns (events_landed, profiles_saved)."""
    ds = load_dataset()
    conn = get_connection()
    try:
        upsert_raw_events(conn, ds.events)
        for profile in ds.profiles:
            save_profile(conn, profile)
        conn.commit()
    finally:
        conn.close()
    return len(ds.events), len(ds.profiles)


if __name__ == "__main__":
    landed, saved = ingest_all()
    print(f"landed {landed} raw events, saved {saved} profiles")
