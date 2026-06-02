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
    assert "**开盘前快照**" in report
    assert "**今日结论**" in report
    assert "**今日动作数量**" in report
    assert "## Morning Review Card" in report
    assert "| **今日优先复核** |" in report
    assert "| **低优先级观察** |" in report
    assert "| **先补数据再判断** |" in report
    assert "**今日人工复核卡片**" not in report.split("\n---\n", 1)[0]
    assert "买入 1 / 加仓 1 / 减仓 1 / 清仓 1 / 观察 1 / 阻断 1" in report
    assert "**执行口径**" in report
    assert "| 复核项 |" in report
    assert "**报告可信度**" in report
    assert "**价格来源**：全部使用昨收数据" in report
    assert "技术基准日 2026-04-28" in report
    assert "**执行前检查**：" in report
    assert "**免费数据质量快照**" in report
    assert "| 项目 | 今天状态 |" in report
    assert "| 行情 |" in report
    assert "| 估值 |" in report
    assert "| 新闻 |" in report

    summary = service.get_last_daily_decision_summary()
    assert summary["price_policy"] == "close_only"
    assert summary["technical_basis_date"] == "2026-04-28"
    assert summary["action_counts"]["total_actions"] == 4
    assert summary["action_counts"]["blocked"] == 1
    assert summary["triage_card"]["counts"]["today_must_review"] == 4
    assert summary["triage_card"]["counts"]["today_can_ignore"] == 1
    assert summary["triage_card"]["counts"]["data_quality_attention"] >= 1
    assert summary["triage_card"]["today_must_review"][0]["source_fields"] == [
        "actionable_items",
        "final_action_display",
        "report_reliability",
    ]


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

    assert "**今日动作数量**：买入 0 / 加仓 0 / 减仓 1 / 清仓 0 / 观察 1 / 阻断 0" in report
    assert "LAU：减仓" not in report
    assert "LAU (LAU.AX)：减仓" not in report
    assert "**LAU (LAU.AX)** | 减仓" not in report
    assert "| 🔴 **LAU (LAU.AX)** | 0.00% | 17.29% | -0.60 |" not in report
    assert "### 🔴 LAU (LAU.AX)" not in report
    assert "| BHP (BHP.AX) | 减仓 | 20.00% | 计划调出约 1,450.44 |" in report
    assert summary["action_counts"]["total_actions"] == 1
    assert summary["action_counts"]["reduce"] == 1
    assert summary["action_counts"]["hold_watch"] == 1
    assert {item["code"] for item in summary["actionable_items"]} == {"BHP.AX"}
    assert {item["code"] for item in summary["watch_items"]} == {"LAU.AX"}
    lau_watch = summary["watch_items"][0]
    assert lau_watch["position_action"] == "HOLD"
    assert lau_watch["target_weight"] == lau_watch["current_weight"]
    assert lau_watch["delta_amount"] == 0.0
    assert lau_watch["suppressed_position_action"] == "REDUCE"
    assert lau_watch["suppressed_delta_amount"] == -0.60


@patch("src.notification.get_db")
def test_current_holding_hold_keeps_followup_review_without_fake_sell(mock_get_db):
    mock_get_db.return_value.get_portfolio_overview.return_value = _overview()
    service = _service()
    result = _result(
        code="BHP.AX",
        name="BHP",
        final_decision="HOLD",
        position_action="HOLD",
        current_weight=0.05,
        target_weight=0.20,
        delta_amount=0.0,
        risk_warning="若跌破 47.50 需要人工复核风险，需看公告。",
        dashboard={
            "battle_plan": {
                "sniper_points": {
                    "stop_loss": "47.50",
                    "take_profit": "55.00",
                }
            },
            "intelligence": {
                "risk_alerts": [{"message": "若跌破 47.50 建议卖出，需看公告。"}]
            },
        },
    )

    report = service.generate_dashboard_report([result], report_date="2026-04-29")

    assert "## 持仓后续复盘" in report
    assert "买入后的持仓跟踪" in report
    assert "| BHP (BHP.AX) | 持有观察 | 25.00% | 20.00% | +0.00 | 47.50 | 55.00 |" in report
    assert "| BHP (BHP.AX) | 持有观察 | 5.00% | 20.00% |" not in report
    assert "若跌破 47.50 需人工复核风险" in report
    assert "建议卖出" not in report
    assert "| BHP (BHP.AX) | 清仓 |" not in report


