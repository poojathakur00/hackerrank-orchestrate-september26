"""CLI entry point.

Usage:
    python main.py ingest          # pipeline 1: build/refresh the SQLite cache
"""
from __future__ import annotations

import sys

from app.db.ingest import ingest_all


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "ingest"

    if command == "ingest":
        landed, saved = ingest_all()
        print(f"landed {landed} raw events, saved {saved} profiles")
    else:
        print(f"unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
