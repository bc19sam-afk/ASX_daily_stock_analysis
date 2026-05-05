# -*- coding: utf-8 -*-
"""Risk sizing cap candidate calculation stays detached from daily actions."""

from types import SimpleNamespace
from datetime import datetime
from zoneinfo import ZoneInfo

from src.analyzer import AnalysisResult
from src.core.risk_sizing import (
    RiskSizingSettings,
    build_risk_sizing_cap_candidate,
    risk_sizing_settings_from_config,
)
from src.daily_decision_summary import build_daily_decision_summary


def _settings(**overrides) -> RiskSizingSettings:
    values = dict(
        max_single_position_weight=0.35,
        max_trade_risk_pct=0.005,
        atr_stop_multiplier=1.5,
        min_order_notional=20.0,
        max_daily_turnover_pct=0.20,
        mode="enabled",
    )
    values.update(overrides)
    return RiskSizingSettings(**values)


def _result(**overrides) -> AnalysisResult:
    values = dict(
        code="BHP.AX",
        name="BHP",
        sentiment_score=75,
        trend_prediction="震荡上行",
        operation_advice="按确定性动作观察",
        final_decision="BUY",
        position_action="OPEN",
        current_weight=0.0,
        target_weight=0.10,
        delta_amount=5000.0,
        execution_price_source="close_only",
        market_snapshot={"date": "2026-05-04", "close": "100.00", "source": "yfinance"},
        stop_loss=95.0,
        action_reason="deterministic action",
    )
    values.update(overrides)
    return AnalysisResult(**values)


def _action(result: AnalysisResult) -> dict:
    return {
        "position_action": result.position_action,
        "target_weight": result.target_weight,
        "delta_amount": result.delta_amount,
    }


def test_settings_accept_only_shadow_or_enabled_modes():
    assert risk_sizing_settings_from_config(SimpleNamespace(risk_sizing_mode="enabled")).mode == "enabled"
    assert risk_sizing_settings_from_config(SimpleNamespace(risk_sizing_mode="shadow")).mode == "shadow"
    assert risk_sizing_settings_from_config(SimpleNamespace(risk_sizing_mode="surprise")).mode == "shadow"
    assert risk_sizing_settings_from_config(SimpleNamespace()).mode == "shadow"


def test_cap_candidate_calculates_risk_budget_weight_without_side_effects():
    result = _result(target_weight=0.20, delta_amount=20000.0, stop_loss=95.0)

    candidate = build_risk_sizing_cap_candidate(
        result=result,
        action_model=_action(result),
        overview={"total_value": 100000.0, "cash": 50000.0},
        settings=_settings(),
        is_blocked=False,
        is_actionable_context=True,
    )

    assert candidate["mode"] == "enabled"
    assert candidate["current_target_weight"] == 0.20
    assert candidate["risk_budget_amount"] == 500.0
    assert candidate["stop_distance"] == 5.0
    assert candidate["stop_distance_source"] == "stop_loss"
    assert candidate["capped_target_weight"] == 0.10
    assert candidate["cap_applied"] is True
    assert candidate["would_change_target"] is True
    assert "risk_budget" in candidate["constraints_applied"]
    assert result.target_weight == 0.20
    assert result.delta_amount == 20000.0
    assert result.position_action == "OPEN"


def test_shadow_mode_cap_candidate_is_not_calculated():
    result = _result(target_weight=0.20, delta_amount=20000.0, stop_loss=95.0)

    candidate = build_risk_sizing_cap_candidate(
        result=result,
        action_model=_action(result),
        overview={"total_value": 100000.0, "cash": 50000.0},
        settings=_settings(mode="shadow"),
        is_blocked=False,
        is_actionable_context=True,
    )

    assert candidate["mode"] == "shadow"
    assert candidate["capped_target_weight"] is None
    assert candidate["cap_applied"] is False
    assert candidate["would_change_target"] is False
    assert candidate["unavailable_reason"] == "shadow_mode"
    assert "shadow_mode_no_cap_candidate" in candidate["warning_flags"]
    assert result.target_weight == 0.20
    assert result.delta_amount == 20000.0
    assert result.position_action == "OPEN"


def test_wider_stop_distance_reduces_cap_candidate():
    near_stop = build_risk_sizing_cap_candidate(
        result=_result(stop_loss=95.0, target_weight=0.30),
        action_model={"position_action": "OPEN", "target_weight": 0.30, "delta_amount": 30000.0},
        overview={"total_value": 100000.0, "cash": 50000.0},
        settings=_settings(),
        is_blocked=False,
        is_actionable_context=True,
    )
    wider_stop = build_risk_sizing_cap_candidate(
        result=_result(stop_loss=90.0, target_weight=0.30),
        action_model={"position_action": "OPEN", "target_weight": 0.30, "delta_amount": 30000.0},
        overview={"total_value": 100000.0, "cash": 50000.0},
        settings=_settings(),
        is_blocked=False,
        is_actionable_context=True,
    )

    assert wider_stop["stop_distance"] > near_stop["stop_distance"]
    assert wider_stop["capped_target_weight"] < near_stop["capped_target_weight"]


