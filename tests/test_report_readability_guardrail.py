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
    assert "风险仓位参考（Shadow" not in landing
    assert "风险仓位对比（Dry Run" not in landing
    assert "validation BLOCK，仅观察" not in landing

    actionable_section = _section_between(landing, "**今日重点股票**", "**主要风险 / 暂停动作**")
    assert "| 标的 | 今天怎么处理 | 目标仓位 | 计划金额 |" in actionable_section
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
    assert "风险仓位参考（Shadow" in report
    assert "风险仓位对比（Dry Run" in report
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
def test_dashboard_homepage_surfaces_holdings_counts_and_single_line_checklist(mock_get_db):
    mock_get_db.return_value.get_portfolio_overview.return_value = _overview()
    service = _service()

    report = service.generate_dashboard_report(_readability_results(), report_date="2026-04-29")
    landing = _landing_section(report)

    assert "**今日动作数量**：买入 2 / 加仓 2 / 减仓 1 / 清仓 1 / 观察 1 / 阻断（BLOCK）1" in landing
    assert "| BHP (BHP.AX) | 加仓 | 24.00% | 计划投入约 4,000.00 |" in landing
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
