# -*- coding: utf-8 -*-
"""Morning Review Card report/email projection tests."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from src.core.risk_sizing import RiskSizingSettings
from src.daily_decision_summary import (
    build_daily_decision_summary,
    render_morning_review_card_lines,
)

from tests.test_report_readability_guardrail import (
    _overview,
    _readability_results,
    _result,
    _service,
)


def _model(result):
    return {
        "position_action": result.position_action,
        "target_weight": result.target_weight,
        "delta_amount": result.delta_amount,
    }


def _summary(results, *, overview=None, risk_sizing_settings=None):
    return build_daily_decision_summary(
        results=results,
        report_date="2026-04-29",
        generated_at=datetime(2026, 4, 29, 7, 30, tzinfo=ZoneInfo("Australia/Sydney")),
        overview=overview or _overview(),
        get_primary_action_model=_model,
        classify_price_basis=lambda result: result.execution_price_source,
        format_stock_display_name=lambda name, code: f"{name} ({code})",
        format_validation_issue_text=lambda result: "；".join(result.validation_issues or []),
        risk_sizing_settings=risk_sizing_settings,
    )


def _card_text(summary):
    return "\n".join(render_morning_review_card_lines(summary))


@patch("src.notification.get_db")
def test_morning_review_card_reaches_email_body_with_action_watch_and_blocked_items(mock_get_db):
    mock_get_db.return_value.get_portfolio_overview.return_value = _overview()
    service = _service()

    archive_report = service.generate_dashboard_report(_readability_results(), report_date="2026-04-29")
    email_body = service.build_email_report_body(archive_report)

    assert "## Morning Review Card" in email_body
    assert "今日总判断" in email_body
    assert "先看这几只" in email_body
    assert "BHP (BHP.AX)" in email_body
    assert "关键风险" in email_body
    assert "数据可靠性" in email_body
    assert "人工复核" in email_body
    assert "## 详情 / 审计附录" not in email_body
    assert "## 完整归档" in email_body


def test_morning_review_card_handles_no_actionable_day_with_manual_review_reminder():
    summary = _summary(
        [
            _result(
                code="WES.AX",
                name="WES",
                final_decision="HOLD",
                position_action="HOLD",
                current_weight=0.0,
                target_weight=0.0,
                delta_amount=0.0,
            )
        ],
        overview={"cash": 10000.0, "equity_value": 0.0, "total_value": 10000.0, "holdings": []},
    )

    card = _card_text(summary)

    assert "今日没有明确计划动作，以观察为主" in card
    assert "观察名单 1 只" in card
    assert "人工复核" in card
    assert "系统不自动下单" in card


def test_morning_review_card_surfaces_reliability_and_data_quality_degradation():
    summary = _summary(
        [
            _result(
                code="BHP.AX",
                name="BHP",
                final_decision="BUY",
                position_action="ADD",
                current_weight=0.20,
                target_weight=0.24,
                delta_amount=4000.0,
                execution_price_source="realtime",
                data_quality_flag="STALE_NEWS",
                market_snapshot={"date": "2026-04-29", "close": "50.00", "price": "50.40", "source": "yfinance"},
            ),
            _result(
                code="NAB.AX",
                name="NAB",
                validation_status="BLOCK",
                validation_issues=["收盘价缺失，无法确认昨收计划。"],
                fundamental_analysis="",
                news_summary="",
            ),
        ]
    )

    card = _card_text(summary)

    assert "报告可信度" in card
    assert "包含实时价格参考" in card
    assert "数据质量" in card
    assert "验证阻断" in card
    assert "收盘价缺失" in card


def test_morning_review_card_marks_risk_sizing_as_preview_without_mutating_actions():
    summary = _summary(
        [
            _result(
                code="BHP.AX",
                name="BHP",
                final_decision="BUY",
                position_action="ADD",
                current_weight=0.20,
                target_weight=0.24,
                delta_amount=4000.0,
                market_snapshot={"date": "2026-04-28", "close": "50.00", "source": "yfinance"},
            )
        ],
        risk_sizing_settings=RiskSizingSettings(mode="enabled", max_trade_risk_pct=0.001),
    )
    action_item = summary["actionable_items"][0]

    card = _card_text(summary)

    assert "风险仓位试算" in card
    assert "不改变主动作" in card
    assert action_item["position_action"] == "ADD"
    assert action_item["target_weight"] == 0.24
    assert action_item["delta_amount"] == 4000.0
    assert "买入股数" not in card
    assert "目标股数" not in card


@patch("src.notification.get_db")
def test_legacy_daily_report_body_also_includes_morning_review_card(mock_get_db):
    mock_get_db.return_value.get_portfolio_overview.return_value = _overview()
    service = _service()

    report = service.generate_daily_report(_readability_results(), report_date="2026-04-29")

    assert "## Morning Review Card" in report
    assert "今日总判断" in report
    assert "先看这几只" in report
    assert report.index("## Morning Review Card") < report.index("## 📊 操作建议汇总")
