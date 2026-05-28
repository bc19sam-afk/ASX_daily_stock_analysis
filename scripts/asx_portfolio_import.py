# -*- coding: utf-8 -*-
"""Preview or apply ASX portfolio ledger CSV imports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.services.asx_portfolio_import_service import AsxPortfolioImportService
from src.storage import DatabaseManager


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Preview or apply an ASX portfolio CSV import")
    parser.add_argument("--csv", dest="csv_path", required=True, help="Path to the CSV file to import")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the CSV rows to the local portfolio ledger instead of previewing them",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    service = AsxPortfolioImportService(DatabaseManager.get_instance())
    csv_path = Path(args.csv_path)
    result = service.apply_csv(csv_path) if args.apply else service.preview_csv(csv_path)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if args.apply and result.get("status") != "applied":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
