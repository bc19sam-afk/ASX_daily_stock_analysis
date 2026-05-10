# -*- coding: utf-8 -*-
"""File-based intraday review runner tests."""

import ast
import copy
import json
from pathlib import Path

from scripts.run_intraday_review import main as run_intraday_review_cli
from src.intraday_review import run_intraday_review_file


def _summary_payload():
    return {
        "report_date": "2026-05-06",
        "technical_basis_date": "2026-05-05",
        "price_policy": "close_only",
        "action_counts": {
            "buy": 2,
            "add": 0,
            "reduce": 0,
            "close": 0,
            "hold_watch": 1,
            "blocked": 1,
            "total_actions": 2,
        },
        "actionable_items": [
            {
                "code": "BHP.AX",
                "position_action": "OPEN",
                "target_weight": 0.10,
                "delta_amount": 10000.0,
            },
            {
                "code": "CBA.AX",
                "position_action": "OPEN",
                "target_weight": 0.08,
                "delta_amount": 8000.0,
            },
        ],
        "watch_items": [
            {
                "code": "WES.AX",
                "position_action": "HOLD",
                "target_weight": 0.0,
                "delta_amount": 0.0,
            }
        ],
        "blocked_items": [
            {
                "code": "NAB.AX",
                "reason": "validation BLOCK",
                "final_action_display": {
                    "actionability": "blocked",
                    "can_show_sizing": False,
                    "can_show_plan_points": False,
                },
            }
        ],
    }


def _market_payload():
    return {
        "generated_at": "2026-05-06T10:30:00+10:00",
        "source": "file_input",
        "items": [
            {
                "code": "BHP.AX",
                "last_price": 101.0,
                "previous_close": 100.0,
                "price_timestamp": "2026-05-06T10:25:00+10:00",
                "has_price_sensitive_risk": False,
                "liquidity_warning": False,
                "notes": ["file input"],
            },
            {
                "code": "CBA.AX",
                "last_price": 106.0,
                "previous_close": 100.0,
                "price_timestamp": "2026-05-06T10:25:00+10:00",
                "has_price_sensitive_risk": False,
                "liquidity_warning": False,
                "notes": [],
            },
            {
                "code": "NAB.AX",
                "last_price": 30.2,
                "previous_close": 30.0,
                "price_timestamp": "2026-05-06T10:25:00+10:00",
                "has_price_sensitive_risk": False,
                "liquidity_warning": False,
                "notes": [],
            },
            {
                "code": "EXTRA.AX",
                "last_price": 5.0,
                "previous_close": 5.0,
                "price_timestamp": "2026-05-06T10:25:00+10:00",
                "has_price_sensitive_risk": False,
                "liquidity_warning": False,
                "notes": ["not in summary"],
            },
        ],
    }


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_file_runner_generates_json_and_markdown_without_mutating_summary(tmp_path: Path):
    summary = _summary_payload()
    original_summary = copy.deepcopy(summary)
    summary_path = tmp_path / "daily_decision_summary_20260506.json"
    market_path = tmp_path / "market_input.json"
    output_dir = tmp_path / "reports"
    _write_json(summary_path, summary)
    _write_json(market_path, _market_payload())

    result = run_intraday_review_file(
        summary_path=summary_path,
        market_input_path=market_path,
        output_dir=output_dir,
    )

    json_path = Path(result["json_path"])
    md_path = Path(result["markdown_path"])
    assert json_path.name == "intraday_review_20260506.json"
    assert md_path.name == "intraday_review_20260506.md"
    assert json_path.exists()
    assert md_path.exists()
    assert json.loads(summary_path.read_text(encoding="utf-8")) == original_summary

    output = json.loads(json_path.read_text(encoding="utf-8"))
    assert output["report_date"] == "2026-05-06"
    assert output["source_summary_path"] == str(summary_path)
    assert output["generated_at"] == "2026-05-06T10:30:00+10:00"
    assert output["price_policy"] == "close_only"
    assert output["technical_basis_date"] == "2026-05-05"
    assert output["is_trade_instruction"] is False
    assert output["warnings"] == ["Ignored market input for symbols not present in summary: EXTRA.AX"]

    by_code = {item["code"]: item for item in output["items"]}
    assert by_code["BHP.AX"]["review_status"] == "still_valid"
    assert by_code["BHP.AX"]["morning_action"] == "OPEN"
    assert by_code["BHP.AX"]["price_deviation_pct"] == 1.0
    assert by_code["BHP.AX"]["source"] == "file_input"
    assert by_code["BHP.AX"]["is_trade_instruction"] is False
    assert by_code["CBA.AX"]["review_status"] == "cancel"
    assert by_code["NAB.AX"]["review_status"] in {"observe_only", "block"}
    assert by_code["NAB.AX"]["review_status"] != "still_valid"
    assert by_code["WES.AX"]["review_status"] == "observe_only"
    assert "missing_input" in by_code["WES.AX"]["reason"]
    assert "EXTRA.AX" not in by_code
    assert all(item["is_trade_instruction"] is False for item in output["items"])
    assert all("required_checks" in item for item in output["items"])

    markdown = md_path.read_text(encoding="utf-8")
    assert "这是盘中复核结果" in markdown
    assert "数据来自输入文件" in markdown
    assert "不自动下单" in markdown
    assert "执行前确认价格、公告、流动性" in markdown
    assert "BHP.AX" in markdown
    assert "NAB.AX" in markdown
    assert "## 人工复核清单" in markdown
    assert "以下检查必须由人工完成；盘中复核不自动下单，也不连接券商。" in markdown
    assert "### BHP.AX" in markdown
    assert "### NAB.AX" in markdown
    assert "人工复核当前价格、盘口流动性和重大公告；本输出不是交易指令。" in markdown
    assert "确认 morning daily_decision_summary 的 close_only / 昨收计划口径仍适用。" in markdown
    assert "required_checks" not in markdown


def test_file_runner_cli_uses_local_files_only(tmp_path: Path):
    summary_path = tmp_path / "daily_decision_summary_20260506.json"
    market_path = tmp_path / "market_input.json"
    output_dir = tmp_path / "reports"
    _write_json(summary_path, _summary_payload())
    _write_json(market_path, _market_payload())

    exit_code = run_intraday_review_cli(
        [
            "--summary",
            str(summary_path),
            "--market-input",
            str(market_path),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    assert (output_dir / "intraday_review_20260506.json").exists()
    assert (output_dir / "intraday_review_20260506.md").exists()


def test_runner_modules_do_not_import_ai_data_provider_or_broker_modules():
    forbidden_markers = ["data_provider", "openai", "anthropic", "broker", "yfinance", "get_realtime_quote"]
    for path in [Path("src/intraday_review.py"), Path("scripts/run_intraday_review.py")]:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)

        assert all(
            marker not in imported
            for imported in imports
            for marker in forbidden_markers
        )
