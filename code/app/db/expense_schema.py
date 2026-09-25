"""Schema for the expense side of the ledger.

category is a new lookup table (debit categories only, for now) — Person_Expense
groups by category rather than description, unlike Person_Income, since an
expense category (rent, groceries) is already a consistent grouping key —
free-text descriptions ("Bakery and snacks" vs "Family dinner") are not.

Person_Expense holds one row per recurring-or-not expense category per user
(pattern only). Expense_Ledger holds one row per actual expense event,
always traceable back to raw_financial_events by event_id. Cancelled events
are never inserted into either table — they have zero cash effect and carry
no decision-relevant information.

flexibility and minimum_allowed_amount live on Person_Expense as a single
current value (from the latest settled occurrence), not per-ledger-row —
a spending-change decision needs one answer per category, not a different
answer depending on which past instance happens to get picked.
"""

EXPENSE_SCHEMA = """
CREATE TABLE IF NOT EXISTS category (
    category_id INTEGER PRIMARY KEY,
    label TEXT NOT NULL UNIQUE
);

INSERT OR IGNORE INTO category (category_id, label) VALUES
    (1, 'rent'),
    (2, 'utilities'),
    (3, 'groceries'),
    (4, 'transport'),
    (5, 'dining'),
    (6, 'education'),
    (7, 'debt_repayment'),
    (8, 'healthcare'),
    (9, 'insurance'),
    (10, 'housing'),
    (11, 'family_support'),
    (12, 'entertainment'),
    (13, 'gym'),
    (14, 'streaming'),
    (15, 'music_subscription'),
    (16, 'cloud_storage'),
    (17, 'delivery_membership'),
    (18, 'shopping'),
    (19, 'investment'),
    (20, 'work_expense');

CREATE TABLE IF NOT EXISTS Person_Expense (
    expense_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    category_id INTEGER NOT NULL REFERENCES category(category_id),
    frequency_id INTEGER NOT NULL DEFAULT 0 REFERENCES Frequency_Type(frequency_id),
    day_of_month INTEGER,
    interval_days INTEGER,
    amount REAL,
    currency TEXT,
    is_variable INTEGER NOT NULL DEFAULT 0,
    flexibility TEXT NOT NULL,
    minimum_allowed_amount REAL,
    first_seen_date TEXT,
    last_seen_date TEXT,
    occurrence_count INTEGER NOT NULL DEFAULT 0,
    latest_event_id TEXT,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_person_expense_user ON Person_Expense (user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_person_expense_user_category ON Person_Expense (user_id, category_id);

CREATE TABLE IF NOT EXISTS Expense_Ledger (
    event_id TEXT PRIMARY KEY,
    expense_id INTEGER REFERENCES Person_Expense(expense_id),
    user_id TEXT NOT NULL,
    category_id INTEGER,
    expense_date TEXT NOT NULL,
    status TEXT NOT NULL,
    amount REAL,
    currency TEXT,
    amount_home REAL,
    flexibility TEXT,
    minimum_allowed_amount REAL
);

CREATE INDEX IF NOT EXISTS idx_expense_ledger_user ON Expense_Ledger (user_id);
CREATE INDEX IF NOT EXISTS idx_expense_ledger_expense ON Expense_Ledger (expense_id);
"""