@patch("src.notification.get_db")
def test_holding_followup_keeps_explicit_reduce_risk_wording_for_reduce_action(mock_get_db):
    mock_get_db.return_value.get_portfolio_overview.return_value = _overview()
    service = _service()
    result = _result(
        code="BHP.AX",
        name="BHP",
        final_decision="SELL",
        position_action="REDUCE",
        current_weight=0.05,
        target_weight=0.10,
        delta_amount=-5000.0,
        risk_warning="若跌破 47.50 建议减仓，需看公告。",
        dashboard={
            "battle_plan": {
                "sniper_points": {
                    "stop_loss": "47.50",
                    "take_profit": "55.00",
                }
            },
            "intelligence": {
                "risk_alerts": [{"message": "若跌破 47.50 建议减仓，需看公告。"}]
            },
        },
    )

    report = service.generate_dashboard_report([result], report_date="2026-04-29")

    assert "| BHP (BHP.AX) | 减仓 | 25.00% | 10.00% | -5,000.00 | 47.50 | 55.00 |" in report
    assert "若跌破 47.50 建议减仓，需看公告。" in report
    assert "需人工复核风险，需看公告" not in report


@patch("src.notification.get_db")
def test_tiny_open_is_watch_across_dashboard_and_wechat_summaries(mock_get_db):
    mock_get_db.return_value.get_portfolio_overview.return_value = _overview()
    result = _result(
        code="ABC.AX",
        name="ABC",
        final_decision="BUY",
        position_action="OPEN",
        target_weight=0.10,
        delta_amount=0.60,
    )
    forbidden_action_text = ("买入:1", "建议买入 1", "今日买入 1")

    service = _service()
    dashboard_report = service.generate_dashboard_report([result], report_date="2026-04-29")
    summary = service.get_last_daily_decision_summary()

    assert summary["action_counts"]["total_actions"] == 0
    assert summary["action_counts"]["buy"] == 0
    assert summary["action_counts"]["hold_watch"] == 1
    assert "**今日动作数量**：买入 0 / 加仓 0 / 减仓 0 / 清仓 0 / 观察 1 / 阻断 0" in dashboard_report
    assert all(text not in dashboard_report for text in forbidden_action_text)

    summary_only_service = _service()
    summary_only_service._report_summary_only = True
    summary_only_report = summary_only_service.generate_dashboard_report([result], report_date="2026-04-29")

    assert all(text not in summary_only_report for text in forbidden_action_text)
    assert "OPEN" not in summary_only_report
    assert "买入/新开仓" not in summary_only_report

    wechat_service = _service()
    wechat_dashboard = wechat_service.generate_wechat_dashboard([result])
    wechat_summary = wechat_service.generate_wechat_summary([result])

    assert all(text not in wechat_dashboard for text in forbidden_action_text)
    assert all(text not in wechat_summary for text in forbidden_action_text)
    assert "买入/新开仓" not in wechat_dashboard
    assert "买入/新开仓" not in wechat_summary


@patch("src.notification.get_db")
def test_normal_open_is_counted_as_buy_action(mock_get_db):
    mock_get_db.return_value.get_portfolio_overview.return_value = _overview()
    service = _service()
    result = _result(
        code="CBA.AX",
        name="CBA",
        final_decision="BUY",
        position_action="OPEN",
        target_weight=0.10,
        delta_amount=2000.0,
    )

    report = service.generate_dashboard_report([result], report_date="2026-04-29")
    summary = service.get_last_daily_decision_summary()

    assert summary["action_counts"]["total_actions"] == 1
    assert summary["action_counts"]["buy"] == 1
    assert summary["action_counts"]["hold_watch"] == 0
    assert "**今日动作数量**：买入 1 / 加仓 0 / 减仓 0 / 清仓 0 / 观察 0 / 阻断 0" in report


