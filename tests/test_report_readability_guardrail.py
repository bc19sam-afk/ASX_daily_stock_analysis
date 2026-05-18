# -*- coding: utf-8 -*-
"""Guardrails for the compact first-screen daily dashboard report."""

from pathlib import Path
from unittest.mock import patch

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
        technical_analysis="MA10 支撑仍在",
        fundamental_analysis="估值稳定",
        news_summary="暂无重大新增风险",
    )
    base.update(overrides)
    return AnalysisResult(**base)


def _overview():
    return {
        "cash": 20000.0,
        "equity_value": 80000.0,
        "total_value": 100000.0,
        "holdings": [
            {"code": "BHP.AX", "name": "BHP", "quantity": 100, "market_value": 20000.0, "weight": 0.20},
            {"code": "CSL.AX", "name": "CSL", "quantity": 40, "market_value": 18000.0, "weight": 0.18},
            {"code": "TLS.AX", "name": "TLS", "quantity": 1500, "market_value": 12000.0, "weight": 0.12},
            {"code": "WOW.AX", "name": "WOW", "quantity": 80, "market_value": 6000.0, "weight": 0.06},
        ],
    }


def _readability_results():
    return [
        _result(
            code="BHP.AX",
            name="BHP",
            final_decision="BUY",
            position_action="ADD",
            current_weight=0.20,
            target_weight=0.24,
            delta_amount=4000.0,
            data_quality_flag="STALE_NEWS",
        ),
        _result(
            code="CSL.AX",
            name="CSL",
            final_decision="SELL",
            position_action="REDUCE",
            current_weight=0.18,
            target_weight=0.12,
            delta_amount=-6000.0,
        ),
        _result(
            code="TLS.AX",
            name="TLS",
            final_decision="SELL",
            position_action="CLOSE",
            current_weight=0.12,
            target_weight=0.0,
            delta_amount=-12000.0,
        ),
        _result(
            code="CBA.AX",
            name="CBA",
            final_decision="BUY",
            position_action="OPEN",
            target_weight=0.10,
            delta_amount=10000.0,
            market_snapshot={"date": "2026-04-27", "close": "100.00", "source": "yfinance"},
        ),
        _result(
            code="WBC.AX",
            name="WBC",
            final_decision="BUY",
            position_action="OPEN",
            target_weight=0.08,
            delta_amount=8000.0,
        ),
        _result(
            code="MQG.AX",
            name="MQG",
            final_decision="BUY",
            position_action="ADD",
            target_weight=0.09,
            delta_amount=9000.0,
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
            target_weight=0.11,
            delta_amount=11000.0,
            validation_status="BLOCK",
            validation_issues=["收盘价缺失，无法确认昨收计划。"],
            news_summary="",
            fundamental_analysis="",
        ),
        _result(
            code="RIO.AX",
            name="RIO",
            success=False,
            error_message="snapshot timeout",
        ),
    ]


def _may14_overview():
    return {
        "cash": 1940.37,
        "equity_value": 8083.42,
        "total_value": 10023.79,
        "holdings": [
            {"code": "SHL.AX", "name": "SHL", "quantity": 172, "market_value": 3251.0, "weight": 0.3243},
            {"code": "NHF.ASX", "name": "NHF", "quantity": 308, "market_value": 2026.0, "weight": 0.2022},
            {"code": "LAU.AX", "name": "LAU", "quantity": 2958, "market_value": 1804.0, "weight": 0.1800},
            {"code": "GMG.AX", "name": "GMG", "quantity": 32, "market_value": 1002.0, "weight": 0.0999},
        ],
    }


