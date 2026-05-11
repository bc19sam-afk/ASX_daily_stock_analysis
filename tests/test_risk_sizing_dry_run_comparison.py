# -*- coding: utf-8 -*-
"""Risk sizing dry-run comparison contract tests."""

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
        target_weight=0.20,
        delta_amount=20000.0,
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


def test_dry_run_comparison_renders_without_changing_action_fields():
    result = _result()

    summary = _summary([result])
    report = _render_dashboard(summary)

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
    assert item["target_weight"] == 0.20
    assert item["delta_amount"] == 20000.0
    assert item["final_action_display"]["position_action"] == "OPEN"
    assert item["final_action_display"]["confirmation_gap"] is True
    assert "风险仓位试算与目标仓位差异较大" in item["final_action_display"]["review_reasons"]

    comparison = summary["risk_sizing_comparison"]["BHP.AX"]
    assert comparison["mode"] == "dry_run"
    assert comparison["current_target_weight"] == 0.20
    assert comparison["risk_capped_candidate_weight"] == 0.10
    assert comparison["would_change_target"] is True
    assert comparison["difference_weight"] == -0.10
    assert "risk_budget" in comparison["constraints_applied"]
    assert "dry_run_no_action_change" in comparison["warning_flags"]
    assert comparison["note"] == "Dry run only; does not change today's action"

    assert "风险仓位对比（Dry Run，不改变今日动作）" in report
    assert "当前系统目标仓位 20.00%" in report
    assert "风险上限候选仓位 10.00%" in report
    assert "Dry Run，仅供人工复核，不改变今日 deterministic action" in report
    assert "需二次确认" in report
    assert "风险仓位试算与目标仓位差异较大" in report


def test_blocked_item_gets_unavailable_comparison_and_stays_blocked():
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

    comparison = summary["risk_sizing_comparison"]["NAB.AX"]
    assert comparison["risk_capped_candidate_weight"] is None
    assert comparison["would_change_target"] is False
    assert comparison["unavailable_reason"] == "validation_block"
    assert "validation_block" in comparison["warning_flags"]
    assert "风险仓位对比：不可用，原因：validation BLOCK，仅观察。" in report
    assert "风险上限候选仓位" not in report


def test_missing_price_or_stop_distance_is_unavailable_without_guessing():
    missing = _result(market_snapshot={"date": "2026-05-04", "source": "fixture"}, stop_loss=None)

    summary = _summary([missing])
    report = _render_dashboard(summary)

    comparison = summary["risk_sizing_comparison"]["BHP.AX"]
    assert comparison["risk_capped_candidate_weight"] is None
    assert comparison["would_change_target"] is False
    assert comparison["unavailable_reason"] == "missing_price_or_stop_distance"
    assert "missing_close_price" in comparison["warning_flags"]
    assert "missing_stop_distance" in comparison["warning_flags"]
    assert "风险仓位对比不可用" in report


def test_dry_run_comparison_keeps_close_only_context_and_action_counts():
    summary = _summary([_result()])
    report = _render_dashboard(summary)

    assert summary["price_policy"] == "close_only"
    assert summary["technical_basis_date"] == "2026-05-04"
    assert summary["action_counts"]["total_actions"] == 1
    assert summary["actionable_items"][0]["target_weight"] == 0.20
    assert summary["actionable_items"][0]["delta_amount"] == 20000.0
    assert "**价格来源**：全部使用昨收数据；技术基准日 2026-05-04" in report


def test_old_summary_without_review_fields_still_renders_dashboard():
    summary = _summary([_result()])
    legacy_summary = dict(summary)
    legacy_item = dict(summary["actionable_items"][0])
    legacy_display = dict(legacy_item["final_action_display"])
    legacy_display.pop("review_reasons", None)
    legacy_display.pop("confirmation_gap", None)
    legacy_display.pop("review_label", None)
    legacy_item["final_action_display"] = legacy_display
    legacy_summary["actionable_items"] = [legacy_item]

    dashboard = "\n".join(render_preopen_decision_dashboard(legacy_summary))

    assert "| 标的 | 今天怎么处理 | 目标仓位 | 计划金额 | 复核提示 |" in dashboard
    assert "BHP (BHP.AX)" in dashboard