@patch("src.notification.get_db")
def test_asx_suffix_alias_in_holdings_matches_ax_analysis(mock_get_db):
    mock_get_db.return_value.get_portfolio_overview.return_value = {
        "cash": 10000.0,
        "holdings": [
            {
                "code": "NHF.ASX",
                "name": "NHF",
                "quantity": 47,
                "market_value": 308.0,
            }
        ],
    }
    service = _service()

    report = service.generate_dashboard_report(
        [
            _result(
                code="NHF.AX",
                name="NHF",
                final_decision="HOLD",
                position_action="HOLD",
                current_weight=0.2,
                target_weight=0.2,
            )
        ],
        report_date="2026-04-29",
    )
    summary = service.get_last_daily_decision_summary()
    nhf_item = summary["watch_items"][0]

    assert summary["uncovered_holdings"] == []
    assert summary["data_quality_flags"] == []
    assert nhf_item["code"] == "NHF.AX"
    assert nhf_item["is_current_holding"] is True
    assert "NHF.ASX 当前持仓未覆盖今日分析" not in report
    assert "当前持仓有 **1** 只未覆盖分析" not in report


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
        "evidence_matrix",
        "evidence_summary",
        "report_reliability",
        "data_quality_snapshot",
        "backtest_confidence",
        "score_bucket_calibration",
        "risk_sizing_previews",
        "risk_sizing_comparison",
        "triage_card",
        "execution_checklist",
        "watch_trigger_rule",
    }
    assert set(summary.keys()) == expected_top_level_keys
    assert summary["schema_version"] == "daily_decision_summary.v1.8"
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
        "final_action_display",
    }
    assert summary["actionable_items"][0]["final_action_display"]["actionability"] == "actionable"
    assert set(summary["actionable_items"][0]["final_action_display"]).issuperset(
        {"review_reasons", "confirmation_gap", "review_label", "display_only"}
    )
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
        "final_action_display",
        "trigger",
    }
    assert summary["watch_items"][0]["final_action_display"]["actionability"] == "watch_only"

    assert [item["code"] for item in summary["blocked_items"]] == ["NAB.AX"]
    assert set(summary["blocked_items"][0].keys()) == {
        "code",
        "name",
        "reason",
        "current_weight",
        "target_weight",
        "price_basis",
        "final_action_display",
    }
    assert summary["blocked_items"][0]["final_action_display"]["actionability"] == "blocked"
    assert summary["blocked_items"][0]["final_action_display"]["can_show_sizing"] is False


@patch("src.notification.get_db")
def test_data_quality_snapshot_summarizes_free_inputs_without_changing_actions(mock_get_db):
    mock_get_db.return_value.get_portfolio_overview.return_value = _overview()
    service = _service()
    results = [
        _result(
            code="BHP.AX",
            name="BHP",
            final_decision="BUY",
            position_action="ADD",
            current_weight=0.20,
            target_weight=0.25,
            delta_amount=2500.0,
            news_summary="No material overnight news.",
            market_snapshot={
                "date": "2026-04-28",
                "close": "50.00",
                "source": "yfinance",
                "valuation_snapshot": {
                    "source": "yfinance",
                    "as_of_date": "2026-04-28",
                    "pe_ttm": 14.2,
                    "pb": 1.7,
                    "dividend_yield": 0.048,
                },
            },
        ),
        _result(
            code="CBA.AX",
            name="CBA",
            final_decision="HOLD",
            position_action="HOLD",
            market_snapshot={"close": "100.00", "source": "yfinance"},
            news_summary="",
            fundamental_analysis="",
            company_highlights="",
        ),
        _result(
            code="RIO.AX",
            name="RIO",
            success=False,
            error_message="snapshot timeout",
        ),
    ]

    report = service.generate_dashboard_report(results, report_date="2026-04-29")
    summary = service.get_last_daily_decision_summary()
    snapshot = summary["data_quality_snapshot"]

    assert summary["action_counts"]["total_actions"] == 1
    assert summary["action_counts"]["add"] == 1
    assert snapshot["display_only"] is True
    assert snapshot["free_sources"] == [
        "market_snapshot",
        "valuation_snapshot",
        "evidence_matrix",
        "report_reliability",
    ]
    assert snapshot["counts"]["successful_count"] == 2
    assert snapshot["counts"]["failed_count"] == 1
    assert snapshot["market_data"]["available_count"] == 1
    assert snapshot["market_data"]["missing_or_stale_count"] == 1
    assert snapshot["valuation"]["available_count"] == 1
    assert snapshot["valuation"]["field_coverage"]["pe_ttm"] == 1
    assert snapshot["valuation"]["field_coverage"]["pb"] == 1
    assert snapshot["valuation"]["field_coverage"]["dividend_yield"] == 1
    assert snapshot["news"]["missing_or_stale_count"] == 1
    assert any(item["code"] == "analysis_failed" for item in snapshot["attention"])
    assert "**免费数据质量快照**" in report
    assert "| 估值 | 1/2 基本面/辅助证据可用；核心估值字段覆盖" in report
    assert report.index("**免费数据质量快照**") < report.index("\n---\n")


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
    assert "昨收数据计划 / 开盘前参考" in html
    assert "开盘后确认价格" in html
    assert "<table>" in html
    assert "border-radius: 8px" in html
    assert "background: #f7f9fc" in html
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


