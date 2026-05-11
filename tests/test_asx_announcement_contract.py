# -*- coding: utf-8 -*-
"""ASX official announcement check contract tests."""

from datetime import datetime
from zoneinfo import ZoneInfo

from src.analyzer import AnalysisResult
from src.asx_announcements import ASXAnnouncementCheck, build_asx_announcement_check
from src.daily_decision_summary import build_daily_decision_summary
from src.evidence_matrix import build_evidence_matrix, summarize_evidence_matrix
from src.report_reliability import build_report_reliability


def _result(**overrides) -> AnalysisResult:
    backtest_summary = overrides.pop("backtest_summary", None)
    base = dict(
        code="BHP.AX",
        name="BHP",
        sentiment_score=70,
        trend_prediction="震荡上行",
        operation_advice="按计划观察",
        final_decision="BUY",
        position_action="ADD",
        current_weight=0.2,
        target_weight=0.25,
        delta_amount=2500.0,
        execution_price_source="close_only",
        market_snapshot={"date": "2026-05-05", "close": "50.00", "source": "yfinance"},
        technical_analysis="MA10 支撑仍在",
        fundamental_analysis="估值稳定",
        news_summary="无重大新增风险",
        action_reason="等待触发条件",
        validation_status="PASS",
    )
    base.update(overrides)
    result = AnalysisResult(**base)
    if backtest_summary is not None:
        result.backtest_summary = backtest_summary
    return result


def _by_category(entries):
    return {entry["category"]: entry for entry in entries}


def _model(result):
    return {
        "position_action": result.position_action,
        "target_weight": result.target_weight,
        "delta_amount": result.delta_amount,
    }


def test_default_announcement_check_is_not_checked_not_clear():
    check = build_asx_announcement_check("BHP.AX")

    assert check.code == "BHP.AX"
    assert check.checked is False
    assert check.status == "not_checked"
    assert check.has_price_sensitive_item is None
    assert check.to_dict()["status"] == "not_checked"
    assert "无公告" not in check.reason
    assert "clear" not in check.reason.lower()


def test_evidence_matrix_preserves_announcement_statuses_without_clear_fallback():
    matrix = build_evidence_matrix(
        results=[
            _result(code="BHP.AX"),
            _result(code="CBA.AX"),
            _result(code="NAB.AX"),
        ],
        overview={"holdings": []},
        classify_price_basis=lambda result: "close_only",
        format_validation_issue_text=lambda result: "",
        announcement_checks={
            "BHP.AX": ASXAnnouncementCheck(
                code="BHP.AX",
                checked=True,
                source="asx_contract_test",
                checked_at="2026-05-06T08:00:00+10:00",
                has_price_sensitive_item=False,
                status="clear",
                reason="已检查，未发现已标记的 price-sensitive 风险。",
            ),
            "CBA.AX": ASXAnnouncementCheck(
                code="CBA.AX",
                checked=False,
                source="asx_contract_test",
                status="unavailable",
                reason="ASX announcement source unavailable.",
            ),
            "NAB.AX": ASXAnnouncementCheck(
                code="NAB.AX",
                checked=True,
                source="asx_contract_test",
                checked_at="2026-05-06T08:05:00+10:00",
                has_price_sensitive_item=True,
                latest_items=[{"title": "Trading halt", "published_at": "2026-05-06T08:00:00+10:00"}],
                status="risk_found",
                reason="检测到 price-sensitive 公告风险。",
            ),
        },
    )

    bhp = _by_category(matrix["BHP.AX"])["announcement"]
    cba = _by_category(matrix["CBA.AX"])["announcement"]
    nab = _by_category(matrix["NAB.AX"])["announcement"]

    assert bhp["status"] == "clear"
    assert bhp["severity"] == "info"
    assert cba["status"] == "unavailable"
    assert cba["severity"] == "warning"
    assert "clear" not in cba["details"].lower()
    assert nab["status"] == "risk_found"
    assert nab["severity"] == "block"
    assert "Trading halt" in nab["details"]