def _may14_report_results():
    return [
        _result(
            code="GMG.AX",
            name="GOOD GROUP [GMG]",
            final_decision="BUY",
            position_action="ADD",
            current_weight=0.0999,
            target_weight=0.1404,
            delta_amount=532.10,
            sentiment_score=88,
            operation_advice="解释性分类：持有/加仓（基于趋势确认，非执行指令）",
            trend_prediction="强烈看多",
            technical_analysis="多头排列稳固，趋势强度 95/100",
            market_snapshot={"date": "2026-05-13", "close": "31.30", "source": "yfinance"},
            stop_loss=30.16,
        ),
        _result(
            code="LAU.AX",
            name="LINDSAY AU [LAU]",
            final_decision="BUY",
            position_action="ADD",
            current_weight=0.1800,
            target_weight=0.2184,
            delta_amount=535.58,
            sentiment_score=52,
            operation_advice="观望",
            trend_prediction="震荡",
            technical_analysis="均线缠绕，技术确认偏弱",
            market_snapshot={"date": "2026-05-13", "close": "0.61", "source": "yfinance"},
            stop_loss=0.59,
        ),
        _result(
            code="NHF.AX",
            name="NIBHOLDING [NHF]",
            final_decision="HOLD",
            position_action="HOLD",
            current_weight=0.2022,
            target_weight=0.2022,
            delta_amount=0.0,
            sentiment_score=42,
            operation_advice="观望",
            trend_prediction="震荡",
            technical_analysis="技术面偏空",
            market_snapshot={"date": "2026-05-13", "close": "6.58", "source": "yfinance"},
        ),
        _result(
            code="SHL.AX",
            name="SONIC HLTH [SHL]",
            final_decision="HOLD",
            position_action="HOLD",
            current_weight=0.3243,
            target_weight=0.3243,
            delta_amount=0.0,
            sentiment_score=42,
            operation_advice="观望",
            trend_prediction="震荡",
            technical_analysis="空头排列向震荡格局转换",
            market_snapshot={"date": "2026-05-13", "close": "18.90", "source": "yfinance"},
        ),
        _result(
            code="BHP.AX",
            name="BHP GROUP [BHP]",
            market_snapshot={"date": "2026-05-13", "close": "61.52", "source": "yfinance"},
        ),
        _result(
            code="SXE.AX",
            name="STH X ELEC [SXE]",
            market_snapshot={"date": "2026-05-13", "close": "4.24", "source": "yfinance"},
        ),
    ]


def _may18_no_action_overview():
    return {
        "cash": 36.49,
        "equity_value": 10140.48,
        "total_value": 10176.97,
        "holdings": [
            {"code": "GMG.AX", "name": "GOOD GROUP [GMG]", "quantity": 32, "market_value": 1000.0, "weight": 0.0983},
            {"code": "NHF.AX", "name": "NIBHOLDING [NHF]", "quantity": 308, "market_value": 2020.0, "weight": 0.1985},
            {"code": "XRO.AX", "name": "XERO [XRO]", "quantity": 14, "market_value": 2071.0, "weight": 0.2035},
        ],
    }


def _may18_no_action_results():
    return [
        _result(
            code="GMG.AX",
            name="GOOD GROUP [GMG]",
            sentiment_score=72,
            operation_advice="持有/观望",
            trend_prediction="震荡",
            analysis_summary="继续观察资金流，不新增仓位。",
            buy_reason="趋势仍未重新转强，先复核开盘承接。",
            risk_warning="外盘走弱可能拖累开盘情绪。",
            final_decision="HOLD",
            position_action="HOLD",
            current_weight=0.0983,
            target_weight=0.0983,
            delta_amount=0.0,
            market_snapshot={"date": "2026-05-15", "close": "31.30", "source": "yfinance"},
        ),
        _result(
            code="NHF.AX",
            name="NIBHOLDING [NHF]",
            sentiment_score=61,
            operation_advice="观望",
            trend_prediction="震荡偏弱",
            analysis_summary="持仓继续观察，等待支撑确认。",
            buy_reason="估值和技术信号未形成新动作。",
            risk_warning="若跌破近期支撑，需要人工复核仓位。",
            final_decision="HOLD",
            position_action="HOLD",
            current_weight=0.1985,
            target_weight=0.1985,
            delta_amount=0.0,
            market_snapshot={"date": "2026-05-15", "close": "6.56", "source": "yfinance"},
        ),
        _result(
            code="XRO.AX",
            name="XERO [XRO]",
            sentiment_score=54,
            operation_advice="观望",
            trend_prediction="震荡",
            analysis_summary="财报后仍在消化期，暂不加仓。",
            buy_reason="价格仍未脱离震荡区间。",
            risk_warning="高估值品种受市场情绪影响更大。",
            final_decision="HOLD",
            position_action="HOLD",
            current_weight=0.2035,
            target_weight=0.2035,
            delta_amount=0.0,
            market_snapshot={"date": "2026-05-15", "close": "147.95", "source": "yfinance"},
        ),
        _result(
            code="BHP.AX",
            name="BHP GROUP [BHP]",
            sentiment_score=68,
            operation_advice="持有/观望",
            trend_prediction="看多",
            analysis_summary="等待回踩支撑确认。",
            buy_reason="MA10 支撑附近可观察，但未形成今日买入动作。",
            risk_warning="若跌破 MA10 支撑，短期趋势转弱。",
            final_decision="HOLD",
            position_action="HOLD",
            market_snapshot={"date": "2026-05-15", "close": "60.20", "source": "yfinance"},
        ),
        _result(
            code="SXE.AX",
            name="STH X ELEC [SXE]",
            sentiment_score=52,
            operation_advice="观望",
            trend_prediction="震荡",
            analysis_summary="量能不足，继续观察。",
            buy_reason="缺少突破确认。",
            risk_warning="乖离率偏高。",
            final_decision="HOLD",
            position_action="HOLD",
            market_snapshot={"date": "2026-05-15", "close": "4.17", "source": "yfinance"},
        ),
        _result(
            code="EGH.AX",
            name="EUR GROUP [EGH]",
            sentiment_score=48,
            operation_advice="观望",
            trend_prediction="震荡",
            analysis_summary="等待 MA20 支撑确认。",
            buy_reason="低乖离率但无明确动作。",
            risk_warning="基本面增长仍需复核。",
            final_decision="HOLD",
            position_action="HOLD",
            market_snapshot={"date": "2026-05-15", "close": "0.57", "source": "yfinance"},
        ),
    ]


