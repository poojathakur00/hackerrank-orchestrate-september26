"""One-time population script: derive Person_Income, Income_Ledger, and
Credit from raw_financial_events (never from the CSV).

Logic, per user:
  1. Read that user's credit-direction rows from raw_financial_events.
  2. Split: category == 'salary' -> income path. Everything else -> Credit
     (one-off, never recurring; category becomes credit_type).
  3. Income path, settled rows only, grouped by source_label (the raw
     `description` column — this is how two salaries for one user are told
     apart, e.g. user_13's "Primary household salary" vs "Second household
     income"):
       - sort by settlement_date, compute gaps between consecutive dates.
       - >=3 occurrences AND consistent gaps -> frequency_id set
         (monthly/weekly/daily/biweekly). Otherwise frequency_id = 0.
         No source is skipped either way — every group gets a Person_Income
         row.
       - is_variable = amounts aren't all equal.
       - amount/latest_event_id/last_seen_date come from the latest SETTLED
         occurrence only (scheduled rows don't redefine the pattern).
  4. Every settled income event becomes an Income_Ledger row.
  5. Scheduled salary rows (generic description, no source of their own) are
     matched to an existing pattern for that user by nearest day-of-month +
     closest amount; unmatched -> income_id NULL. Always inserted.
  6. Non-salary credits (shopping/work_expense/investment/windfall) go into
     Credit as-is, one row per event, no pattern.

Safe to re-run: existing rows are replaced by event_id / by user rebuild.

Usage (from the repo root):
    python3 code/scripts/build_income_credit_tables.py
"""
from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE_DIR))

from app.db.income_schema import INCOME_SCHEMA  # noqa: E402
from app.db.repository import DEFAULT_DB_PATH  # noqa: E402

MIN_OCCURRENCES = 3
DAILY_GAP = (1, 1)
WEEKLY_GAP = (6, 8)
BIWEEKLY_GAP = (12, 16)
MONTHLY_GAP = (27, 32)

SALARY_CATEGORY = "salary"


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def _detect_frequency(dates: list[date]) -> tuple[int, int | None, int | None]:
    """Returns (frequency_id, day_of_month, interval_days) for a sorted date list."""
    if len(dates) < MIN_OCCURRENCES:
        return 0, None, None

    gaps = [(b - a).days for a, b in zip(dates, dates[1:])]

    if all(DAILY_GAP[0] <= g <= DAILY_GAP[1] for g in gaps):
        return 3, None, 1
    if all(WEEKLY_GAP[0] <= g <= WEEKLY_GAP[1] for g in gaps):
        return 2, None, 7
    if all(BIWEEKLY_GAP[0] <= g <= BIWEEKLY_GAP[1] for g in gaps):
        return 4, None, 14
    if all(MONTHLY_GAP[0] <= g <= MONTHLY_GAP[1] for g in gaps):
        days = {d.day for d in dates}
        if len(days) == 1:
            return 1, dates[-1].day, None
    return 0, None, None