def test_evidence_summary_counts_announcement_statuses():
    matrix = build_evidence_matrix(
        results=[_result(code="BHP.AX"), _result(code="CBA.AX")],
        overview={"holdings": []},
        classify_price_basis=lambda result: "close_only",
        format_validation_issue_text=lambda result: "",
        announcement_checks={
            "BHP.AX": build_asx_announcement_check("BHP.AX"),
            "CBA.AX": ASXAnnouncementCheck(code="CBA.AX", checked=False, status="unavailable", reason="source down"),
        },
    )

    summary = summarize_evidence_matrix(matrix)

    assert summary["announcement_not_checked"] == 1
    assert summary["announcement_unavailable"] == 1
    assert summary["announcement_risk_found"] == 0


def test_report_reliability_flags_announcement_not_checked_unavailable_and_risk_found():
    reliability = build_report_reliability(
        price_policy="close_only",
        price_basis_counts={"close_only": 3},
        evidence_matrix={
            "BHP.AX": [{"category": "announcement", "status": "not_checked", "severity": "warning"}],
            "CBA.AX": [{"category": "announcement", "status": "unavailable", "severity": "warning"}],
            "NAB.AX": [{"category": "announcement", "status": "risk_found", "severity": "block"}],
        },
        evidence_summary={
            "stock_count": 3,
            "market_data_available": 3,
            "validation_block": 0,
            "announcement_not_checked": 1,
            "announcement_unavailable": 1,
            "announcement_risk_found": 1,
        },
        data_quality_flags=[],
    )

    flag_codes = {flag["code"] for flag in reliability["flags"]}

    assert "asx_announcement_not_checked" in flag_codes
    assert "asx_announcement_unavailable" in flag_codes
    assert "asx_announcement_risk_found" in flag_codes
    assert reliability["components"]["evidence_completeness"] < 25


def test_daily_summary_announcement_contract_does_not_change_actions():
    results = [
        _result(code="BHP.AX"),
        _result(
            code="NAB.AX",
            validation_status="BLOCK",
            validation_issues=["收盘价缺失，无法确认昨收计划。"],
        ),
    ]

    summary = build_daily_decision_summary(
        results=results,
        report_date="2026-05-06",
        generated_at=datetime(2026, 5, 6, 7, 30, tzinfo=ZoneInfo("Australia/Sydney")),
        overview={"cash": 10000.0, "holdings": []},
        get_primary_action_model=_model,
        classify_price_basis=lambda result: "close_only",
        format_stock_display_name=lambda name, code: f"{name} ({code})",
        format_validation_issue_text=lambda result: "；".join(result.validation_issues or []),
    )

    assert summary["action_counts"]["add"] == 1
    assert summary["action_counts"]["blocked"] == 1
    assert summary["actionable_items"][0]["code"] == "BHP.AX"
    assert summary["blocked_items"][0]["code"] == "NAB.AX"
    assert summary["actionable_items"][0]["target_weight"] == 0.25
    assert summary["actionable_items"][0]["delta_amount"] == 2500.0
    assert "announcement" not in _by_category(summary["evidence_matrix"]["BHP.AX"])


def test_default_announcement_not_checked_is_hidden_from_daily_review_reasons():
    result = _result(
        code="BHP.AX",
        operation_advice="看多，按计划复核",
        trend_prediction="强势上行",
        technical_analysis="多头排列，量能充足",
        fundamental_analysis="估值稳定",
        news_summary="无重大新增风险",
        backtest_summary={"sample_size": 30, "win_rate_pct": 55},
    )

    summary = build_daily_decision_summary(
        results=[result],
        report_date="2026-05-06",
        generated_at=datetime(2026, 5, 6, 7, 30, tzinfo=ZoneInfo("Australia/Sydney")),
        overview={"cash": 10000.0, "holdings": []},
        get_primary_action_model=_model,
        classify_price_basis=lambda result: "close_only",
        format_stock_display_name=lambda name, code: f"{name} ({code})",
        format_validation_issue_text=lambda result: "；".join(result.validation_issues or []),
    )

    item = summary["actionable_items"][0]
    assert summary["action_counts"]["add"] == 1
    assert summary["action_counts"]["blocked"] == 0
    assert [blocked["code"] for blocked in summary["blocked_items"]] == []
    assert item["code"] == "BHP.AX"
    assert item["position_action"] == "ADD"
    assert "announcement" not in _by_category(summary["evidence_matrix"]["BHP.AX"])
    assert "公告未检查，执行前复核" not in item["final_action_display"]["review_reasons"]
    assert item["final_action_display"]["confirmation_gap"] is False