def _landing_section(report: str) -> str:
    marker = "## 开盘前决策驾驶舱"
    start = report.index(marker)
    rest = report[start:]
    separator = "\n---\n"
    return rest.split(separator, 1)[0]


def _section_between(text: str, title: str, next_title: str) -> str:
    return text.split(title, 1)[1].split(next_title, 1)[0]


@patch("src.notification.get_db")
def test_dashboard_homepage_is_compact_and_moves_audit_sections_to_appendix(mock_get_db):
    mock_get_db.return_value.get_portfolio_overview.return_value = _overview()
    service = _service()

    report = service.generate_dashboard_report(_readability_results(), report_date="2026-04-29")
    landing = _landing_section(report)

    assert "**今日结论**" in landing
    assert "**今日动作数量**" in landing
    assert "**今日人工复核卡片**" in landing
    assert "- **先看这几只**：" in landing
    assert "- **低优先级**：" in landing
    assert "- **有机会但证据不足**：" in landing
    assert "- **先补数据再判断**：" in landing
    assert "**当前持仓需要处理什么**" in landing
    assert "**今日重点股票**" in landing
    assert "**主要风险 / 暂停动作**" in landing
    assert "**报告可信度**" in landing
    assert "**价格来源**：全部使用昨收数据" in landing
    assert "**执行前检查**：" in landing

    assert "## 证据质量摘要" not in landing
    assert "## 个股证据矩阵" not in landing
    assert "## 历史校准" not in landing
    assert "## 评分校准" not in landing
    assert "风险仓位参考（观察模式" not in landing
    assert "风险仓位对比（试算" not in landing
    assert "validation BLOCK，仅观察" not in landing

    actionable_section = _section_between(landing, "**今日重点股票**", "**主要风险 / 暂停动作**")
    assert "| 标的 | 今天怎么处理 | 目标仓位 | 计划金额 | 复核提示 |" in actionable_section
    actionable_lines = [
        line for line in actionable_section.splitlines()
        if line.startswith("| ") and not line.startswith("| ---") and "标的" not in line
    ]
    assert len(actionable_lines) == 5

    risk_section = _section_between(landing, "**主要风险 / 暂停动作**", "**报告可信度**")
    risk_lines = [line for line in risk_section.splitlines() if line.startswith("- ")]
    assert len(risk_lines) <= 5

    assert "## 详情 / 审计附录" in report
    assert "## 证据质量摘要" in report
    assert "## 个股证据矩阵" in report
    assert "## 历史校准" in report
    assert "## 评分校准" in report
    assert "风险仓位参考（观察模式" in report
    assert "风险仓位对比（试算" in report
    assert "Shadow" not in report
    assert "Dry Run" not in report
    assert "deterministic action" not in report
    assert "| 项目 | 今天状态 |" in landing


