"""SQLite table definitions for the per-user financial state cache.

Once ingestion runs, everything downstream (planner, LLM steps) reads only
from these tables — financial_profiles.csv and financial_events.csv are
never read again.
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS user_profile (
    user_id TEXT PRIMARY KEY,
    home_currency TEXT NOT NULL,
    current_available_balance REAL NOT NULL,
    minimum_balance_to_keep REAL NOT NULL,
    financial_priorities TEXT,
    expense_categories_to_protect TEXT,
    expense_categories_user_is_willing_to_reduce TEXT,
    expense_categories_user_is_willing_to_stop TEXT,
    payment_methods_user_will_consider TEXT,
    max_installment_months INTEGER
);

-- Landing table: financial_events.csv exactly as received (all values kept
-- as text). New events are upserted here first, then user_ledger_events is
-- derived from it.
CREATE TABLE IF NOT EXISTS raw_financial_events (
    event_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    event_type TEXT,
    description TEXT,
    category TEXT,
    direction TEXT,
    amount TEXT,
    currency TEXT,
    event_date TEXT,
    settlement_date TEXT,
    status TEXT,
    linked_event_id TEXT,
    flexibility TEXT,
    minimum_allowed_amount TEXT,
    ingested_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_raw_events_user
    ON raw_financial_events (user_id);
"""
