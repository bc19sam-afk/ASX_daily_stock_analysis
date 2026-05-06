# -*- coding: utf-8 -*-
"""Risk sizing shadow mode summary and report contract tests."""

from datetime import datetime
from zoneinfo import ZoneInfo

from src.analyzer import AnalysisResult
from src.daily_decision_summary import (
    build_daily_decision_summary,
    render_preopen_decision_appendix,
    render_preopen_decision_dashboard,
)


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


def _action_model(result: AnalysisResult) -> dict:
    return {
        "position_action": result.position_action,
        "target_weight": result.target_weight,
        "delta_amount": result.delta_amount,
    }


def _summary(results):
    return build_daily_decision_summary(
        results=results,
        report_date="2026-05-05",
        generated_at=datetime(2026, 5, 5, 7, 30, tzinfo=ZoneInfo("Australia/Sydney")),
        overview={"cash": 50000.0, "equity_value": 50000.0, "total_value": 100000.0, "holdings": []},
        get_primary_action_model=_action_model,
        classify_price_basis=lambda result: result.execution_price_source,
        format_stock_display_name=lambda name, code: f"{name} ({code})",
        format_validation_issue_text=lambda result: "；".join(result.validation_issues or []),
    )


def _render_dashboard(summary) -> str:
    return "\n".join(
        render_preopen_decision_dashboard(summary)
        + render_preopen_decision_appendix(summary)
    )


def test_risk_sizing_shadow_preview_does_not_change_deterministic_action_fields():
    result = _result()

    summary = _summary([result])

    assert summary["action_counts"] == {
        "buy": 1,
        "add": 0,
        "reduce": 0,
        "close": 0,
        "hold_watch": 0,
        "blocked": 0,
        "total_actions": 1,
    }
    item = summary["actionable_items"][0]
    assert item["position_action"] == "OPEN"
    assert item["target_weight"] == 0.10
    assert item["delta_amount"] == 5000.0
    assert item["final_action_display"]["position_action"] == "OPEN"

    preview = summary["risk_sizing_previews"][0]
    assert preview["code"] == "BHP.AX"
    assert preview["mode"] == "shadow"
    assert preview["current_target_weight"] == 0.10
    assert preview["current_delta_amount"] == 5000.0
    assert preview["raw_risk_target_weight"] == 0.10
    assert preview["capped_risk_target_weight"] == 0.10
    assert preview["is_actionable_context"] is True


def test_blocked_result_gets_unavailable_shadow_preview_and_stays_blocked():
    blocked = _result(
        code="NAB.AX",
        name="NAB",
        position_action="ADD",
        current_weight=0.12,
        target_weight=0.17,
        delta_amount=5000.0,
        validation_status="BLOCK",
        validation_issues=["mixed_price_basis"],
    )

    summary = _summary([blocked])
    report = _render_dashboard(summary)

    assert summary["action_counts"]["blocked"] == 1
    assert summary["action_counts"]["total_actions"] == 0
    assert summary["blocked_items"][0]["final_action_display"]["actionability"] == "blocked"
    assert summary["blocked_items"][0]["final_action_display"]["can_show_sizing"] is False

    preview = summary["risk_sizing_previews"][0]
    assert preview["code"] == "NAB.AX"
    assert preview["raw_risk_target_weight"] is None
    assert preview["capped_risk_target_weight"] is None
    assert preview["current_target_weight"] == 0.12
    assert preview["current_delta_amount"] == 0.0
    assert preview["is_actionable_context"] is False
    assert "validation_block" in preview["warning_flags"]
    assert "风险仓位参考：不可用，原因：validation BLOCK，仅观察。" in report


def test_dashboard_renders_shadow_wording_without_changing_close_only_context():
    summary = _summary([_result()])
    report = _render_dashboard(summary)

    assert "风险仓位参考（Shadow，不改变今日动作）" in report
    assert "仅供人工复核，不改变今日 deterministic action" in report
    assert summary["price_policy"] == "close_only"
    assert summary["technical_basis_date"] == "2026-05-04"
    assert "**价格口径**：close_only；技术基准日 2026-05-04" in report