@patch("src.notification.get_db")
def test_triage_card_homepage_uses_plain_chinese_not_developer_jargon(mock_get_db):
    mock_get_db.return_value.get_portfolio_overview.return_value = _overview()
    service = _service()

    results = _readability_results()
    results[3] = _result(
        code="CBA.AX",
        name="CBA",
        sentiment_score=95,
        final_decision="BUY",
        position_action="OPEN",
        target_weight=0.10,
        delta_amount=10000.0,
        execution_price_source="realtime",
        market_snapshot={"date": "2026-04-29", "close": "100.00", "price": "101.00", "source": "yfinance"},
    )

    report = service.generate_dashboard_report(results, report_date="2026-04-29")
    landing = _landing_section(report)

    assert "加仓当前持仓" in landing
    assert "新开仓观察" in landing
    assert "今天没有明确动作" in landing
    assert "数据或历史样本需要人工确认" in landing
    assert "回测证据不足" in landing
    assert "行情时间口径不是纯昨收" in landing

    developer_terms = [
        "add to holding",
        "new position",
        "non-holding",
        "simulated delta",
        "No deterministic action",
        "Actionable but confidence inputs",
        "Watch item has weak data inputs",
        "backtest=not_checked",
        "score_bucket_sample",
        "price_basis=",
        "risk_sizing_dry_run_differs",
        "review_reasons",
        "confirmation_gap",
        "risk_sizing_comparison",
        "evidence_matrix",
        "Top actionable items",
        "Top risks / BLOCK",
        "close_only",
        "unknown",
        "N/A",
        "模拟调仓",
    ]
    for term in developer_terms:
        assert term not in landing


@patch("src.notification.get_db")
def test_triage_card_reuses_existing_artifacts_without_changing_actions(mock_get_db):
    mock_get_db.return_value.get_portfolio_overview.return_value = _overview()
    service = _service()

    service.generate_dashboard_report(_readability_results(), report_date="2026-04-29")
    summary = service.get_last_daily_decision_summary()
    card = summary["triage_card"]

    assert summary["action_counts"]["total_actions"] == 6
    assert summary["action_counts"]["blocked"] == 1
    assert card["counts"]["today_must_review"] == 6
    assert card["counts"]["today_can_ignore"] == 1
    assert card["counts"]["high_value_low_confidence"] >= 1
    assert card["counts"]["data_quality_attention"] >= 2

    blocked = [item for item in card["data_quality_attention"] if item["code"] == "NAB.AX"][0]
    assert blocked["position_action"] == "BLOCK"
    assert blocked["confidence_note"] == "BLOCK 仍是硬阻断。"
    assert "blocked_items" in blocked["source_fields"]

    high_value = card["high_value_low_confidence"][0]
    assert "evidence_matrix" in high_value["source_fields"]
    assert high_value["section"] == "high_value_low_confidence"


@patch("src.notification.get_db")
def test_unverified_backtest_claims_are_sanitized_from_user_facing_report(mock_get_db):
    mock_get_db.return_value.get_portfolio_overview.return_value = _overview()
    service = _service()

    result = _result(
        code="BHP.AX",
        final_decision="BUY",
        position_action="ADD",
        target_weight=0.20,
        delta_amount=2500.0,
        analysis_summary="历史回测胜率 78%，准确率 81%，但仍需人工复核。",
        buy_reason="历史回测胜率 78%，准确率 81%，但仍需人工复核。",
        risk_warning="历史回测胜率较高，仅供参考。",
    )
    result.backtest_summary = {}

    report = service.generate_dashboard_report([result], report_date="2026-04-29")
    landing = _landing_section(report)
    detail_section = report.split("## 详情 / 审计附录", 1)[0]

    assert "历史回测胜率 78%" not in landing
    assert "准确率 81%" not in landing
    assert "历史回测胜率" not in detail_section
    assert "系统未检查该标的回测证据" in landing or "系统未检查该标的回测证据" in detail_section


@patch("src.notification.get_db")
def test_legacy_daily_and_wechat_reports_sanitize_raw_ai_backtest_claims(mock_get_db):
    mock_get_db.return_value.get_portfolio_overview.return_value = _overview()
    service = _service()

    result = _result(
        final_decision="BUY",
        position_action="ADD",
        target_weight=0.20,
        delta_amount=2500.0,
        analysis_summary="历史回测胜率 78%，准确率 81%，但仍需人工复核。",
        buy_reason="历史回测胜率 78%，准确率 81%，但仍需人工复核。",
        risk_warning="历史回测胜率较高，仅供参考。",
    )
    result.backtest_summary = {}

    daily_report = service.generate_daily_report([result], report_date="2026-04-29")
    wechat_report = service.generate_wechat_summary([result], report_date="2026-04-29")
    combined = "\n".join([daily_report, wechat_report])

    assert "历史回测胜率 78%" not in combined
    assert "准确率 81%" not in combined
    assert "系统未检查该标的回测证据" in combined


