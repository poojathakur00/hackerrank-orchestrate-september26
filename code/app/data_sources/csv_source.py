"""Data layer: load dataset/*.csv and index them for lookup by key.

This module only loads and joins raw records. It does not interpret
financial semantics (recurrence, settlement, safety checks, etc.) —
that logic belongs in `app.ledger`. It also does not touch the SQLite
cache — that's `app.db`. This module is the *only* place raw CSVs are
read; everything downstream reads from the SQLite cache instead.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

DATASET_DIR = Path(__file__).resolve().parent.parent.parent.parent / "dataset"


def _read_csv(name: str) -> list[dict]:
    path = DATASET_DIR / name
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _index_by(rows: list[dict], key: str) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    for row in rows:
        index.setdefault(row[key], []).append(row)
    return index


def _index_unique_by(rows: list[dict], key: str) -> dict[str, dict]:
    return {row[key]: row for row in rows}


@dataclass
class Dataset:
    profiles: list[dict]
    events: list[dict]
    exchange_rates: list[dict]
    requests: list[dict]
    payment_options: list[dict]
    messages: list[dict]
    images: list[dict]

    profile_by_user: dict[str, dict] = field(init=False)
    events_by_user: dict[str, list[dict]] = field(init=False)
    request_by_id: dict[str, dict] = field(init=False)
    payment_options_by_request: dict[str, list[dict]] = field(init=False)
    messages_by_user: dict[str, list[dict]] = field(init=False)
    messages_by_request: dict[str, list[dict]] = field(init=False)
    messages_by_event: dict[str, list[dict]] = field(init=False)
    images_by_event: dict[str, dict] = field(init=False)
    rate_by_key: dict[tuple[str, str, str], float] = field(init=False)

    def __post_init__(self) -> None:
        self.profile_by_user = _index_unique_by(self.profiles, "user_id")
        self.events_by_user = _index_by(self.events, "user_id")
        self.request_by_id = _index_unique_by(self.requests, "request_id")
        self.payment_options_by_request = _index_by(self.payment_options, "request_id")

        self.messages_by_user = _index_by(self.messages, "user_id")
        self.messages_by_request = {}
        self.messages_by_event = {}
        for m in self.messages:
            if m.get("request_id"):
                self.messages_by_request.setdefault(m["request_id"], []).append(m)
            if m.get("related_event_id"):
                self.messages_by_event.setdefault(m["related_event_id"], []).append(m)

        # images.csv is keyed 1:1 by related_event_id for this dataset
        self.images_by_event = {
            img["related_event_id"]: img for img in self.images if img.get("related_event_id")
        }

        self.rate_by_key = {}
        for r in self.exchange_rates:
            key = (r["rate_date"], r["from_currency"], r["to_currency"])
            self.rate_by_key[key] = float(r["rate"])

    def image_path(self, image_id: str) -> Path:
        return DATASET_DIR / "media" / "images" / f"{image_id}.png"


def load_dataset() -> Dataset:
    return Dataset(
        profiles=_read_csv("financial_profiles.csv"),
        events=_read_csv("financial_events.csv"),
        exchange_rates=_read_csv("exchange_rates.csv"),
        requests=_read_csv("requests.csv"),
        payment_options=_read_csv("request_payment_options.csv"),
        messages=_read_csv("messages.csv"),
        images=_read_csv("images.csv"),
    )


@dataclass
class RequestContext:
    """Everything request-scoped (not part of the per-user ledger cache)
    needed to evaluate one request: the request row, its payment options,
    and the messages/images relevant to it."""

    request: dict
    profile: dict
    payment_options: list[dict]
    messages: list[dict]  # union of user-level and request-level messages
    images: list[dict]  # images linked to this user's events


def build_request_context(ds: Dataset, request_id: str) -> RequestContext:
    request = ds.request_by_id[request_id]
    user_id = request["user_id"]
    profile = ds.profile_by_user[user_id]

    request_messages = ds.messages_by_request.get(request_id, [])
    user_messages = ds.messages_by_user.get(user_id, [])
    # de-dupe while preserving order (a message could match both)
    seen_ids = set()
    messages = []
    for m in request_messages + user_messages:
        mid = m.get("message_id", id(m))
        if mid not in seen_ids:
            seen_ids.add(mid)
            messages.append(m)

    user_event_ids = {e["event_id"] for e in ds.events_by_user.get(user_id, [])}
    images = [img for img in ds.images if img.get("related_event_id") in user_event_ids]

    return RequestContext(
        request=request,
        profile=profile,
        payment_options=ds.payment_options_by_request.get(request_id, []),
        messages=messages,
        images=images,
    )
