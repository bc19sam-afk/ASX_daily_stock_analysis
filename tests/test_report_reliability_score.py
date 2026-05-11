# -*- coding: utf-8 -*-
"""Report reliability score contract tests."""

from datetime import datetime
from zoneinfo import ZoneInfo

from src.analyzer import AnalysisResult
from src.daily_decision_summary import build_daily_decision_summary
from src.notification import NotificationService
from src.report_reliability import build_report_reliability, normalize_reliability_reason


def _result(**overrides) -> AnalysisResult:
    backtest_summary = overrides.pop("backtest_summary", {"sample_size": 30, "win_rate_pct": 55})
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
        validation_status="PASS",
    )
    base.update(overrides)
    result = AnalysisResult(**base)
    result.backtest_summary = backtest_summary
    return result


def _model(result):
    return {
        "position_action": result.position_action,
        "target_weight": result.target_weight,
        "delta_amount": result.delta_amount,
    }


def _summary(results, *, classify_price_basis=None):
    return build_daily_decision_summary(
        results=results,
        report_date="2026-04-29",
        generated_at=datetime(2026, 4, 29, 7, 30, tzinfo=ZoneInfo("Australia/Sydney")),
        overview={"cash": 10000.0, "holdings": [{"code": "BHP.AX", "weight": 0.2}]},
        get_primary_action_model=_model,
        classify_price_basis=classify_price_basis or (lambda result: result.execution_price_source),
        format_stock_display_name=lambda name, code: f"{name} ({code})",
        format_validation_issue_text=lambda result: "；".join(result.validation_issues or []),
    )


def test_reliability_is_high_when_close_only_and_evidence_complete():
    summary = _summary([_result(code="BHP.AX"), _result(code="CBA.AX")])

    reliability = summary["report_reliability"]

    assert reliability["score"] >= 80
    assert reliability["level"] == "high"
    assert reliability["components"]["price_basis_consistency"] == 20
    assert reliability["components"]["market_data_freshness"] == 20


def test_validation_block_deducts_without_changing_actions_or_block_semantics():
    baseline = _summary(
        [
            _result(code="BHP.AX", final_decision="BUY", position_action="ADD", current_weight=0.2, target_weight=0.25, delta_amount=2500.0),
            _result(code="NAB.AX", validation_status="BLOCK", validation_issues=["收盘价缺失，无法确认昨收计划。"], position_action="ADD", delta_amount=6000.0),
        ]
    )

    reliability = baseline["report_reliability"]

    assert reliability["score"] < 80
    assert any(flag["code"] == "validation_block" for flag in reliability["flags"])
    assert baseline["action_counts"]["add"] == 1
    assert baseline["action_counts"]["blocked"] == 1
    assert [item["code"] for item in baseline["actionable_items"]] == ["BHP.AX"]
    assert [item["code"] for item in baseline["blocked_items"]] == ["NAB.AX"]


def test_missing_news_and_evidence_reduce_reliability():
    complete = _summary([_result(code="BHP.AX")])["report_reliability"]["score"]
    missing = _summary(
        [
            _result(
                code="BHP.AX",
                market_snapshot={"close": "50.00", "source": "yfinance"},
                news_summary="",
                fundamental_analysis="",
            )
        ]
    )["report_reliability"]

    assert missing["score"] < complete
    assert missing["components"]["market_data_freshness"] < 20
    assert any(flag["code"] == "evidence_missing" for flag in missing["flags"])


def test_mixed_or_non_close_only_price_policy_reduces_reliability():
    summary = _summary(
        [
            _result(code="BHP.AX", execution_price_source="close_only"),
            _result(code="CBA.AX", execution_price_source="realtime"),
        ]
    )

    reliability = summary["report_reliability"]

    assert summary["price_policy"] == "mixed"
    assert reliability["components"]["price_basis_consistency"] < 20
    assert any(flag["code"] == "price_basis_mismatch" for flag in reliability["flags"])


def test_low_reliability_report_renders_observe_only_warning(monkeypatch):
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
            _result(
                code="NAB.AX",
                validation_status="BLOCK",
                validation_issues=["收盘价缺失，无法确认昨收计划。"],
                execution_price_source="realtime",
                market_snapshot={},
                technical_analysis="",
                fundamental_analysis="",
                news_summary="",
                backtest_summary={},
            )
        ],
        report_date="2026-04-29",
    )

    assert "报告可信度：" in report
    assert "仅观察" in report
    assert "报告可信度偏低：不建议直接依据本报告执行，仅用于观察和人工复核。" in report


def test_homepage_reliability_ignores_absent_announcement_source_but_keeps_backtest_gap(monkeypatch):
    service = NotificationService.__new__(NotificationService)
    service._report_summary_only = False
    service._report_timezone = "Australia/Sydney"
    service._last_daily_decision_summary = None
    monkeypatch.setattr(
        "src.notification.get_db",
        lambda: type("DB", (), {"get_portfolio_overview": lambda self: {"cash": 10000.0, "holdings": []}})(),
    )
    results = [_result(code=f"T{i:02d}.AX", name=f"T{i:02d}", backtest_summary={}) for i in range(14)]

    report = service.generate_dashboard_report(results, report_date="2026-05-08")

    assert "可直接作为开盘前计划" not in report
    assert "**报告可信度**：96/100，可作为开盘前人工复核计划" in report
    assert "等级：可作为开盘前人工复核计划（high）" in report
    assert "ASX 官方公告未检查" not in report
    assert "ASX 官方公告：未检查" not in report
    assert "14/14 只股票回测证据未检查" in report


def test_reliability_reason_cleanup_strips_common_ascii_and_chinese_punctuation():
    assert normalize_reliability_reason("External source unavailable.") == "External source unavailable"
    assert normalize_reliability_reason("External source unavailable,") == "External source unavailable"
    assert normalize_reliability_reason("External source unavailable!") == "External source unavailable"
    assert normalize_reliability_reason("External source unavailable?") == "External source unavailable"
    assert normalize_reliability_reason("公告未检查。") == "公告未检查"


def test_report_reliability_builder_does_not_need_action_fields():
    reliability = build_report_reliability(
        price_policy="close_only",
        price_basis_counts={"close_only": 1, "latest_close": 0, "realtime": 0},
        evidence_matrix={
            "BHP.AX": [
                {"category": "market_data", "status": "available", "severity": "info"},
                {"category": "technical", "status": "available", "severity": "info"},
                {"category": "valuation", "status": "available", "severity": "info"},
                {"category": "news", "status": "available", "severity": "info"},
                {"category": "backtest", "status": "not_checked", "severity": "warning"},
                {"category": "validation", "status": "available", "severity": "info"},
            ]
        },
        evidence_summary={"stock_count": 1, "market_data_available": 1, "market_data_missing_or_stale": 0, "backtest_not_checked": 1, "validation_block": 0},
        data_quality_flags=[],
    )

    assert set(reliability) == {"score", "level", "components", "flags"}
    assert reliability["flags"][0]["code"] == "backtest_not_checked"