@patch("src.notification.get_db")
def test_legacy_daily_and_wechat_reports_sanitize_internal_jargon(mock_get_db):
    mock_get_db.return_value.get_portfolio_overview.return_value = _overview()
    service = _service()

    raw_jargon = (
        "Dry Run / Shadow / deterministic action / summary artifact / non_buy_action_context；"
        "强制执行、自动执行、立即执行、直接执行；无需二次确认、不需要二次确认、无需人工确认。"
    )
    result = _result(
        final_decision="BUY",
        position_action="ADD",
        target_weight=0.20,
        delta_amount=2500.0,
        analysis_summary=raw_jargon,
        buy_reason=raw_jargon,
        risk_warning=raw_jargon,
    )

    daily_report = service.generate_daily_report([result], report_date="2026-04-29")
    wechat_report = service.generate_wechat_summary([result], report_date="2026-04-29")
    combined = "\n".join([daily_report, wechat_report])

    for raw_term in [
        "Dry Run",
        "Shadow",
        "deterministic action",
        "summary artifact",
        "non_buy_action_context",
        "强制执行",
        "自动执行",
        "立即执行",
        "直接执行",
        "无需二次确认",
        "不需要二次确认",
        "无需人工确认",
    ]:
        assert raw_term not in combined

    assert "试算" in combined
    assert "观察模式" in combined
    assert "今日主动作" in combined
    assert "完整摘要" in combined
    assert "不是买入或加仓场景" in combined
    assert "人工复核后再处理" in combined
    assert "必须二次确认" in combined
    assert "必须人工确认" in combined


@patch("src.notification.get_db")
def test_dashboard_homepage_surfaces_holdings_counts_and_single_line_checklist(mock_get_db):
    mock_get_db.return_value.get_portfolio_overview.return_value = _overview()
    service = _service()

    report = service.generate_dashboard_report(_readability_results(), report_date="2026-04-29")
    landing = _landing_section(report)

    assert "**今日动作数量**：买入 2 / 加仓 2 / 减仓 1 / 清仓 1 / 观察 1 / 阻断（BLOCK）1" in landing
    assert "| BHP (BHP.AX) | 加仓 | 24.00% | 计划投入约 4,000.00 | 需二次确认：" in landing
    assert "| CSL (CSL.AX) | 减仓 | 12.00% | 计划调出约 6,000.00 |" in landing
    assert "| TLS (TLS.AX) | 清仓 | 0.00% | 计划调出约 12,000.00 |" in landing
    assert "另有 1 只当前持仓未覆盖今日分析" in landing
    assert "技术基准日 2026-04-27~2026-04-28" in landing
    assert "开盘后确认价格；检查公告和新闻；数据不足则观察；仅作计划。" in landing

    assert "- 确认报告为昨收计划 / 开盘前计划" not in landing
    assert "- 开盘后执行前复核实时价格、盘口流动性和重大新闻" not in landing


@patch("src.notification.get_db")
def test_dashboard_homepage_banner_uses_actual_price_policy(mock_get_db):
    mock_get_db.return_value.get_portfolio_overview.return_value = _overview()
    service = _service()

    mixed_results = _readability_results()
    mixed_results[0] = _result(
        code="BHP.AX",
        name="BHP",
        final_decision="BUY",
        position_action="ADD",
        current_weight=0.20,
        target_weight=0.24,
        delta_amount=4000.0,
        execution_price_source="realtime",
        market_snapshot={"date": "2026-04-29", "close": "50.00", "price": "50.30", "source": "yfinance"},
    )

    report = service.generate_dashboard_report(mixed_results, report_date="2026-04-29")
    landing = _landing_section(report)

    assert "> 价格来源混用。开盘后必须先确认价格。" in landing
    assert "> 昨收数据计划 / 开盘前参考。开盘后先确认价格。" not in landing
    assert "**价格来源**：价格来源混用" in landing


