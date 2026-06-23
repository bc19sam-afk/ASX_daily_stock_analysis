# -*- coding: utf-8 -*-
"""Final action display contract tests."""

from src.analyzer import AnalysisResult
from src.final_action_display import build_final_action_display
from src.notification import NotificationService


def _result(**overrides) -> AnalysisResult:
    base = dict(
        code="BHP.AX",
        name="BHP",
        sentiment_score=70,
        trend_prediction="震荡上行",
        operation_advice="按计划观察",
        final_decision="HOLD",
        position_action="HOLD",
        current_weight=0.0,
        target_weight=0.0,
        delta_amount=0.0,
        validation_status="PASS",
        action_reason="等待触发条件",
    )
    base.update(overrides)
    return AnalysisResult(**base)


def _display(result, *, min_delta_amount=20.0, min_buy_delta_amount=None):
    return build_final_action_display(
        result,
        action_model={
            "decision": result.final_decision,
            "position_action": result.position_action,
            "target_weight": result.target_weight,
            "delta_amount": result.delta_amount,
        },
        min_delta_amount=min_delta_amount,
        min_buy_delta_amount=min_buy_delta_amount,
        format_stock_display_name=lambda name, code: f"{name} ({code})",
        format_validation_issue_text=lambda item: "；".join(item.validation_issues or []),
    )


def test_blocked_display_never_allows_sizing_or_plan_points():
    result = _result(
        validation_status="BLOCK",
        validation_issues=["价格口径混用"],
        final_decision="BUY",
        position_action="ADD",
        current_weight=0.2,
        target_weight=0.3,
        delta_amount=5000.0,
    )

    display = _display(result)

    assert display["actionability"] == "blocked"
    assert display["position_action"] == "HOLD"
    assert display["can_show_sizing"] is False
    assert display["can_show_plan_points"] is False
    assert display["display_label"] == "不可决策 / 仅观察"
    assert display["reason"] == "价格口径混用"


def test_failed_display_never_allows_sizing_or_plan_points():
    result = _result(success=False, analysis_status="FAILED", error_message="provider failed", position_action="OPEN", target_weight=0.1, delta_amount=3000.0)

    display = _display(result)

    assert display["actionability"] == "failed"
    assert display["can_show_sizing"] is False
    assert display["can_show_plan_points"] is False


def test_tiny_delta_executable_action_becomes_watch_only():
    result = _result(final_decision="BUY", position_action="OPEN", target_weight=0.1, delta_amount=0.6)

    display = _display(result, min_delta_amount=20.0)

    assert display["actionability"] == "watch_only"
    assert display["position_action"] == "HOLD"
    assert display["can_show_sizing"] is False
    assert display["can_show_plan_points"] is True


def test_small_open_below_buy_notional_threshold_becomes_watch_only():
    result = _result(final_decision="BUY", position_action="OPEN", target_weight=0.1, delta_amount=21.78)

    display = _display(result, min_delta_amount=20.0, min_buy_delta_amount=1000.0)

    assert display["actionability"] == "watch_only"
    assert display["position_action"] == "HOLD"
    assert display["delta_amount"] == 0.0


def test_buy_notional_threshold_does_not_suppress_small_reduce():
    result = _result(
        final_decision="SELL",
        position_action="REDUCE",
        current_weight=0.2,
        target_weight=0.18,
        delta_amount=-21.78,
    )

    display = _display(result, min_delta_amount=20.0, min_buy_delta_amount=1000.0)

    assert display["actionability"] == "actionable"
    assert display["position_action"] == "REDUCE"
    assert display["delta_amount"] == -21.78


def test_ai_prose_does_not_change_display_action_or_underlying_result():
    result = _result(
        operation_advice="AI says must buy now and sell later",
        final_decision="HOLD",
        position_action="HOLD",
        target_weight=0.0,
        delta_amount=0.0,
    )

    display = _display(result)

    assert display["actionability"] == "watch_only"
    assert display["position_action"] == "HOLD"
    assert result.position_action == "HOLD"
    assert result.operation_advice == "AI says must buy now and sell later"


def test_notification_service_uses_final_action_display_for_actionability():
    service = NotificationService.__new__(NotificationService)
    result = _result(position_action="OPEN", target_weight=0.1, delta_amount=0.6)

    display = service._build_final_action_display(result)

    assert display["actionability"] == "watch_only"
    assert service._is_actionable_today(result) is False
