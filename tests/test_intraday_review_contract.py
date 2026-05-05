# -*- coding: utf-8 -*-
"""Intraday review contract-only tests."""

import ast
import json
from pathlib import Path

import pytest

from src.intraday_review_contract import (
    IntradayReviewDecision,
    IntradayReviewInput,
    build_intraday_review_input_from_summary,
    validate_intraday_review_decision,
)


def _summary():
    return {
        "report_date": "2026-05-05",
        "technical_basis_date": "2026-05-04",
        "price_policy": "close_only",
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
                },
            }
        ],
    }


def test_can_build_intraday_review_input_from_daily_summary():
    contract = build_intraday_review_input_from_summary(
        _summary(),
        source_summary_path="reports/daily_decision_summary_20260505.json",
    )

    assert contract.report_date == "2026-05-05"
    assert contract.source_summary_path == "reports/daily_decision_summary_20260505.json"
    assert contract.technical_basis_date == "2026-05-04"
    assert contract.price_policy == "close_only"
    assert "last close / pre-open plan" in contract.price_policy_source_note
    assert [item["code"] for item in contract.actionable_items] == ["BHP.AX"]
    assert [item["code"] for item in contract.watch_items] == ["WES.AX"]
    assert [item["code"] for item in contract.blocked_items] == ["NAB.AX"]


def test_intraday_review_input_requires_price_policy():
    payload = _summary()
    payload["price_policy"] = ""

    with pytest.raises(ValueError, match="price_policy"):
        build_intraday_review_input_from_summary(
            payload,
            source_summary_path="reports/daily_decision_summary_20260505.json",
        )


def test_blocked_item_can_only_observe_or_block():
    observe = IntradayReviewDecision(
        code="NAB.AX",
        morning_action="BLOCK",
        review_status="observe_only",
        reason="validation BLOCK from morning report remains unresolved.",
        required_manual_checks=["Do not treat as actionable before manual review."],
    )
    validate_intraday_review_decision(observe, is_blocked_morning_item=True)

    still_valid = IntradayReviewDecision(
        code="NAB.AX",
        morning_action="BLOCK",
        review_status="still_valid",
        reason="not allowed",
        required_manual_checks=[],
    )
    with pytest.raises(ValueError, match="BLOCK morning items"):
        validate_intraday_review_decision(still_valid, is_blocked_morning_item=True)


def test_contract_serializes_and_deserializes_round_trip():
    contract = build_intraday_review_input_from_summary(
        _summary(),
        source_summary_path="reports/daily_decision_summary_20260505.json",
    )
    encoded = json.dumps(contract.to_dict(), ensure_ascii=False)
    decoded = IntradayReviewInput.from_dict(json.loads(encoded))

    assert decoded == contract

    decision = IntradayReviewDecision(
        code="BHP.AX",
        morning_action="OPEN",
        review_status="wait",
        reason="Contract-only sample decision; no realtime data was fetched.",
        required_manual_checks=["Check realtime price manually before any action."],
    )
    decoded_decision = IntradayReviewDecision.from_dict(json.loads(json.dumps(decision.to_dict())))

    assert decoded_decision == decision


def test_contract_module_does_not_import_ai_or_data_sources():
    source = Path("src/intraday_review_contract.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)

    forbidden_markers = ["data_provider", "openai", "anthropic", "broker", "get_realtime_quote"]
    assert all(
        marker not in imported
        for imported in imports
        for marker in forbidden_markers
    )
