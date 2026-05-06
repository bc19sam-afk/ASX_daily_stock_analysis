# -*- coding: utf-8 -*-
"""Run a file-based offline intraday review."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.intraday_review import run_intraday_review_file


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run offline intraday review from local files.")
    parser.add_argument("--summary", required=True, help="Path to daily_decision_summary JSON.")
    parser.add_argument("--market-input", required=True, help="Path to offline market_input JSON.")
    parser.add_argument("--output-dir", required=True, help="Directory for intraday review outputs.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_intraday_review_file(
        summary_path=args.summary,
        market_input_path=args.market_input,
        output_dir=args.output_dir,
    )
    print(f"Wrote JSON: {result['json_path']}")
    print(f"Wrote Markdown: {result['markdown_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
