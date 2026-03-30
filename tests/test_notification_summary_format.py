# -*- coding: utf-8 -*-
"""Tests for stable rendering of Analysis Results Summary table."""

import unittest
from unittest.mock import patch

from src.analyzer import AnalysisResult
from src.formatters import format_feishu_markdown, markdown_to_html_document
from src.notification import NotificationService


class NotificationSummaryFormatTestCase(unittest.TestCase):
    def _build_service(self) -> NotificationService:
        service = NotificationService.__new__(NotificationService)
        service._report_summary_only = True
        return service

    def _build_result(self, **overrides) -> AnalysisResult:
        base = dict(
            code="600519",
            name="贵州茅台",
            sentiment_score=75,
            trend_prediction="震荡上行",
            operation_advice="买入",
            position_action="ADD",
            current_weight=0.12,
            target_weight=0.18,
            delta_amount=3200.0,
            action_reason="趋势确认后分批加仓",
        )
        base.update(overrides)
        return AnalysisResult(**base)

    @patch("src.notification.get_db")
    def test_dashboard_summary_renders_table_with_long_stock_name(self, mock_get_db) -> None:
        mock_get_db.return_value.get_portfolio_overview.return_value = {}
        service = self._build_service()

        result = self._build_result(
            name="超长股票名称用于验证表格列宽稳定性与渲染一致性示例股份有限公司",
        )
        report = service.generate_dashboard_report([result], report_date="2026-03-30")

        self.assertIn("## 📊 分析结果摘要", report)
        self.assertIn("| Stock | AI View | Action | Current Weight | Target Weight | Delta Amount |", report)
        self.assertIn("|---|---|---|---:|---:|---:|", report)
        self.assertIn("**超长股票名称用于验证表格列宽稳定性与渲染一致性示例股份有限公司(600519)**", report)
        self.assertNotIn("   - 今日动作", report)

    @patch("src.notification.get_db")
    def test_dashboard_summary_escapes_long_operation_advice_and_reason(self, mock_get_db) -> None:
        mock_get_db.return_value.get_portfolio_overview.return_value = {}
        service = self._build_service()

        result = self._build_result(
            operation_advice="逢回调分批买入 | 保持纪律\n关注成交量变化",
            action_reason="动作说明非常长用于覆盖多种渲染场景 | 包含竖线\n并且包含换行",
        )
        report = service.generate_dashboard_report([result], report_date="2026-03-30")

        self.assertIn("逢回调分批买入 \\| 保持纪律<br>关注成交量变化", report)
        self.assertIn("ADD · 动作说明非常长用于覆盖多种渲染场景 \\| 包含竖线<br>并且包含换行", report)

        html = markdown_to_html_document(report)
        self.assertIn("<table>", html)
        self.assertIn("<th>Stock</th>", html)
        self.assertIn("<th>Action</th>", html)

    @patch("src.notification.get_db")
    def test_feishu_formatter_keeps_escaped_pipe_inside_cells(self, mock_get_db) -> None:
        mock_get_db.return_value.get_portfolio_overview.return_value = {}
        service = self._build_service()
        result = self._build_result(
            operation_advice="区间交易 | 高抛低吸",
            action_reason="分批执行 | 严格止损",
        )
        report = service.generate_dashboard_report([result], report_date="2026-03-30")

        feishu = format_feishu_markdown(report)
        expected_line = (
            "• Stock：🟢 **贵州茅台(600519)** | "
            "AI View：区间交易 | 高抛低吸 · 评分 75 · 震荡上行 | "
            "Action：ADD · 分批执行 | 严格止损 | "
            "Current Weight：12.00% | Target Weight：18.00% | Delta Amount：3,200.00"
        )
        self.assertIn(expected_line, feishu)


if __name__ == "__main__":
    unittest.main()