@patch("src.notification.get_db")
def test_may14_report_fixture_keeps_alias_and_material_review_hints_separate(mock_get_db):
    mock_get_db.return_value.get_portfolio_overview.return_value = _may14_overview()
    service = _service()

    report = service.generate_dashboard_report(_may14_report_results(), report_date="2026-05-14")
    landing = _landing_section(report)
    summary = service.get_last_daily_decision_summary()
    card = summary["triage_card"]

    assert summary["uncovered_holdings"] == []
    assert "NHF.ASX 当前持仓未覆盖今日分析" not in report
    assert "当前持仓有 **1** 只未覆盖分析" not in report
    assert "**今日动作数量**：买入 0 / 加仓 2 / 减仓 0 / 清仓 0" in landing
    assert "**价格来源**：全部使用昨收数据；技术基准日 2026-05-13" in landing
    assert "| GOOD GROUP [GMG] (GMG.AX) | 加仓 | 14.04% | 计划投入约 532.10 | 需二次确认：" in landing
    assert "| LINDSAY AU [LAU] (LAU.AX) | 加仓 | 21.84% | 计划投入约 535.58 | 需二次确认：" in landing
    assert "1 只股票风险仓位试算与目标仓位差异较大，执行前先复核仓位。" in landing
    assert "回测证据未检查" in landing
    assert "风险仓位试算与目标仓位差异较大" in landing

    gmg_low_confidence = [
        item for item in card["high_value_low_confidence"] if item["code"] == "GMG.AX"
    ][0]
    lau_low_confidence = [
        item for item in card["high_value_low_confidence"] if item["code"] == "LAU.AX"
    ][0]

    assert "风险仓位" not in gmg_low_confidence["confidence_note"]
    assert "风险仓位试算与目标仓位差异较大" in lau_low_confidence["confidence_note"]
    assert summary["actionable_items"][0]["target_weight"] == 0.1404
    assert summary["actionable_items"][1]["target_weight"] == 0.2184
    assert summary["risk_sizing_comparison"]["LAU.AX"]["would_change_target"] is True


@patch("src.notification.get_db")
def test_may18_no_action_report_keeps_holdings_and_watch_ai_review_before_audit(mock_get_db):
    mock_get_db.return_value.get_portfolio_overview.return_value = _may18_no_action_overview()
    service = _service()

    report = service.generate_dashboard_report(_may18_no_action_results(), report_date="2026-05-18")
    summary = service.get_last_daily_decision_summary()

    assert summary["action_counts"]["total_actions"] == 0
    assert summary["action_counts"]["hold_watch"] == 6
    assert "## 当前持仓动作" in report
    assert "### 持仓复盘（无调仓观察）" in report
    assert "## 重点观察复盘（非持仓）" in report
    assert "## 详情 / 审计附录" in report

    holdings_index = report.index("### 持仓复盘（无调仓观察）")
    watch_index = report.index("## 重点观察复盘（非持仓）")
    audit_index = report.index("## 详情 / 审计附录")
    matrix_index = report.index("## 个股证据矩阵")

    assert holdings_index < audit_index
    assert watch_index < audit_index
    assert audit_index < matrix_index

    holdings_section = _section_between(report, "### 持仓复盘（无调仓观察）", "## 新开仓 / 观察清单")
    assert "| 标的 | 今日主动作（确定性/未执行） | AI补充（仅参考） |" in holdings_section
    assert "GOOD GROUP [GMG]" in holdings_section
    assert "NIBHOLDING [NHF]" in holdings_section
    assert "XERO [XRO]" in holdings_section
    assert "关键理由：趋势仍未重新转强，先复核开盘承接。" in holdings_section
    assert "风险：外盘走弱可能拖累开盘情绪。" in holdings_section

    watch_section = _section_between(report, "## 重点观察复盘（非持仓）", "## 详情 / 审计附录")
    assert "BHP GROUP [BHP]" in watch_section
    assert "STH X ELEC [SXE]" in watch_section
    assert "EUR GROUP [EGH]" in watch_section
    assert "关键理由：MA10 支撑附近可观察，但未形成今日买入动作。" in watch_section


def test_archive_html_still_contains_compact_homepage_text(tmp_path: Path):
    service = _service()
    html_path = Path(
        service.save_report_archive_html(
            "# 🎯 2026-04-29 决策仪表盘\n\n## 开盘前决策驾驶舱\n\n**今日结论**：今日有动作。\n",
            filename="report_20260429.html",
            reports_dir=tmp_path,
        )
    )

    html = html_path.read_text(encoding="utf-8")

    assert "<h2>开盘前决策驾驶舱</h2>" in html
    assert "今日结论" in html
    assert "border-radius: 8px" in html
    assert "background: #f7f9fc" in html
