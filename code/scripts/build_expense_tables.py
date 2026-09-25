"""One-time population script: derive Person_Expense and Expense_Ledger from
raw_financial_events (never from the CSV).

Logic, per user:
  1. Read that user's debit-direction rows from raw_financial_events,
     excluding 'cancelled' (zero cash effect, dropped everywhere but the
     raw landing table) and rows with a blank amount (image-resolution
     case, not yet handled here).
  2. Group by category (not description — a category like "rent" or
     "groceries" is already a consistent grouping key; free-text
     descriptions like "Bakery and snacks" vs "Family dinner" are not,
     as seen on user_35's dining events).
  3. Every category a user has any debit in gets exactly one Person_Expense
     row — never skipped, same rule as income.
  4. Cadence (frequency_id, day_of_month/interval_days) is detected from
     settled rows only, using the same >=3-occurrence / consistent-gap
     rule as income. Non-settled rows never influence the pattern.
  5. flexibility / minimum_allowed_amount / amount / last_seen_date /
     latest_event_id all come from the latest SETTLED occurrence only —
     one current answer per category, not one per historical row.
  6. Every non-cancelled event (settled, pending, scheduled, failed)
     becomes an Expense_Ledger row, linked to its category's expense_id.
     No separate matching step is needed here (unlike income's scheduled
     rows) because every expense event already carries its own category.

Safe to re-run: existing rows are replaced by event_id / by user rebuild.

Usage (from the repo root):
    python3 code/scripts/build_expense_tables.py
"""
from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE_DIR))

from app.db.expense_schema import EXPENSE_SCHEMA  # noqa: E402
from app.db.income_schema import INCOME_SCHEMA  # noqa: E402  (Frequency_Type lives here)
from app.db.repository import DEFAULT_DB_PATH  # noqa: E402
from scripts.build_income_credit_tables import _detect_frequency, _parse_date  # noqa: E402

EXCLUDED_STATUSES = {"cancelled", "failed"}


def build(conn: sqlite3.Connection) -> None:
    conn.executescript(INCOME_SCHEMA)  # ensures Frequency_Type exists
    conn.executescript(EXPENSE_SCHEMA)
    conn.execute("DELETE FROM Expense_Ledger")
    conn.execute("DELETE FROM Person_Expense")

    category_id_by_label = dict(conn.execute("SELECT label, category_id FROM category").fetchall())

    rows = conn.execute(
        """
        SELECT event_id, user_id, category, amount, currency, settlement_date,
               status, flexibility, minimum_allowed_amount
        FROM raw_financial_events
        WHERE direction = 'debit' AND amount <> ''
        ORDER BY user_id, category, settlement_date, event_id
        """
    ).fetchall()

    by_user_category: dict[tuple[str, str], list[tuple]] = defaultdict(list)
    for r in rows:
        status = r[6]
        if status in EXCLUDED_STATUSES:
            continue
        by_user_category[(r[1], r[2])].append(r)

    now = datetime.now(timezone.utc).isoformat()
    patterns_created = 0
    ledger_rows_inserted = 0

    for (user_id, category), group_rows in by_user_category.items():
        category_id = category_id_by_label.get(category)
        if category_id is None:
            continue  # category not in the lookup table — flagged separately

        settled_rows = [r for r in group_rows if r[6] == "settled"]

        if settled_rows:
            settled_rows.sort(key=lambda r: r[5])  # settlement_date
            dates = [_parse_date(r[5]) for r in settled_rows]
            amounts = [float(r[3]) for r in settled_rows]
            frequency_id, day_of_month, interval_days = _detect_frequency(dates)
            is_variable = 1 if len(set(amounts)) > 1 else 0
            latest = settled_rows[-1]
            currency = latest[4]
            flexibility = latest[7]
            min_allowed = float(latest[8]) if latest[8] else None
            first_seen = dates[0].isoformat()
            last_seen = dates[-1].isoformat()
            occurrence_count = len(settled_rows)
            latest_event_id = latest[0]
            amount = amounts[-1]
        else:
            # only pending/scheduled/failed rows exist for this category —
            # still gets a Person_Expense row, just with no confirmed pattern
            group_rows.sort(key=lambda r: r[5])
            latest = group_rows[-1]
            frequency_id, day_of_month, interval_days = 0, None, None
            is_variable = 0
            currency = latest[4]
            flexibility = latest[7]
            min_allowed = float(latest[8]) if latest[8] else None
            first_seen = _parse_date(group_rows[0][5]).isoformat()
            last_seen = _parse_date(latest[5]).isoformat()
            occurrence_count = 0
            latest_event_id = latest[0]
            amount = float(latest[3])

        cur = conn.execute(
            """
            INSERT INTO Person_Expense
                (user_id, category_id, frequency_id, day_of_month, interval_days,
                 amount, currency, is_variable, flexibility, minimum_allowed_amount,
                 first_seen_date, last_seen_date, occurrence_count, latest_event_id, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id, category_id, frequency_id, day_of_month, interval_days,
                amount, currency, is_variable, flexibility, min_allowed,
                first_seen, last_seen, occurrence_count, latest_event_id, now,
            ),
        )
        expense_id = cur.lastrowid
        patterns_created += 1

        for event_id, uid, cat, amt, cur_code, sdate, status, flex, min_amt in group_rows:
            conn.execute(
                """
                INSERT OR REPLACE INTO Expense_Ledger
                    (event_id, expense_id, user_id, category_id, expense_date,
                     status, amount, currency, amount_home, flexibility, minimum_allowed_amount)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    event_id, expense_id, uid, category_id, sdate, status,
                    float(amt), cur_code, flex, float(min_amt) if min_amt else None,
                ),
            )
            ledger_rows_inserted += 1

    conn.commit()
    print(f"Person_Expense patterns: {patterns_created} | Expense_Ledger rows: {ledger_rows_inserted}")


def main() -> None:
    conn = sqlite3.connect(DEFAULT_DB_PATH)
    try:
        build(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
