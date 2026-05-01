# -*- coding: utf-8 -*-
"""Tests for the pre-open decision cockpit and archive artifacts."""

from pathlib import Path
from unittest.mock import patch
from datetime import datetime
from zoneinfo import ZoneInfo

from src.analyzer import AnalysisResult
from src.notification import NotificationService


def _service() -> NotificationService:
    service = NotificationService.__new__(NotificationService)
    service._report_summary_only = False
    service._report_timezone = "Australia/Sydney"
    service._last_daily_decision_summary = None
    return service


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
        action_reason="等待触发条件",
    )
    base.update(overrides)
    return AnalysisResult(**base)


def _overview():
    return {
        "cash": 10000.0,
        "equity_value": 40000.0,
        "total_value": 50000.0,
        "holdings": [
            {"code": "BHP.AX", "name": "BHP", "quantity": 100, "market_value": 10000.0},
            {"code": "CSL.AX", "name": "CSL", "quantity": 20, "market_value": 12000.0},
            {"code": "TLS.AX", "name": "TLS", "quantity": 1000, "market_value": 8000.0},
        ],
    }


def _mixed_action_results():
    return [
        _result(
            code="BHP.AX",
            name="BHP",
            final_decision="BUY",
            position_action="ADD",
            current_weight=0.20,
            target_weight=0.25,
            delta_amount=2500.0,
        ),
        _result(
            code="CBA.AX",
            name="CBA",
            final_decision="BUY",
            position_action="OPEN",
            target_weight=0.10,
            delta_amount=5000.0,
            action_reason="",
            buy_reason="AI narrative should not enter daily_decision_summary reason",
        ),
        _result(
            code="CSL.AX",
            name="CSL",
            final_decision="SELL",
            position_action="REDUCE",
            current_weight=0.24,
            target_weight=0.15,
            delta_amount=-4500.0,
        ),
        _result(
            code="TLS.AX",
            name="TLS",
            final_decision="SELL",
            position_action="CLOSE",
            current_weight=0.16,
            target_weight=0.0,
            delta_amount=-8000.0,
        ),
        _result(
            code="WES.AX",
            name="WES",
            final_decision="HOLD",
            position_action="HOLD",
            target_weight=0.0,
            delta_amount=0.0,
        ),
        _result(
            code="NAB.AX",
            name="NAB",
            final_decision="BUY",
            position_action="ADD",
            target_weight=0.12,
            delta_amount=6000.0,
            validation_status="BLOCK",
            validation_issues=["收盘价缺失，无法确认昨收计划。"],
        ),
    ]


@patch("src.notification.get_db")
def test_preopen_dashboard_close_only_wording_and_action_counts(mock_get_db):
    mock_get_db.return_value.get_portfolio_overview.return_value = _overview()
    service = _service()

    report = service.generate_dashboard_report(_mixed_action_results(), report_date="2026-04-29")

    assert report.startswith("# 🎯 2026-04-29 决策仪表盘\n\n## 开盘前决策驾驶舱")
    assert "昨收计划 / 开盘前计划" in report
    assert "不是实时交易建议" in report
    assert "开盘后执行前必须复核实时价格" in report
    assert "| 今日总动作数量 | **4** |" in report
    assert "| 买入 / 加仓 / 减仓 / 清仓 / 持有观察 / 阻塞 | 1 / 1 / 1 / 1 / 1 / 1 |" in report

    summary = service.get_last_daily_decision_summary()
    assert summary["price_policy"] == "close_only"
    assert summary["technical_basis_date"] == "2026-04-28"
    assert summary["action_counts"]["total_actions"] == 4
    assert summary["action_counts"]["blocked"] == 1


@patch("src.notification.get_db")
def test_blocked_items_are_not_counted_as_actionable(mock_get_db):
    mock_get_db.return_value.get_portfolio_overview.return_value = _overview()
    service = _service()

    summary = service.build_daily_decision_summary(
        _mixed_action_results(),
        report_date="2026-04-29",
        overview=service._build_report_time_portfolio_overview(
            overview=_overview(),
            results=_mixed_action_results(),
        ),
    )

    actionable_codes = {item["code"] for item in summary["actionable_items"]}
    blocked_codes = {item["code"] for item in summary["blocked_items"]}

    assert "NAB.AX" in blocked_codes
    assert "NAB.AX" not in actionable_codes
    assert summary["action_counts"]["total_actions"] == 4
    assert summary["action_counts"]["add"] == 1
    assert summary["action_counts"]["blocked"] == 1


@patch("src.notification.get_db")
def test_noise_sized_actions_are_counted_as_watch_not_actionable(mock_get_db):
    mock_get_db.return_value.get_portfolio_overview.return_value = _overview()
    service = _service()
    results = [
        _result(
            code="LAU.AX",
            name="LAU",
            final_decision="SELL",
            position_action="REDUCE",
            current_weight=0.1815,
            target_weight=0.1729,
            delta_amount=-0.60,
        ),
        _result(
            code="BHP.AX",
            name="BHP",
            final_decision="SELL",
            position_action="REDUCE",
            current_weight=0.36,
            target_weight=0.20,
            delta_amount=-1450.44,
        ),
    ]

    report = service.generate_dashboard_report(results, report_date="2026-04-29")
    summary = service.get_last_daily_decision_summary()

    assert "| 今日总动作数量 | **1** |" in report
    assert "LAU：减仓" not in report
    assert "BHP (BHP.AX)：减仓，目标仓位 20.00%，模拟调仓 -1,450.44" in report
    assert summary["action_counts"]["total_actions"] == 1
    assert summary["action_counts"]["reduce"] == 1
    assert summary["action_counts"]["hold_watch"] == 1
    assert {item["code"] for item in summary["actionable_items"]} == {"BHP.AX"}
    assert {item["code"] for item in summary["watch_items"]} == {"LAU.AX"}