def test_report_archive_filename_preserves_rendered_report_date_across_close(monkeypatch, tmp_path: Path):
    service = _service()
    timestamps = iter(
        [
            datetime(2026, 3, 30, 15, 59, tzinfo=ZoneInfo("Australia/Sydney")),
            datetime(2026, 3, 30, 16, 1, tzinfo=ZoneInfo("Australia/Sydney")),
        ]
    )
    monkeypatch.setattr(service, "_now_in_report_tz", lambda: next(timestamps))

    report = service.generate_dashboard_report(
        [_result(market_snapshot={"date": "2026-03-27", "close": "50.00", "source": "yfinance"})]
    )
    md_path = Path(service.save_report_to_file(report, reports_dir=tmp_path))
    html_path = Path(service.save_report_archive_html(report, reports_dir=tmp_path))

    assert report.startswith("# 🎯 2026-03-30 决策仪表盘")
    assert "技术基准日 2026-03-27" in report
    assert md_path.name == "report_20260330.md"
    assert html_path.name == "report_20260330.html"


def test_daily_decision_summary_filename_preserves_explicit_report_date(monkeypatch, tmp_path: Path):
    service = _service()
    monkeypatch.setattr(
        service,
        "_now_in_report_tz",
        lambda: datetime(2026, 4, 30, 1, 15, tzinfo=ZoneInfo("Australia/Sydney")),
    )

    summary_path = Path(
        service.save_daily_decision_summary_to_file({"report_date": "2026-04-29"}, reports_dir=tmp_path)
    )

    assert summary_path.name == "daily_decision_summary_20260429.json"


def test_default_dashboard_report_date_uses_report_run_date_with_technical_basis(monkeypatch):
    service = _service()
    monkeypatch.setattr(
        service,
        "_now_in_report_tz",
        lambda: datetime(2026, 3, 30, 8, 30, tzinfo=ZoneInfo("Australia/Sydney")),
    )

    report = service.generate_dashboard_report(
        [_result(market_snapshot={"date": "2026-03-27", "close": "50.00", "source": "yfinance"})]
    )
    daily_summary = service.get_last_daily_decision_summary()

    assert report.startswith("# 🎯 2026-03-30 决策仪表盘")
    assert "**价格来源**：全部使用昨收数据；技术基准日 2026-03-27" in report
    assert daily_summary["report_date"] == "2026-03-30"
    assert daily_summary["technical_basis_date"] == "2026-03-27"


def test_default_wechat_report_dates_use_report_run_date(monkeypatch):
    service = _service()
    monkeypatch.setattr(
        service,
        "_now_in_report_tz",
        lambda: datetime(2026, 3, 30, 8, 30, tzinfo=ZoneInfo("Australia/Sydney")),
    )

    result = _result(market_snapshot={"date": "2026-03-27", "close": "50.00", "source": "yfinance"})
    dashboard = service.generate_wechat_dashboard([result])
    summary = service.generate_wechat_summary([result])

    assert dashboard.startswith("## 🎯 2026-03-30 决策仪表盘")
    assert summary.startswith("## 📅 2026-03-30 股票分析报告")
    assert "技术基准日 2026-03-27" in dashboard
    assert "2026-03-27 日线（收盘口径）" in summary
    assert "reports/report_20260330.md" in summary
    assert service.get_last_daily_decision_summary()["report_date"] == "2026-03-30"


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
