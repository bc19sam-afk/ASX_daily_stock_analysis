# -*- coding: utf-8 -*-
"""Daily decision summary evidence matrix integration tests."""

from datetime import datetime
from zoneinfo import ZoneInfo

from src.analyzer import AnalysisResult
from src.daily_decision_summary import build_daily_decision_summary
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
        execution_price_source="close_only",
        market_snapshot={"date": "2026-04-28", "close": "50.00", "source": "yfinance"},
        technical_analysis="MA10 支撑仍在",
        fundamental_analysis="估值稳定",
        news_summary="无重大新增风险",
        action_reason="等待触发条件",
    )
    base.update(overrides)
    return AnalysisResult(**base)


def _model(result):
    return {
        "position_action": result.position_action,
        "target_weight": result.target_weight,
        "delta_amount": result.delta_amount,
    }


def _summary(results):
    return build_daily_decision_summary(
        results=results,
        report_date="2026-04-29",
        generated_at=datetime(2026, 4, 29, 7, 30, tzinfo=ZoneInfo("Australia/Sydney")),
        overview={"cash": 10000.0, "holdings": [{"code": "BHP.AX", "weight": 0.2}]},
        get_primary_action_model=_model,
        classify_price_basis=lambda result: result.execution_price_source,
        format_stock_display_name=lambda name, code: f"{name} ({code})",
        format_validation_issue_text=lambda result: "；".join(result.validation_issues or []),
    )


def _by_category(entries):
    return {entry["category"]: entry for entry in entries}


def test_daily_decision_summary_contains_evidence_matrix_without_changing_actions():
    results = [
        _result(
            code="BHP.AX",
            final_decision="BUY",
            position_action="ADD",
            current_weight=0.2,
            target_weight=0.25,
            delta_amount=2500.0,
        ),
        _result(
            code="NAB.AX",
            validation_status="BLOCK",
            validation_issues=["收盘价缺失，无法确认昨收计划。"],
            news_summary="",
            fundamental_analysis="",
        ),
    ]

    summary = _summary(results)

    assert "evidence_matrix" in summary
    assert set(summary["evidence_matrix"].keys()) == {"BHP.AX", "NAB.AX"}
    assert summary["action_counts"]["add"] == 1
    assert summary["action_counts"]["blocked"] == 1
    assert [item["code"] for item in summary["actionable_items"]] == ["BHP.AX"]
    assert [item["code"] for item in summary["blocked_items"]] == ["NAB.AX"]

    nab_evidence = _by_category(summary["evidence_matrix"]["NAB.AX"])
    assert nab_evidence["validation"]["severity"] == "block"
    assert nab_evidence["news"]["status"] == "missing"
    assert nab_evidence["valuation"]["status"] == "missing"
    assert nab_evidence["backtest"]["status"] == "not_checked"


def test_dashboard_report_renders_evidence_summary_and_detail_table(monkeypatch):
    service = NotificationService.__new__(NotificationService)
    service._report_summary_only = False
    service._report_timezone = "Australia/Sydney"
    service._last_daily_decision_summary = None
    monkeypatch.setattr(
        "src.notification.get_db",
        lambda: type("DB", (), {"get_portfolio_overview": lambda self: {"cash": 10000.0, "holdings": []}})(),
    )

    report = service.generate_dashboard_report(
        [
            _result(code="BHP.AX"),
            _result(code="NAB.AX", news_summary="", validation_status="BLOCK"),
        ],
        report_date="2026-04-29",
    )

    assert "## 证据质量摘要" in report
    assert "行情数据完整" in report
    assert "新闻证据缺失" in report
    assert "validation block" in report
    assert "## 个股证据矩阵" in report
    assert "| 标的 | 类别 | 来源 | 时间 | 状态 | 说明 |" in report
    assert "not_checked" in report