@patch("src.notification.get_db")
def test_daily_decision_summary_schema_is_stable(mock_get_db):
    mock_get_db.return_value.get_portfolio_overview.return_value = _overview()
    service = _service()

    summary = service.build_daily_decision_summary(
        _mixed_action_results(),
        report_date="2026-04-29",
        overview=service._build_report_time_portfolio_overview(
            overview=_overview(),
            results=_mixed_action_results(),
        ),
    )

    expected_top_level_keys = {
        "schema_version",
        "report_date",
        "technical_basis_date",
        "technical_basis_dates",
        "price_policy",
        "price_basis_counts",
        "generated_at",
        "stock_count",
        "successful_count",
        "failed_count",
        "action_counts",
        "actionable_items",
        "watch_items",
        "blocked_items",
        "uncovered_holdings",
        "data_quality_flags",
        "execution_checklist",
        "watch_trigger_rule",
    }
    assert set(summary.keys()) == expected_top_level_keys
    assert summary["schema_version"] == "daily_decision_summary.v1"
    assert set(summary["action_counts"].keys()) == {
        "buy",
        "add",
        "reduce",
        "close",
        "hold_watch",
        "blocked",
        "total_actions",
    }
    assert summary["action_counts"] == {
        "buy": 1,
        "add": 1,
        "reduce": 1,
        "close": 1,
        "hold_watch": 1,
        "blocked": 1,
        "total_actions": 4,
    }

    assert [item["code"] for item in summary["actionable_items"]] == [
        "BHP.AX",
        "CBA.AX",
        "CSL.AX",
        "TLS.AX",
    ]
    assert set(summary["actionable_items"][0].keys()) == {
        "code",
        "name",
        "position_action",
        "target_weight",
        "current_weight",
        "delta_amount",
        "is_current_holding",
        "price_basis",
        "reason",
    }
    cba_item = next(item for item in summary["actionable_items"] if item["code"] == "CBA.AX")
    assert cba_item["reason"] == ""

    assert [item["code"] for item in summary["watch_items"]] == ["WES.AX"]
    assert set(summary["watch_items"][0].keys()) == {
        "code",
        "name",
        "position_action",
        "target_weight",
        "current_weight",
        "delta_amount",
        "is_current_holding",
        "price_basis",
        "reason",
        "trigger",
    }

    assert [item["code"] for item in summary["blocked_items"]] == ["NAB.AX"]
    assert set(summary["blocked_items"][0].keys()) == {
        "code",
        "name",
        "reason",
        "current_weight",
        "target_weight",
        "price_basis",
    }


@patch("src.notification.get_db")
def test_html_archive_is_text_based_and_contains_dashboard(mock_get_db, tmp_path: Path):
    mock_get_db.return_value.get_portfolio_overview.return_value = _overview()
    service = _service()
    report = service.generate_dashboard_report(_mixed_action_results(), report_date="2026-04-29")

    html_path = Path(
        service.save_report_archive_html(
            report,
            filename="report_20260429.html",
            reports_dir=tmp_path,
        )
    )
    html = html_path.read_text(encoding="utf-8")

    assert "<h2>开盘前决策驾驶舱</h2>" in html
    assert "昨收计划 / 开盘前计划" in html
    assert "开盘后执行前必须复核实时价格" in html
    assert "<table>" in html
    assert "<img" not in html.lower()
    assert "image placeholder" not in html.lower()


def test_report_archive_filenames_use_report_timezone(monkeypatch, tmp_path: Path):
    service = _service()
    monkeypatch.setattr(
        service,
        "_now_in_report_tz",
        lambda: datetime(2026, 4, 30, 1, 15, tzinfo=ZoneInfo("Australia/Sydney")),
    )

    md_path = Path(service.save_report_to_file("report", reports_dir=tmp_path))
    html_path = Path(service.save_report_archive_html("report", reports_dir=tmp_path))
    summary_path = Path(service.save_daily_decision_summary_to_file({}, reports_dir=tmp_path))

    assert md_path.name == "report_20260430.md"
    assert html_path.name == "report_20260430.html"
    assert summary_path.name == "daily_decision_summary_20260430.json"


def test_default_push_titles_use_report_timezone(monkeypatch):
    service = _service()
    monkeypatch.setattr(
        service,
        "_now_in_report_tz",
        lambda: datetime(2026, 4, 30, 1, 15, tzinfo=ZoneInfo("Australia/Sydney")),
    )
    monkeypatch.setattr(service, "_markdown_to_plain_text", lambda content: content)

    captured = {}
    service._pushover_config = {"user_key": "user", "api_token": "token"}

    def fake_send_pushover_message(api_url, user_key, api_token, content, title):
        captured["pushover"] = title
        return True

    monkeypatch.setattr(service, "_send_pushover_message", fake_send_pushover_message)
    assert service.send_to_pushover("content") is True
    assert captured["pushover"] == "📈 股票分析报告 - 2026-04-30"

    class _Response:
        status_code = 200

        @staticmethod
        def json():
            return {"code": 200}

    posts = []

    def fake_post(url, **kwargs):
        posts.append((url, kwargs))
        return _Response()

    monkeypatch.setattr("src.notification.requests.post", fake_post)
    service._pushplus_token = "token"
    assert service.send_to_pushplus("content") is True
    assert posts[-1][1]["json"]["title"] == "📈 股票分析报告 - 2026-04-30"

    service._serverchan3_sendkey = "SCTKEY"
    service._serverchan3_sendkey_2 = None
    assert service.send_to_serverchan3("content") is True
    assert posts[-1][1]["json"]["title"] == "📈 股票分析报告 - 2026-04-30"
