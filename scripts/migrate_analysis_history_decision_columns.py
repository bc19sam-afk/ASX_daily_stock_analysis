#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Add deterministic decision columns to analysis_history table (SQLite).

Usage:
  python scripts/migrate_analysis_history_decision_columns.py
  python scripts/migrate_analysis_history_decision_columns.py --db ./data/stock_analysis.db
  python scripts/migrate_analysis_history_decision_columns.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path


COLUMNS = [
    ("alpha_decision", "TEXT"),
    ("final_decision", "TEXT"),
    ("watchlist_state", "TEXT"),
    ("market_regime", "TEXT"),
    ("news_sentiment", "TEXT"),
    ("event_risk", "TEXT"),
    ("sector_tone", "TEXT"),
    ("data_quality_flag", "TEXT"),
]


def resolve_db_path(cli_db: str | None) -> Path:
    if cli_db:
        return Path(cli_db).expanduser().resolve()
    env_path = os.getenv("DATABASE_PATH")
    if env_path:
        return Path(env_path).expanduser().resolve()
    return Path("./data/stock_analysis.db").resolve()


def get_existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    # row format: cid, name, type, notnull, dflt_value, pk
    return {str(r[1]) for r in rows}


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate analysis_history decision columns")
    parser.add_argument("--db", help="SQLite DB file path (default: DATABASE_PATH or ./data/stock_analysis.db)")
    parser.add_argument("--dry-run", action="store_true", help="Only print planned SQL without executing")
    args = parser.parse_args()

    db_path = resolve_db_path(args.db)
    if not db_path.exists():
        print(f"[SKIP] DB not found, nothing to migrate: {db_path}")
        return 0

    conn = sqlite3.connect(str(db_path))
    try:
        existing = get_existing_columns(conn, "analysis_history")
        statements: list[str] = []
        for col, col_type in COLUMNS:
            if col not in existing:
                statements.append(f"ALTER TABLE analysis_history ADD COLUMN {col} {col_type};")

        if not statements:
            print("[OK] No migration needed. All columns already exist.")
            return 0

        print(f"[INFO] DB: {db_path}")
        print("[INFO] Planned SQL:")
        for sql in statements:
            print(f"  {sql}")

        if args.dry_run:
            print("[DRY-RUN] No changes applied.")
            return 0

        with conn:
            for sql in statements:
                conn.execute(sql)
        print(f"[OK] Applied {len(statements)} ALTER TABLE statements.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