def build(conn: sqlite3.Connection) -> None:
    conn.executescript(INCOME_SCHEMA)
    conn.execute("DELETE FROM Income_Ledger")
    conn.execute("DELETE FROM Credit")
    conn.execute("DELETE FROM Person_Income")

    rows = conn.execute(
        """
        SELECT event_id, user_id, description, category, amount, currency,
               settlement_date, status
        FROM raw_financial_events
        WHERE direction = 'credit' AND amount <> ''
        ORDER BY user_id, settlement_date, event_id
        """
    ).fetchall()

    by_user: dict[str, list[tuple]] = defaultdict(list)
    for r in rows:
        by_user[r[1]].append(r)

    now = datetime.now(timezone.utc).isoformat()
    income_rows_inserted = 0
    credit_rows_inserted = 0
    patterns_created = 0

    for user_id, user_rows in by_user.items():
        salary_rows = [r for r in user_rows if r[3] == SALARY_CATEGORY]
        other_credit_rows = [r for r in user_rows if r[3] != SALARY_CATEGORY]

        # --- non-salary credits: no pattern, straight insert ---
        for event_id, uid, description, category, amount, currency, sdate, status in other_credit_rows:
            conn.execute(
                """
                INSERT OR REPLACE INTO Credit
                    (event_id, user_id, credit_type, income_id, linked_event_id,
                     credit_date, status, amount, currency, amount_home)
                VALUES (?, ?, ?, NULL, NULL, ?, ?, ?, ?, NULL)
                """,
                (event_id, uid, category, sdate, status, float(amount), currency),
            )
            credit_rows_inserted += 1

        # --- salary: group settled rows by source_label (description) ---
        settled_by_source: dict[str, list[tuple]] = defaultdict(list)
        scheduled_rows = []
        for row in salary_rows:
            event_id, uid, description, category, amount, currency, sdate, status = row
            if status == "settled":
                settled_by_source[description].append(row)
            elif status == "scheduled":
                scheduled_rows.append(row)
            else:
                # pending/cancelled/failed salary rows: keep as unattached
                # ledger evidence, no pattern impact
                conn.execute(
                    """
                    INSERT OR REPLACE INTO Income_Ledger
                        (event_id, income_id, user_id, income_type, source_label,
                         income_date, status, amount, currency, amount_home)
                    VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, NULL)
                    """,
                    (event_id, uid, category, description, sdate, status, float(amount), currency),
                )
                income_rows_inserted += 1

        source_to_income_id: dict[str, int] = {}
        pattern_meta: dict[int, dict] = {}

        for source_label, source_rows in settled_by_source.items():
            source_rows.sort(key=lambda r: r[6])  # settlement_date
            dates = [_parse_date(r[6]) for r in source_rows]
            amounts = [float(r[4]) for r in source_rows]
            currency = source_rows[0][5]

            frequency_id, day_of_month, interval_days = _detect_frequency(dates)
            is_variable = 1 if len(set(amounts)) > 1 else 0
            latest = source_rows[-1]

            cur = conn.execute(
                """
                INSERT INTO Person_Income
                    (user_id, frequency_id, day_of_month, interval_days, amount,
                     currency, is_variable, effective_from, first_seen_date,
                     last_seen_date, occurrence_count, latest_event_id, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id, frequency_id, day_of_month, interval_days, amounts[-1],
                    currency, is_variable, dates[0].isoformat(), dates[0].isoformat(),
                    dates[-1].isoformat(), len(source_rows), latest[0], now,
                ),
            )
            income_id = cur.lastrowid
            patterns_created += 1
            source_to_income_id[source_label] = income_id
            pattern_meta[income_id] = {
                "day_of_month": day_of_month,
                "amount": amounts[-1],
                "frequency_id": frequency_id,
            }

            for event_id, uid, description, category, amount, cur_, sdate, status in source_rows:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO Income_Ledger
                        (event_id, income_id, user_id, income_type, source_label,
                         income_date, status, amount, currency, amount_home)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                    """,
                    (event_id, income_id, uid, category, description, sdate, status, float(amount), cur_),
                )
                income_rows_inserted += 1

        # --- scheduled rows: match to nearest pattern by day-of-month + amount ---
        for event_id, uid, description, category, amount, currency, sdate, status in scheduled_rows:
            sched_amount = float(amount)
            sched_day = _parse_date(sdate).day
            best_income_id = None
            best_score = None
            for income_id, meta in pattern_meta.items():
                if meta["day_of_month"] is None:
                    continue
                day_diff = abs(meta["day_of_month"] - sched_day)
                amount_diff = abs(meta["amount"] - sched_amount) / max(meta["amount"], 1)
                if day_diff <= 2 and amount_diff <= 0.05:
                    score = day_diff + amount_diff
                    if best_score is None or score < best_score:
                        best_score = score
                        best_income_id = income_id

            conn.execute(
                """
                INSERT OR REPLACE INTO Income_Ledger
                    (event_id, income_id, user_id, income_type, source_label,
                     income_date, status, amount, currency, amount_home)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (event_id, best_income_id, user_id, category, description, sdate, status, sched_amount, currency),
            )
            income_rows_inserted += 1

    conn.commit()
    print(
        f"Person_Income patterns: {patterns_created} | "
        f"Income_Ledger rows: {income_rows_inserted} | "
        f"Credit rows: {credit_rows_inserted}"
    )


def main() -> None:
    conn = sqlite3.connect(DEFAULT_DB_PATH)
    try:
        build(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
