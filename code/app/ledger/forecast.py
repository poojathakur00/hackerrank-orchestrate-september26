"""Deterministic ledger engine: turns one user's raw events into an enriched,
request-independent event list, and turns that list + a start date into a
90-day balance forecast.

No LLM calls here. This module only does arithmetic and rule application,
so results are reproducible and auditable. It never reads requests.csv —
that's request-scoped and handled by the planner.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

FORECAST_DAYS = 90

# Bump whenever filtering/projection rules change so cached ledgers rebuild.
LEDGER_RULES_VERSION = "1"

# Events in these statuses never move the balance forecast.
EXCLUDED_STATUSES = {"cancelled", "failed", "unrealized"}

# direction=credit rows we don't trust until they settle (bonuses, refunds,
# commissions, lottery, etc. show up as pending credits in this dataset).
UNSAFE_PENDING_CREDIT = {"pending"}


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def to_home_currency(
    rate_by_key: dict[tuple[str, str, str], float],
    amount: float,
    currency: str,
    home_currency: str,
    on_date: str,
) -> float:
    """Convert amount -> home_currency using the fixed dated rate table."""
    if currency == home_currency:
        return amount
    key = (on_date, currency, home_currency)
    if key in rate_by_key:
        return amount * rate_by_key[key]
    # no rate for this exact date/pair: treat as unconvertible, ignore in forecast
    return 0.0


@dataclass
class LedgerEvent:
    event_id: str
    event_date: date
    amount: float  # signed: +credit, -debit, already in home currency
    category: str
    flexibility: str
    minimum_allowed_amount: float | None = None
    is_projection: bool = False


def usable_events(
    raw_events: list[dict],
    home_currency: str,
    rate_by_key: dict[tuple[str, str, str], float],
) -> list[LedgerEvent]:
    """Filter + sign + convert currency for one user's raw event rows.

    Keeps settled/pending/scheduled debits (money we must expect to pay)
    but only settled/scheduled credits (money we can rely on), per the
    "ignore pending credits" rule.
    """
    out: list[LedgerEvent] = []
    for e in raw_events:
        if e["status"] in EXCLUDED_STATUSES:
            continue
        if e["direction"] == "non_cash":
            continue
        if not e.get("amount"):
            continue  # blank amounts are resolved via images at request time
        if e["direction"] == "credit" and e["status"] in UNSAFE_PENDING_CREDIT:
            continue

        amount = float(e["amount"])
        amount = to_home_currency(rate_by_key, amount, e["currency"], home_currency, e["settlement_date"])
        signed = amount if e["direction"] == "credit" else -amount

        min_allowed = e.get("minimum_allowed_amount") or None
        out.append(
            LedgerEvent(
                event_id=e["event_id"],
                event_date=_parse_date(e["settlement_date"]),
                amount=signed,
                category=e["category"],
                flexibility=e["flexibility"],
                minimum_allowed_amount=float(min_allowed) if min_allowed else None,
            )
        )
    return out


def detect_recurring(events: list[LedgerEvent]) -> list[LedgerEvent]:
    """Find repeating (category, sign) patterns and project the next
    occurrence forward so the forecast accounts for future rent/salary/etc.

    Heuristic: group by category+sign; if 2+ occurrences with a roughly
    consistent day-interval exist, project one more occurrence at the last
    interval, tagged as a projection (not a confirmed event).
    """
    groups: dict[tuple[str, bool], list[LedgerEvent]] = defaultdict(list)
    for ev in events:
        groups[(ev.category, ev.amount >= 0)].append(ev)

    projections: list[LedgerEvent] = []
    for (_, _), group in groups.items():
        if len(group) < 2:
            continue
        group.sort(key=lambda e: e.event_date)
        last, prev = group[-1], group[-2]
        interval = (last.event_date - prev.event_date).days
        if interval <= 0:
            continue
        next_date = last.event_date + timedelta(days=interval)
        projections.append(
            LedgerEvent(
                event_id=f"{last.event_id}_projected",
                event_date=next_date,
                amount=last.amount,
                category=last.category,
                flexibility=last.flexibility,
                minimum_allowed_amount=last.minimum_allowed_amount,
                is_projection=True,
            )
        )
    return projections


def build_base_corpus(
    raw_events: list[dict],
    home_currency: str,
    rate_by_key: dict[tuple[str, str, str], float],
) -> list[LedgerEvent]:
    """The full, request-independent enriched event list for one user:
    real usable events + one projected occurrence per recurring pattern.
    This is exactly what gets cached in the `user_ledger_events` DB table.
    """
    events = usable_events(raw_events, home_currency, rate_by_key)
    events += detect_recurring(events)
    return events


def build_forecast(
    base_corpus: list[LedgerEvent], current_balance: float, start_date: date
) -> list[tuple[date, float]]:
    """Return a (date, running_balance) timeline for FORECAST_DAYS starting
    at `start_date`, applying every base-corpus event that falls in that
    window. Reads only the cached base corpus — never touches raw CSVs.
    """
    end_date = start_date + timedelta(days=FORECAST_DAYS)

    window = [e for e in base_corpus if start_date <= e.event_date <= end_date]
    window.sort(key=lambda e: e.event_date)

    timeline: list[tuple[date, float]] = [(start_date, current_balance)]
    running = current_balance
    for ev in window:
        running += ev.amount
        timeline.append((ev.event_date, running))
    return timeline


def min_balance_after(timeline: list[tuple[date, float]], on_or_after: date) -> float:
    """Worst (lowest) balance reached on or after a given date."""
    relevant = [b for d, b in timeline if d >= on_or_after]
    return min(relevant) if relevant else timeline[-1][1]
