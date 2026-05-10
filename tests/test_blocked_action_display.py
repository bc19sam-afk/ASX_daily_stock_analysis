# -*- coding: utf-8 -*-
"""Blocked action display must not leak pseudo-execution fields."""

from unittest.mock import patch

from src.analyzer import AnalysisResult
from src.notification import NotificationService


def _service(*, summary_only: bool = True) -> NotificationService:
    service = NotificationService.__new__(NotificationService)
    service._report_summary_only = summary_only
    service._report_timezone = "Australia/Sydney"
    service._last_daily_decision_summary = None
    return service


def _blocked_result() -> AnalysisResult:
    return AnalysisResult(
        code="BHP.AX",
        name="BHP",
        sentiment_score=70,
        trend_prediction="看多",
        operation_advice="必须买入",
        final_decision="BUY",
        position_action="ADD",
        current_weight=0.2,
        target_weight=0.3,
        delta_amount=5000.0,
        ideal_buy=10.0,
        stop_loss=9.2,
        take_profit=11.5,
        validation_status="BLOCK",
        validation_issues=["价格口径混用：信号基于旧日线，但执行价使用实时价格。"],
        action_reason="AI text should not matter",
    )


def _pass_result() -> AnalysisResult:
    return AnalysisResult(
        code="RIO.AX",
        name="Rio Tinto",
        sentiment_score=72,
        trend_prediction="震荡上行",
        operation_advice="按计划执行",
        final_decision="BUY",
        position_action="OPEN",
        current_weight=0.0,
        target_weight=0.1,
        delta_amount=1000.0,
        validation_status="PASS",
        analysis_status="OK",
        analysis_summary="综合分析正文",
        technical_analysis="技术面内容",
        fundamental_analysis="基本面内容",
        news_summary="新闻内容",
        risk_warning="风险内容",
    )


@patch("src.notification.get_db")
def test_blocked_dashboard_does_not_show_executable_sizing_or_plan_points(mock_get_db):
    mock_get_db.return_value.get_portfolio_overview.return_value = {
        "cash": 5000.0,
        "equity_value": 10000.0,
        "total_value": 15000.0,
        "holdings": [{"code": "BHP.AX", "name": "BHP", "weight": 0.2}],
    }
    report = _service().generate_dashboard_report([_blocked_result()], report_date="2026-04-29")

    assert "不可决策（仅观察）" in report
    assert "价格口径混用" in report
    assert "目标仓位 30.00%" not in report
    assert "模拟Δ 5,000.00" not in report
    assert "当前/保持仓位" not in report
    assert "条件化计划点位" not in report
    assert "理想买入观察位" not in report


@patch("src.notification.get_db")
def test_blocked_wechat_summary_does_not_show_sizing_or_ai_buy_language(mock_get_db):
    mock_get_db.return_value.get_portfolio_overview.return_value = {
        "cash": 5000.0,
        "equity_value": 10000.0,
        "total_value": 15000.0,
        "holdings": [{"code": "BHP.AX", "name": "BHP", "weight": 0.2}],
    }
    wechat = _service().generate_wechat_dashboard([_blocked_result()])

    assert "**B2) 不可决策（仅观察）**" in wechat
    assert "目标 30.00%" not in wechat
    assert "模拟目标 30.00%" not in wechat
    assert "Δ5,000.00" not in wechat
    assert "必须买入" not in wechat


@patch("src.notification.get_db")
def test_full_report_surfaces_blocked_result_without_execution_language(mock_get_db):
    mock_get_db.return_value.get_portfolio_overview.return_value = {
        "cash": 5000.0,
        "equity_value": 10000.0,
        "total_value": 15000.0,
        "holdings": [{"code": "BHP.AX", "name": "BHP", "weight": 0.2}],
    }
    result = _blocked_result()
    result.analysis_status = "DEGRADED"
    result.validation_issues = ["schema gate 失败", "analysis_status=DEGRADED"]

    report = _service(summary_only=False).generate_daily_report([result], report_date="2026-04-29")

    assert "暂不决策" in report
    assert "仅观察" in report
    assert "AI 输出格式异常" in report
    assert "本次分析失败或结果不完整" in report
    assert "不买入、不加仓、不减仓" in report
    assert "行情数据是否完整" in report
    assert "必须买入" not in report
    assert "BUY" not in report
    assert "OPEN" not in report
    assert "ADD" not in report
    assert "target quantity" not in report
    assert "target position" not in report
    assert "目标仓位 30.00%" not in report
    assert "目标数量" not in report
    assert "validation_status=BLOCK" not in report
    assert "final_decision=HOLD" not in report
    assert "position_action=HOLD" not in report
    assert "analysis_status=DEGRADED" not in report


@patch("src.notification.get_db")
def test_full_report_keeps_pass_detail_sections(mock_get_db):
    mock_get_db.return_value.get_portfolio_overview.return_value = {
        "cash": 5000.0,
        "equity_value": 10000.0,
        "total_value": 15000.0,
        "holdings": [],
    }

    report = _service(summary_only=False).generate_daily_report([_pass_result()], report_date="2026-04-29")

    assert "综合分析正文" in report
    assert "技术面内容" in report
    assert "基本面内容" in report
    assert "新闻内容" in report
    assert "风险内容" in report
    assert "暂不决策" not in report
