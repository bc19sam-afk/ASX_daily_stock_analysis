# -*- coding: utf-8 -*-
"""Backtest confidence panel contract tests."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from src.analyzer import AnalysisResult
from src.daily_decision_summary import build_daily_decision_summary
from src.notification import NotificationService


def _result(**overrides) -> AnalysisResult:
    base = dict(
        code="CBA.AX",
        name="CBA",
        sentiment_score=76,
        trend_prediction="震荡上行",
        operation_advice="按确定性动作观察",
        final_decision="BUY",
        position_action="OPEN",
        current_weight=0.0,
        target_weight=0.10,
        delta_amount=5000.0,
        execution_price_source="close_only",
        market_snapshot={"date": "2026-05-04", "close": "100.00", "source": "yfinance"},
        technical_analysis="MA20 仍在价格下方",
        fundamental_analysis="估值稳定",
        news_summary="无重大新增风险",
        action_reason="deterministic action",
    )
    base.update(overrides)
    return AnalysisResult(**base)


def _model(result: AnalysisResult) -> dict:
    return {
        "position_action": result.position_action,
        "target_weight": result.target_weight,
        "delta_amount": result.delta_amount,
    }


def _summary(results, *, backtest_confidence=None):
    return build_daily_decision_summary(
        results=results,
        report_date="2026-05-05",
        generated_at=datetime(2026, 5, 5, 7, 30, tzinfo=ZoneInfo("Australia/Sydney")),
        overview={"cash": 10000.0, "holdings": []},
        get_primary_action_model=_model,
        classify_price_basis=lambda result: result.execution_price_source,
        format_stock_display_name=lambda name, code: f"{name} ({code})",
        format_validation_issue_text=lambda result: "；".join(result.validation_issues or []),
        backtest_confidence=backtest_confidence,
    )


def _confidence_panel(sample_size=42, win_rate_pct=58.3, avg_simulated_return_pct=1.2):
    return {
        "overall": {
            "sample_size": sample_size,
            "window_days": 10,
            "win_rate_pct": win_rate_pct,
            "avg_simulated_return_pct": avg_simulated_return_pct,
            "confidence_level": "usable_sample" if sample_size >= 20 else "low_sample",
        },
        "by_action": {
            "OPEN": {
                "sample_size": sample_size,
                "win_rate_pct": win_rate_pct,
                "avg_simulated_return_pct": avg_simulated_return_pct,
                "confidence_level": "usable_sample" if sample_size >= 20 else "low_sample",
            },
            "ADD": {"sample_size": 0, "win_rate_pct": None, "avg_simulated_return_pct": None, "confidence_level": "low_sample"},
            "REDUCE": {"sample_size": 0, "win_rate_pct": None, "avg_simulated_return_pct": None, "confidence_level": "low_sample"},
            "CLOSE": {"sample_size": 0, "win_rate_pct": None, "avg_simulated_return_pct": None, "confidence_level": "low_sample"},
        },
    }


def test_backtest_confidence_panel_builds_enough_sample_metrics():
    from src.backtest_confidence import build_backtest_confidence_panel, render_backtest_confidence_lines

    rows = [
        SimpleNamespace(eval_status="completed", position_action="OPEN", outcome="win", simulated_return_pct=2.0),
        SimpleNamespace(eval_status="completed", position_action="OPEN", outcome="loss", simulated_return_pct=-1.0),
    ] * 15
    panel = build_backtest_confidence_panel(
        summary={
            "eval_window_days": 10,
            "completed_count": 30,
            "win_rate_pct": 66.67,
            "avg_simulated_return_pct": 0.5,
        },
        action_results=rows,
        window_days=10,
    )

    assert panel["overall"] == {
        "sample_size": 30,
        "window_days": 10,
        "win_rate_pct": 66.67,
        "avg_simulated_return_pct": 0.5,
        "confidence_level": "usable_sample",
    }
    assert panel["by_action"]["OPEN"]["sample_size"] == 30
    assert panel["by_action"]["OPEN"]["win_rate_pct"] == 50.0
    rendered = "\n".join(render_backtest_confidence_lines(panel, action_counts={"buy": 1}))
    assert "历史校准" in rendered
    assert "10 日窗口" in rendered
    assert "样本 30 次" in rendered
    assert "胜率 66.67%" in rendered
    assert "平均模拟收益 +0.50%" in rendered
    assert "个股回测状态以证据矩阵为准" in rendered


def test_backtest_confidence_panel_marks_low_sample_without_confidence_boost():
    from src.backtest_confidence import build_backtest_confidence_panel, render_backtest_confidence_lines

    panel = build_backtest_confidence_panel(
        summary={
            "eval_window_days": 10,
            "completed_count": 3,
            "win_rate_pct": 100.0,
            "avg_simulated_return_pct": 4.2,
        },
        action_results=[],
        window_days=10,
    )

    assert panel["overall"]["confidence_level"] == "low_sample"
    rendered = "\n".join(render_backtest_confidence_lines(panel, action_counts={"buy": 1}))
    assert "历史样本不足，不作为置信增强" in rendered
    assert "高置信" not in rendered


def test_backtest_confidence_panel_handles_no_data_without_error():
    from src.backtest_confidence import build_backtest_confidence_panel, render_backtest_confidence_lines

    panel = build_backtest_confidence_panel(summary=None, action_results=[], window_days=10)

    assert panel["overall"]["sample_size"] == 0
    assert panel["overall"]["confidence_level"] == "low_sample"
    rendered = "\n".join(render_backtest_confidence_lines(panel, action_counts={}))
    assert "无可用回测摘要" in rendered


def test_backtest_confidence_does_not_change_actions_or_counts():
    result = _result(position_action="OPEN", final_decision="BUY", target_weight=0.1, delta_amount=5000.0)

    without_confidence = _summary([result])
    with_confidence = _summary([result], backtest_confidence=_confidence_panel())

    assert with_confidence["backtest_confidence"]["overall"]["sample_size"] == 42
    assert with_confidence["action_counts"] == without_confidence["action_counts"]
    assert with_confidence["actionable_items"][0]["position_action"] == without_confidence["actionable_items"][0]["position_action"]
    assert with_confidence["actionable_items"][0]["final_action_display"] == without_confidence["actionable_items"][0]["final_action_display"]


@patch("src.notification.get_db")
def test_dashboard_renders_backtest_confidence_without_action_changes(mock_get_db):
    mock_get_db.return_value.get_portfolio_overview.return_value = {"cash": 10000.0, "holdings": []}
    service = NotificationService.__new__(NotificationService)
    service._report_summary_only = False
    service._report_timezone = "Australia/Sydney"
    service._last_daily_decision_summary = None
    service._build_backtest_confidence_panel = lambda: _confidence_panel()

    report = service.generate_dashboard_report([_result()], report_date="2026-05-05")
    summary = service.get_last_daily_decision_summary()

    assert "历史校准" in report
    assert "10 日窗口" in report
    assert "样本 42 次" in report
    assert "胜率 58.30%" in report
    assert "平均模拟收益 +1.20%" in report
    assert "个股回测状态以证据矩阵为准" in report
    assert summary["action_counts"] == {"buy": 1, "add": 0, "reduce": 0, "close": 0, "hold_watch": 0, "blocked": 0, "total_actions": 1}


@patch("src.notification.get_db")
def test_blocked_items_do_not_receive_action_confidence_enhancement(mock_get_db):
    mock_get_db.return_value.get_portfolio_overview.return_value = {"cash": 10000.0, "holdings": []}
    service = NotificationService.__new__(NotificationService)
    service._report_summary_only = False
    service._report_timezone = "Australia/Sydney"
    service._last_daily_decision_summary = None
    service._build_backtest_confidence_panel = lambda: _confidence_panel()
    blocked = _result(
        code="NAB.AX",
        name="NAB",
        validation_status="BLOCK",
        validation_issues=["收盘价缺失，无法确认昨收计划。"],
        position_action="OPEN",
        target_weight=0.10,
        delta_amount=3000.0,
    )

    report = service.generate_dashboard_report([blocked], report_date="2026-05-05")
    summary = service.get_last_daily_decision_summary()

    assert summary["action_counts"]["total_actions"] == 0
    assert summary["action_counts"]["blocked"] == 1
    assert "OPEN 历史样本" not in report
    assert "新开仓历史样本" not in report
