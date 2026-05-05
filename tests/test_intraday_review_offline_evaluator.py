# -*- coding: utf-8 -*-
"""Offline intraday review evaluator tests."""

import ast
import copy
from pathlib import Path

from src.intraday_review import evaluate_intraday_review_offline
from src.intraday_review_contract import (
    IntradayReviewMarketInput,
    build_intraday_review_input_from_summary,
)


def _summary():
    return {
        "report_date": "2026-05-05",
        "technical_basis_date": "2026-05-04",
        "price_policy": "close_only",
        "action_counts": {
            "buy": 1,
            "add": 0,
            "reduce": 0,
            "close": 0,
            "hold_watch": 1,
            "blocked": 1,
            "total_actions": 1,
        },
        "actionable_items": [
            {
                "code": "BHP.AX",
                "position_action": "OPEN",
                "target_weight": 0.10,
                "delta_amount": 10000.0,
            }
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
                "reason": "mixed_price_basis",
                "final_action_display": {
                    "actionability": "blocked",
                    "can_show_sizing": False,
                    "can_show_plan_points": False,
                },
            }
        ],
    }


def _contract(summary=None):
    return build_intraday_review_input_from_summary(
        summary or _summary(),
        source_summary_path="reports/daily_decision_summary_20260505.json",
    )


def _market(code, **overrides):
    values = dict(
        code=code,
        last_price=101.0,
        previous_close=100.0,
        price_timestamp="2026-05-05T11:00:00+10:00",
        has_price_sensitive_risk=False,
        liquidity_warning=False,
        notes=[],
    )
    values.update(overrides)
    return IntradayReviewMarketInput(**values)


def test_actionable_small_price_move_is_still_valid_for_manual_review():
    evaluations = evaluate_intraday_review_offline(
        _contract(),
        market_inputs={"BHP.AX": _market("BHP.AX", last_price=101.0, previous_close=100.0)},
    )

    evaluation = evaluations["BHP.AX"]
    assert evaluation.review_status == "still_valid"
    assert evaluation.morning_action == "OPEN"
    assert evaluation.price_deviation_pct == 1.0
    assert evaluation.source == "offline_input"
    assert evaluation.is_trade_instruction is False
    assert any("人工复核" in item or "manual" in item.lower() for item in evaluation.required_manual_checks)
    assert "不是交易指令" in evaluation.reason


def test_actionable_waits_when_price_move_exceeds_wait_threshold():
    evaluations = evaluate_intraday_review_offline(
        _contract(),
        market_inputs={"BHP.AX": _market("BHP.AX", last_price=103.0, previous_close=100.0)},
        max_price_deviation_pct=2.0,
        cancel_deviation_pct=5.0,
    )

    assert evaluations["BHP.AX"].review_status == "wait"
    assert evaluations["BHP.AX"].price_deviation_pct == 3.0


def test_actionable_cancels_when_price_move_exceeds_cancel_threshold():
    evaluations = evaluate_intraday_review_offline(
        _contract(),
        market_inputs={"BHP.AX": _market("BHP.AX", last_price=106.0, previous_close=100.0)},
        max_price_deviation_pct=2.0,
        cancel_deviation_pct=5.0,
    )

    assert evaluations["BHP.AX"].review_status == "cancel"
    assert evaluations["BHP.AX"].price_deviation_pct == 6.0


def test_blocked_morning_item_never_becomes_still_valid():
    evaluations = evaluate_intraday_review_offline(
        _contract(),
        market_inputs={"NAB.AX": _market("NAB.AX", last_price=100.5, previous_close=100.0)},
    )

    evaluation = evaluations["NAB.AX"]
    assert evaluation.review_status in {"observe_only", "block"}
    assert evaluation.review_status != "still_valid"
    assert evaluation.is_trade_instruction is False


def test_missing_last_price_or_previous_close_degrades_without_guessing():
    evaluations = evaluate_intraday_review_offline(
        _contract(),
        market_inputs={
            "BHP.AX": _market("BHP.AX", last_price=None, previous_close=100.0),
            "WES.AX": _market("WES.AX", last_price=10.0, previous_close=None),
        },
    )

    assert evaluations["BHP.AX"].review_status in {"observe_only", "block"}
    assert evaluations["BHP.AX"].price_deviation_pct is None
    assert evaluations["WES.AX"].review_status in {"observe_only", "block"}
    assert evaluations["WES.AX"].price_deviation_pct is None


def test_price_sensitive_risk_blocks_even_actionable_items():
    evaluations = evaluate_intraday_review_offline(
        _contract(),
        market_inputs={
            "BHP.AX": _market("BHP.AX", has_price_sensitive_risk=True),
        },
    )

    assert evaluations["BHP.AX"].review_status == "block"
    assert evaluations["BHP.AX"].is_trade_instruction is False


def test_liquidity_warning_waits_or_observes_only():
    evaluations = evaluate_intraday_review_offline(
        _contract(),
        market_inputs={
            "BHP.AX": _market("BHP.AX", liquidity_warning=True),
        },
    )

    assert evaluations["BHP.AX"].review_status in {"wait", "observe_only"}


def test_evaluator_does_not_mutate_summary_or_action_counts():
    summary = _summary()
    original = copy.deepcopy(summary)

    evaluate_intraday_review_offline(
        _contract(summary),
        market_inputs={"BHP.AX": _market("BHP.AX")},
    )

    assert summary == original
    assert summary["action_counts"] == original["action_counts"]


def test_evaluator_module_does_not_import_ai_data_provider_or_broker_modules():
    source = Path("src/intraday_review.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)

    forbidden_markers = ["data_provider", "openai", "anthropic", "broker", "yfinance", "get_realtime_quote"]
    assert all(
        marker not in imported
        for imported in imports
        for marker in forbidden_markers
    )
