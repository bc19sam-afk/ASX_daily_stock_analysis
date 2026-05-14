# -*- coding: utf-8 -*-
"""Daily decision summary evidence matrix integration tests."""

from datetime import datetime
from zoneinfo import ZoneInfo

from src.analyzer import AnalysisResult
from src.daily_decision_summary import build_daily_decision_summary, render_preopen_decision_dashboard
from src.notification import NotificationService


def _result(**overrides) -> AnalysisResult:
    backtest_summary = overrides.pop("backtest_summary", None)
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
    result = AnalysisResult(**base)
    if backtest_summary is not None:
        result.backtest_summary = backtest_summary
    return result


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


def test_evidence_gaps_feed_review_reasons_without_changing_summary_actions():
    result = _result(
        code="BHP.AX",
        final_decision="BUY",
        position_action="ADD",
        current_weight=0.2,
        target_weight=0.25,
        delta_amount=2500.0,
        fundamental_analysis="",
        news_summary="",
    )

    summary = _summary([result])
    item = summary["actionable_items"][0]
    review_reasons = item["final_action_display"]["review_reasons"]

    assert summary["action_counts"]["add"] == 1
    assert summary["action_counts"]["blocked"] == 0
    assert item["position_action"] == "ADD"
    assert item["target_weight"] == 0.25
    assert item["delta_amount"] == 2500.0
    assert "公告未检查，执行前复核" not in review_reasons
    assert "回测证据未检查" in review_reasons
    assert "估值覆盖缺口" in review_reasons
    assert item["final_action_display"]["confirmation_gap"] is True

    evidence = _by_category(summary["evidence_matrix"]["BHP.AX"])
    assert "announcement" not in evidence
    assert evidence["valuation"]["status"] == "missing"
    assert evidence["backtest"]["status"] == "not_checked"

    dashboard = "\n".join(render_preopen_decision_dashboard(summary))
    assert "无 validation BLOCK；但仍可能存在回测 / 估值覆盖缺口。" in dashboard
    assert "未发现阻断（BLOCK）或数据质量风险" not in dashboard


def test_blocked_report_with_evidence_gaps_does_not_claim_no_validation_block():
    actionable = _result(
        code="BHP.AX",
        final_decision="BUY",
        position_action="ADD",
        current_weight=0.2,
        target_weight=0.25,
        delta_amount=2500.0,
        fundamental_analysis="",
        news_summary="",
    )
    blocked = _result(
        code="NAB.AX",
        validation_status="BLOCK",
        validation_issues=["收盘价缺失，无法确认昨收计划。"],
        news_summary="",
        fundamental_analysis="",
    )

    summary = _summary([actionable, blocked])
    dashboard = "\n".join(render_preopen_decision_dashboard(summary))

    assert summary["action_counts"]["add"] == 1
    assert summary["action_counts"]["blocked"] == 1
    assert "1 只股票被阻断（BLOCK），已从可执行动作中排除。" in dashboard
    assert "存在回测 / 估值覆盖缺口，BLOCK 标的解除前仍只观察。" in dashboard
    assert "无 validation BLOCK；但仍可能存在公告 / 回测 / 估值覆盖缺口。" not in dashboard


def test_ai_observe_and_technical_weakness_feed_review_reasons_without_changing_counts():
    add_item = _result(
        code="LAU.AX",
        name="LAU",
        final_decision="BUY",
        position_action="ADD",
        current_weight=0.17,
        target_weight=0.22,
        delta_amount=5000.0,
        operation_advice="观望 / 持有，等待确认",
        trend_prediction="震荡",
        technical_analysis="均线缠绕，趋势弱，量能弱",
        fundamental_analysis="估值稳定",
        news_summary="无重大新增风险",
        backtest_summary={"sample_size": 30, "win_rate_pct": 55},
    )
    open_item = _result(
        code="NHF.AX",
        name="NHF",
        final_decision="BUY",
        position_action="OPEN",
        current_weight=0.0,
        target_weight=0.10,
        delta_amount=10000.0,
        operation_advice="震荡，条件化观察，非现价买入理由",
        trend_prediction="震荡",
        technical_analysis="非多头排列",
        fundamental_analysis="估值稳定",
        news_summary="无重大新增风险",
        backtest_summary={"sample_size": 30, "win_rate_pct": 55},
    )

    summary = _summary([add_item, open_item])
    lau = next(item for item in summary["actionable_items"] if item["code"] == "LAU.AX")
    nhf = next(item for item in summary["actionable_items"] if item["code"] == "NHF.AX")

    assert summary["action_counts"]["add"] == 1
    assert summary["action_counts"]["buy"] == 1
    assert summary["action_counts"]["total_actions"] == 2
    assert lau["position_action"] == "ADD"
    assert nhf["position_action"] == "OPEN"
    assert "AI 补充偏观望，需二次确认" in lau["final_action_display"]["review_reasons"]
    assert "技术确认偏弱，需条件复核" in lau["final_action_display"]["review_reasons"]
    assert lau["final_action_display"]["confirmation_gap"] is True
    assert "AI 补充偏观望，需二次确认" in nhf["final_action_display"]["review_reasons"]
    assert "技术确认偏弱，需条件复核" in nhf["final_action_display"]["review_reasons"]
    assert nhf["final_action_display"]["confirmation_gap"] is True