def test_cap_candidate_respects_single_position_cap():
    candidate = build_risk_sizing_cap_candidate(
        result=_result(stop_loss=99.0, target_weight=0.60),
        action_model={"position_action": "OPEN", "target_weight": 0.60, "delta_amount": 60000.0},
        overview={"total_value": 100000.0, "cash": 100000.0},
        settings=_settings(max_single_position_weight=0.35, max_daily_turnover_pct=1.0),
        is_blocked=False,
        is_actionable_context=True,
    )

    assert candidate["capped_target_weight"] == 0.35
    assert "max_single_position_weight" in candidate["constraints_applied"]


def test_cap_candidate_is_unavailable_without_close_or_stop_distance():
    candidate = build_risk_sizing_cap_candidate(
        result=_result(stop_loss=None, market_snapshot={}, current_price=None),
        action_model={"position_action": "OPEN", "target_weight": 0.10, "delta_amount": 5000.0},
        overview={"total_value": 100000.0, "cash": 50000.0},
        settings=_settings(),
        is_blocked=False,
        is_actionable_context=True,
    )

    assert candidate["capped_target_weight"] is None
    assert candidate["cap_applied"] is False
    assert candidate["unavailable_reason"] == "missing_price_or_stop_distance"
    assert "missing_close_price" in candidate["warning_flags"]
    assert "missing_stop_distance" in candidate["warning_flags"]


def test_blocked_candidate_is_unavailable_and_not_actionable():
    result = _result(validation_status="BLOCK", validation_issues=["收盘价缺失"])

    candidate = build_risk_sizing_cap_candidate(
        result=result,
        action_model=_action(result),
        overview={"total_value": 100000.0, "cash": 50000.0},
        settings=_settings(),
        is_blocked=True,
        is_actionable_context=True,
    )

    assert candidate["capped_target_weight"] is None
    assert candidate["cap_applied"] is False
    assert candidate["would_change_target"] is False
    assert candidate["unavailable_reason"] == "validation_block"
    assert "validation_block" in candidate["warning_flags"]


def test_cap_candidate_never_suggests_forced_sell_for_add_context():
    result = _result(
        position_action="ADD",
        current_weight=0.30,
        target_weight=0.35,
        delta_amount=5000.0,
        stop_loss=50.0,
    )

    candidate = build_risk_sizing_cap_candidate(
        result=result,
        action_model=_action(result),
        overview={"total_value": 100000.0, "cash": 50000.0},
        settings=_settings(max_single_position_weight=0.35),
        is_blocked=False,
        is_actionable_context=True,
    )

    assert candidate["capped_target_weight"] == 0.30
    assert candidate["would_change_target"] is True
    assert "cap_below_current_holding" in candidate["warning_flags"]
    assert "no_forced_sell" in candidate["constraints_applied"]
    assert result.position_action == "ADD"
    assert result.target_weight == 0.35
    assert result.delta_amount == 5000.0


def test_default_shadow_summary_still_does_not_change_actions_or_counts():
    result = _result()
    summary = build_daily_decision_summary(
        results=[result],
        report_date="2026-05-05",
        generated_at=datetime(2026, 5, 5, 7, 30, tzinfo=ZoneInfo("Australia/Sydney")),
        overview={"cash": 50000.0, "equity_value": 50000.0, "total_value": 100000.0, "holdings": []},
        get_primary_action_model=_action,
        classify_price_basis=lambda item: item.execution_price_source,
        format_stock_display_name=lambda name, code: f"{name} ({code})",
        format_validation_issue_text=lambda item: "；".join(item.validation_issues or []),
        risk_sizing_settings=_settings(mode="shadow"),
    )

    assert summary["action_counts"] == {
        "buy": 1,
        "add": 0,
        "reduce": 0,
        "close": 0,
        "hold_watch": 0,
        "blocked": 0,
        "total_actions": 1,
    }
    assert summary["actionable_items"][0]["position_action"] == "OPEN"
    assert summary["actionable_items"][0]["target_weight"] == 0.10
    assert summary["actionable_items"][0]["delta_amount"] == 5000.0
    assert result.final_decision == "BUY"
    assert result.validation_status == "PASS"
