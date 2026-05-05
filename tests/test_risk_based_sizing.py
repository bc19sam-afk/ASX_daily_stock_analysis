# -*- coding: utf-8 -*-
"""Risk sizing shadow preview calculation tests."""

from types import SimpleNamespace

from src.core.risk_sizing import RiskSizingSettings, build_risk_sizing_preview


def _settings(**overrides) -> RiskSizingSettings:
    values = dict(
        max_single_position_weight=0.35,
        max_trade_risk_pct=0.005,
        atr_stop_multiplier=1.5,
        min_order_notional=20.0,
        max_daily_turnover_pct=0.20,
        mode="shadow",
    )
    values.update(overrides)
    return RiskSizingSettings(**values)


def _result(**overrides) -> SimpleNamespace:
    values = dict(
        code="BHP.AX",
        stop_loss=95.0,
        market_snapshot={"close": "100.00", "date": "2026-05-04"},
        current_price=100.0,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _action(**overrides) -> dict:
    values = {"position_action": "OPEN", "target_weight": 0.10, "delta_amount": 5000.0}
    values.update(overrides)
    return values


def test_risk_sizing_preview_calculates_reference_weight_from_stop_distance():
    preview = build_risk_sizing_preview(
        result=_result(stop_loss=95.0),
        action_model=_action(),
        overview={"total_value": 100000.0, "cash": 50000.0},
        settings=_settings(),
        is_blocked=False,
        is_actionable_context=True,
    )

    assert preview["mode"] == "shadow"
    assert preview["risk_budget_amount"] == 500.0
    assert preview["stop_distance"] == 5.0
    assert preview["stop_distance_source"] == "stop_loss"
    assert preview["raw_risk_target_weight"] == 0.10
    assert preview["capped_risk_target_weight"] == 0.10
    assert preview["current_target_weight"] == 0.10
    assert preview["current_delta_amount"] == 5000.0
    assert preview["is_actionable_context"] is True
    assert "shadow_no_action_change" in preview["warning_flags"]


def test_larger_stop_distance_reduces_raw_reference_weight():
    near_stop = build_risk_sizing_preview(
        result=_result(stop_loss=95.0),
        action_model=_action(),
        overview={"total_value": 100000.0, "cash": 50000.0},
        settings=_settings(),
        is_blocked=False,
        is_actionable_context=True,
    )
    wider_stop = build_risk_sizing_preview(
        result=_result(stop_loss=90.0),
        action_model=_action(),
        overview={"total_value": 100000.0, "cash": 50000.0},
        settings=_settings(),
        is_blocked=False,
        is_actionable_context=True,
    )

    assert wider_stop["stop_distance"] > near_stop["stop_distance"]
    assert wider_stop["raw_risk_target_weight"] < near_stop["raw_risk_target_weight"]


def test_risk_sizing_preview_caps_at_max_single_position_weight():
    preview = build_risk_sizing_preview(
        result=_result(stop_loss=99.0),
        action_model=_action(),
        overview={"total_value": 100000.0, "cash": 100000.0},
        settings=_settings(max_single_position_weight=0.35, max_daily_turnover_pct=1.0),
        is_blocked=False,
        is_actionable_context=True,
    )

    assert preview["raw_risk_target_weight"] == 0.50
    assert preview["capped_risk_target_weight"] == 0.35
    assert "max_single_position_weight" in preview["constraints_applied"]


def test_risk_sizing_preview_caps_at_daily_turnover_reference_limit():
    preview = build_risk_sizing_preview(
        result=_result(stop_loss=99.0, current_weight=0.10),
        action_model=_action(target_weight=0.15, delta_amount=5000.0),
        overview={"total_value": 100000.0, "cash": 100000.0},
        settings=_settings(max_single_position_weight=0.80, max_daily_turnover_pct=0.20),
        is_blocked=False,
        is_actionable_context=True,
    )

    assert preview["raw_risk_target_weight"] == 0.50
    assert preview["capped_risk_target_weight"] == 0.30
    assert "max_daily_turnover_pct" in preview["constraints_applied"]


def test_risk_sizing_preview_is_unavailable_without_close_or_stop_distance():
    preview = build_risk_sizing_preview(
        result=_result(stop_loss=None, market_snapshot={}, current_price=None),
        action_model=_action(),
        overview={"total_value": 100000.0, "cash": 50000.0},
        settings=_settings(),
        is_blocked=False,
        is_actionable_context=True,
    )

    assert preview["raw_risk_target_weight"] is None
    assert preview["capped_risk_target_weight"] is None
    assert preview["stop_distance"] is None
    assert preview["stop_distance_source"] == "unavailable"
    assert "missing_close_price" in preview["warning_flags"]
    assert "missing_stop_distance" in preview["warning_flags"]