def test_strong_consistent_action_is_not_marked_as_weak_confirmation():
    result = _result(
        code="GMG.AX",
        name="GMG",
        final_decision="BUY",
        position_action="ADD",
        current_weight=0.18,
        target_weight=0.22,
        delta_amount=4000.0,
        operation_advice="看多，按计划复核",
        trend_prediction="强势上行",
        technical_analysis="多头排列，量能充足",
        fundamental_analysis="估值稳定",
        news_summary="无重大新增风险",
        backtest_summary={"sample_size": 30, "win_rate_pct": 55},
    )

    summary = _summary([result])
    display = summary["actionable_items"][0]["final_action_display"]

    assert summary["action_counts"]["add"] == 1
    assert summary["action_counts"]["total_actions"] == 1
    assert display["confirmation_gap"] is False
    assert "AI 补充偏观望，需二次确认" not in display["review_reasons"]
    assert "技术确认偏弱，需条件复核" not in display["review_reasons"]
    assert "风险仓位试算与目标仓位差异较大" not in display["review_reasons"]
    assert display["review_reasons"] == []


def test_daily_summary_matches_asx_suffix_alias_in_raw_overview():
    result = _result(
        code="NHF.AX",
        name="NHF",
        final_decision="HOLD",
        position_action="HOLD",
        current_weight=0.2,
        target_weight=0.2,
    )

    summary = build_daily_decision_summary(
        results=[result],
        report_date="2026-04-29",
        generated_at=datetime(2026, 4, 29, 7, 30, tzinfo=ZoneInfo("Australia/Sydney")),
        overview={"cash": 10000.0, "holdings": [{"code": "NHF.ASX", "weight": 0.2}]},
        get_primary_action_model=_model,
        classify_price_basis=lambda item: item.execution_price_source,
        format_stock_display_name=lambda name, code: f"{name} ({code})",
        format_validation_issue_text=lambda item: "；".join(item.validation_issues or []),
    )

    assert summary["uncovered_holdings"] == []
    assert summary["watch_items"][0]["code"] == "NHF.AX"
    assert summary["watch_items"][0]["is_current_holding"] is True
    assert not any(flag["code"] == "uncovered_holding" for flag in summary["data_quality_flags"])
    evidence = _by_category(summary["evidence_matrix"]["NHF.AX"])
    assert evidence["portfolio"]["status"] == "available"
    assert evidence["portfolio"]["source"] == "portfolio_overview"


def test_data_quality_snapshot_uses_asx_alias_for_evidence_lookup():
    result = _result(
        code="NHF.ASX",
        name="NHF",
        final_decision="HOLD",
        position_action="HOLD",
        current_weight=0.2,
        target_weight=0.2,
        market_snapshot={"date": "2026-04-28", "close": "6.58", "source": "yfinance"},
    )

    summary = build_daily_decision_summary(
        results=[result],
        report_date="2026-04-29",
        generated_at=datetime(2026, 4, 29, 7, 30, tzinfo=ZoneInfo("Australia/Sydney")),
        overview={"cash": 10000.0, "holdings": [{"code": "NHF.AX", "weight": 0.2}]},
        get_primary_action_model=_model,
        classify_price_basis=lambda item: item.execution_price_source,
        format_stock_display_name=lambda name, code: f"{name} ({code})",
        format_validation_issue_text=lambda item: "；".join(item.validation_issues or []),
    )

    assert set(summary["evidence_matrix"].keys()) == {"NHF.AX"}
    assert summary["data_quality_snapshot"]["market_data"]["available_count"] == 1
    assert summary["data_quality_snapshot"]["market_data"]["missing_or_stale_count"] == 0
    assert summary["data_quality_snapshot"]["market_data"]["attention"] == []


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
    assert "ASX 官方公告：未检查" not in report
    assert "validation block" in report
    assert "## 个股证据矩阵" in report
    assert "| 标的 | 类别 | 来源 | 时间 | 状态 | 说明 |" in report
    assert "not_checked" in report
