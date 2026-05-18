# -*- coding: utf-8 -*-
"""Guardrails for deduplicated report body structure."""

from unittest.mock import patch

from tests.test_report_readability_guardrail import (
    _overview,
    _readability_results,
    _service,
)


def _section_between(text: str, title: str, next_title: str) -> str:
    return text.split(title, 1)[1].split(next_title, 1)[0]


@patch("src.notification.get_db")
def test_dashboard_body_uses_deduplicated_sections_after_homepage(mock_get_db):
    mock_get_db.return_value.get_portfolio_overview.return_value = _overview()
    service = _service()

    report = service.generate_dashboard_report(_readability_results(), report_date="2026-04-29")

    assert "## 当前持仓动作" in report
    assert "## 新开仓 / 观察清单" in report
    assert "## 今日行动摘要" not in report
    assert "## 当前持仓总览" not in report
    assert "## 当前持仓行动清单" not in report
    assert "\n## 目标仓位模拟（计划视图）\n" not in report


@patch("src.notification.get_db")
def test_dashboard_body_keeps_action_table_but_moves_target_simulation_to_appendix(mock_get_db):
    mock_get_db.return_value.get_portfolio_overview.return_value = _overview()
    service = _service()

    report = service.generate_dashboard_report(_readability_results(), report_date="2026-04-29")

    current_holding_section = _section_between(report, "## 当前持仓动作", "## 新开仓 / 观察清单")
    assert "| 标的 | 今日主动作（确定性/未执行） | AI补充（仅参考） |" in current_holding_section
    assert "| 标的 | 当前已执行权重 | 模拟目标权重 | 模拟调仓金额 |" not in current_holding_section

    appendix_section = report.split("## 详情 / 审计附录", 1)[1]
    assert "### 计划仓位模拟（附录）" in appendix_section
    assert "| 标的 | 当前已执行权重 | 模拟目标权重 | 模拟调仓金额 |" in appendix_section
    assert "### C 段闭环说明" in appendix_section


@patch("src.notification.get_db")
def test_dashboard_body_flows_homepage_to_holdings_to_watchlist_to_details_to_appendix(mock_get_db):
    mock_get_db.return_value.get_portfolio_overview.return_value = _overview()
    service = _service()

    report = service.generate_dashboard_report(_readability_results(), report_date="2026-04-29")

    homepage_index = report.index("## 开盘前决策驾驶舱")
    holdings_index = report.index("## 当前持仓动作")
    watchlist_index = report.index("## 新开仓 / 观察清单")
    detail_index = report.index("## 🟢 BHP (BHP.AX)")
    appendix_index = report.index("## 详情 / 审计附录")

    assert homepage_index < holdings_index < watchlist_index < detail_index < appendix_index
    assert "## 证据质量摘要" in report
    assert "## 历史校准" in report
    assert "## 评分校准" in report
    assert "风险仓位参考（观察模式" in report
    assert "风险仓位对比（试算" in report


def test_email_body_projection_keeps_mainline_and_points_to_full_archive():
    service = _service()
    archive_report = (
        "# 2026-05-18 决策仪表盘\n\n"
        "## 开盘前决策驾驶舱\n\n"
        "今日人工复核重点。\n\n"
        "## 当前持仓动作\n\n"
        "| 标的 | 主动作 |\n"
        "| --- | --- |\n"
        "| AAA | 观察 |\n\n"
        "## 个股详细分析\n\n"
        "### ⚪ AAA (AAA.AX)\n\n"
        "### 证据附录（技术/数据）\n\n"
        "| 价格指标 | 数值 |\n"
        "| --- | --- |\n"
        "| MA10 | 10.00 |\n\n"
        "---\n\n"
        "## 详情 / 审计附录\n\n"
        "## 个股证据矩阵\n\n"
        "审计明细"
    )

    email_body = service.build_email_report_body(archive_report)

    assert "## 开盘前决策驾驶舱" in email_body
    assert "## 当前持仓动作" in email_body
    assert "## 个股详细分析" in email_body
    assert "### 证据附录（技术/数据）" in email_body
    assert "## 详情 / 审计附录" not in email_body
    assert "## 个股证据矩阵" not in email_body
    assert "## 完整归档" in email_body
    assert "\n---\n\n---\n\n## 完整归档" not in email_body
    assert "仅作计划，供人工决策辅助；系统不自动下单" in email_body


def test_email_body_projection_leaves_reports_without_audit_marker_unchanged():
    service = _service()
    report = "# 2026-05-18 决策仪表盘\n\n## 开盘前决策驾驶舱\n\nmain"

    assert service.build_email_report_body(report) == report
