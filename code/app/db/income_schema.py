"""Schema for the income/credit side of the ledger.

Person_Income holds one row per recurring income source per user (pattern
only — no per-payment amounts). Income_Ledger holds one row per actual
income event (settled or scheduled), always linked back to raw_financial_events
by event_id. Credit holds one-off, non-salary credit events (refunds,
investment sales, windfalls) — never recurring.
"""

INCOME_SCHEMA = """
CREATE TABLE IF NOT EXISTS Frequency_Type (
    frequency_id INTEGER PRIMARY KEY,
    label TEXT NOT NULL
);

INSERT OR IGNORE INTO Frequency_Type (frequency_id, label) VALUES
    (0, 'none'),
    (1, 'monthly'),
    (2, 'weekly'),
    (3, 'daily'),
    (4, 'biweekly');

CREATE TABLE IF NOT EXISTS Person_Income (
    income_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    frequency_id INTEGER NOT NULL DEFAULT 0 REFERENCES Frequency_Type(frequency_id),
    day_of_month INTEGER,
    interval_days INTEGER,
    amount REAL,
    currency TEXT,
    is_variable INTEGER NOT NULL DEFAULT 0,
    effective_from TEXT,
    first_seen_date TEXT,
    last_seen_date TEXT,
    occurrence_count INTEGER NOT NULL DEFAULT 0,
    latest_event_id TEXT,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_person_income_user ON Person_Income (user_id);

CREATE TABLE IF NOT EXISTS Income_Ledger (
    event_id TEXT PRIMARY KEY,
    income_id INTEGER REFERENCES Person_Income(income_id),
    user_id TEXT NOT NULL,
    income_type TEXT,
    source_label TEXT,
    income_date TEXT NOT NULL,
    status TEXT NOT NULL,
    amount REAL,
    currency TEXT,
    amount_home REAL
);

CREATE INDEX IF NOT EXISTS idx_income_ledger_user ON Income_Ledger (user_id);
CREATE INDEX IF NOT EXISTS idx_income_ledger_income ON Income_Ledger (income_id);

CREATE TABLE IF NOT EXISTS Credit (
    event_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    credit_type TEXT,
    income_id INTEGER REFERENCES Person_Income(income_id),
    linked_event_id TEXT,
    credit_date TEXT NOT NULL,
    status TEXT NOT NULL,
    amount REAL,
    currency TEXT,
    amount_home REAL
);

CREATE INDEX IF NOT EXISTS idx_credit_user ON Credit (user_id);
"""
