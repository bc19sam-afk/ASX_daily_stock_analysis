# -*- coding: utf-8 -*-
"""Tests for stable rendering of Analysis Results Summary table."""

import unittest
from unittest.mock import patch
from datetime import datetime as real_datetime

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

    def _build_regression_results(self) -> list[AnalysisResult]:
        return [
            self._build_result(
                code="600519",
                name="贵州茅台",
                sentiment_score=78,
                trend_prediction="震荡上行",
                operation_advice="区间交易",
                position_action="ADD",
                current_weight=0.10,
                target_weight=0.16,
                delta_amount=15000.0,
                action_reason="回撤到支撑位后分批执行",
                final_decision="BUY",
            ),
            self._build_result(
                code="000858",
                name="五粮液",
                sentiment_score=52,
                trend_prediction="区间震荡",
                operation_advice="持有观察",
                position_action="HOLD",
                current_weight=0.08,
                target_weight=0.08,
                delta_amount=0.0,
                action_reason="等待放量突破再调整",
                final_decision="HOLD",
            ),
        ]

    @patch("src.notification.get_db")
    def test_dashboard_summary_renders_table_with_long_stock_name(self, mock_get_db) -> None:
        mock_get_db.return_value.get_portfolio_overview.return_value = {
            "cash": 100000.0,
            "equity_value": 200000.0,
            "total_value": 300000.0,
            "holdings": [],
        }
        service = self._build_service()

        result = self._build_result(
            name="超长股票名称用于验证表格列宽稳定性与渲染一致性示例股份有限公司",
        )
        report = service.generate_dashboard_report([result], report_date="2026-03-30")

        self.assertIn("## A. Current Portfolio Overview (Executed / Real State)", report)
        self.assertIn("## B. Recommended Actions Today", report)
        self.assertIn("## C. Hypothetical Target Allocation (Simulated / Recommended)", report)
        self.assertIn("- 可用现金: **100,000.00**", report)
        self.assertIn("- 持仓市值: **200,000.00**", report)
        self.assertIn("- 账户总值: **300,000.00**", report)
        self.assertIn("| Stock | AI View | Recommended Action Today (Not Executed) |", report)
        self.assertIn("| Stock | Current Executed Weight | Simulated Target Weight | Simulated Delta Amount |", report)
        self.assertIn("**超长股票名称用于验证表格列宽稳定性与渲染一致性示例股份有限公司(600519)**", report)
        self.assertNotIn("   - 今日动作", report)

        section_a = report.split("## B. Recommended Actions Today")[0]
        self.assertNotIn("Simulated Target Weight", section_a)

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
        self.assertIn("<th>Recommended Action Today (Not Executed)</th>", html)

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
        expected_action_line = (
            "• Stock：🟢 **贵州茅台(600519)** | "
            "AI View：区间交易 | 高抛低吸 · 评分 75 · 震荡上行 | "
            "Recommended Action Today (Not Executed)：ADD · 分批执行 | 严格止损"
        )
        expected_sim_line = (
            "• Stock：🟢 **贵州茅台(600519)** | "
            "Current Executed Weight：12.00% | "
            "Simulated Target Weight：18.00% | "
            "Simulated Delta Amount：3,200.00"
        )
        self.assertIn(expected_action_line, feishu)
        self.assertIn(expected_sim_line, feishu)

    @patch("src.notification.get_db")
    def test_wechat_dashboard_separates_executed_recommended_and_simulated(self, mock_get_db) -> None:
        mock_get_db.return_value.get_portfolio_overview.return_value = {
            "cash": 120000.0,
            "equity_value": 180000.0,
            "total_value": 300000.0,
            "holdings": [],
        }
        service = self._build_service()
        result = self._build_result(
            operation_advice="区间交易 | 高抛低吸",
            action_reason="分批执行 | 严格止损",
        )

        wechat = service.generate_wechat_dashboard([result])
        self.assertIn("**A) 当前账户状态（已执行）**", wechat)
        self.assertIn("现金: 120,000.00", wechat)
        self.assertIn("持仓市值: 180,000.00", wechat)
        self.assertIn("总资产: 300,000.00", wechat)
        self.assertIn("**B) 今日建议动作（未执行）**", wechat)
        self.assertIn("ADD · 分批执行 | 严格止损", wechat)
        self.assertIn("**C) 目标仓位（模拟，不代表已成交）**", wechat)
        self.assertIn("执行中 12.00% → 模拟目标 18.00% (Δ3,200.00)", wechat)

    @patch("src.notification.datetime")
    @patch("src.notification.get_db")
    def test_dashboard_report_snapshot_regression(self, mock_get_db, mock_datetime) -> None:
        mock_get_db.return_value.get_portfolio_overview.return_value = {
            "cash": 200000.0,
            "equity_value": 300000.0,
            "total_value": 500000.0,
            "holdings": [
                {"code": "600519", "name": "贵州茅台", "quantity": 100, "weight": 0.36},
                {"code": "000858", "name": "五粮液", "quantity": 200, "weight": 0.24},
            ],
        }
        mock_datetime.now.return_value = real_datetime(2026, 3, 30, 9, 30, 45)
        service = self._build_service()

        report = service.generate_dashboard_report(self._build_regression_results(), report_date="2026-03-30")

        expected = """# 🎯 2026-03-30 决策仪表盘

> 共分析 **2** 只股票 | 🟢买入:1 🟡观望:1 🔴卖出:0

## A. Current Portfolio Overview (Executed / Real State)

- 可用现金: **200,000.00**
- 持仓市值: **300,000.00**
- 账户总值: **500,000.00**

| 当前持仓 | 数量 | 权重 |
|---------|------|------|
| 贵州茅台(600519) | 100.00 | 36.00% |
| 五粮液(000858) | 200.00 | 24.00% |

## B. Recommended Actions Today

> 以下内容为今日分析建议，尚未执行，不代表真实账户已变化。

| Stock | AI View | Recommended Action Today (Not Executed) |
|---|---|---|
| 🟢 **贵州茅台(600519)** | 区间交易 · 评分 78 · 震荡上行 | ADD · 回撤到支撑位后分批执行 |
| ⚪ **五粮液(000858)** | 持有观察 · 评分 52 · 区间震荡 | HOLD · 等待放量突破再调整 |

## C. Hypothetical Target Allocation (Simulated / Recommended)

> 以下目标仓位为模拟结果，仅用于计划参考。Portfolio Overview 始终展示已执行的真实状态。

| Stock | Current Executed Weight | Simulated Target Weight | Simulated Delta Amount |
|---|---:|---:|---:|
| 🟢 **贵州茅台(600519)** | 10.00% | 16.00% | 15,000.00 |
| ⚪ **五粮液(000858)** | 8.00% | 8.00% | 0.00 |

---


*报告生成时间：2026-03-30 09:30:45*"""
        self.assertEqual(expected, report)
        self.assertIn("## A. Current Portfolio Overview (Executed / Real State)", report)
        self.assertIn("## B. Recommended Actions Today", report)
        self.assertIn("## C. Hypothetical Target Allocation (Simulated / Recommended)", report)

    @patch("src.notification.datetime")
    @patch("src.notification.get_db")
    def test_wechat_report_snapshot_regression(self, mock_get_db, mock_datetime) -> None:
        mock_get_db.return_value.get_portfolio_overview.return_value = {
            "cash": 200000.0,
            "equity_value": 300000.0,
            "total_value": 500000.0,
            "holdings": [],
        }
        mock_datetime.now.return_value = real_datetime(2026, 3, 30, 9, 30, 45)
        service = self._build_service()

        report = service.generate_wechat_dashboard(self._build_regression_results())
        expected = """## 🎯 2026-03-30 决策仪表盘

> 2只股票 | 🟢买入:1 🟡观望:1 🔴卖出:0

**A) 当前账户状态（已执行）**
- 现金: 200,000.00
- 持仓市值: 300,000.00
- 总资产: 500,000.00

**B) 今日建议动作（未执行）**

🟢 **贵州茅台(600519)**: ADD · 回撤到支撑位后分批执行 (AI: 区间交易 / 78)
⚪ **五粮液(000858)**: HOLD · 等待放量突破再调整 (AI: 持有观察 / 52)

**C) 目标仓位（模拟，不代表已成交）**
🟢 贵州茅台(600519): 执行中 10.00% → 模拟目标 16.00% (Δ15,000.00)
⚪ 五粮液(000858): 执行中 8.00% → 模拟目标 8.00% (Δ0.00)
*生成时间: 09:30*"""
        self.assertEqual(expected, report)

    @patch("src.notification.datetime")
    @patch("src.notification.get_db")
    def test_feishu_report_snapshot_regression(self, mock_get_db, mock_datetime) -> None:
        mock_get_db.return_value.get_portfolio_overview.return_value = {
            "cash": 200000.0,
            "equity_value": 300000.0,
            "total_value": 500000.0,
            "holdings": [
                {"code": "600519", "name": "贵州茅台", "quantity": 100, "weight": 0.36},
                {"code": "000858", "name": "五粮液", "quantity": 200, "weight": 0.24},
            ],
        }
        mock_datetime.now.return_value = real_datetime(2026, 3, 30, 9, 30, 45)
        service = self._build_service()
        dashboard = service.generate_dashboard_report(self._build_regression_results(), report_date="2026-03-30")

        feishu = format_feishu_markdown(dashboard)
        expected = """**🎯 2026-03-30 决策仪表盘**

💬 共分析 **2** 只股票 | 🟢买入:1 🟡观望:1 🔴卖出:0

**A. Current Portfolio Overview (Executed / Real State)**

• 可用现金: **200,000.00**
• 持仓市值: **300,000.00**
• 账户总值: **500,000.00**

• 当前持仓：贵州茅台(600519) | 数量：100.00 | 权重：36.00%
• 当前持仓：五粮液(000858) | 数量：200.00 | 权重：24.00%

**B. Recommended Actions Today**

💬 以下内容为今日分析建议，尚未执行，不代表真实账户已变化。

• Stock：🟢 **贵州茅台(600519)** | AI View：区间交易 · 评分 78 · 震荡上行 | Recommended Action Today (Not Executed)：ADD · 回撤到支撑位后分批执行
• Stock：⚪ **五粮液(000858)** | AI View：持有观察 · 评分 52 · 区间震荡 | Recommended Action Today (Not Executed)：HOLD · 等待放量突破再调整

**C. Hypothetical Target Allocation (Simulated / Recommended)**

💬 以下目标仓位为模拟结果，仅用于计划参考。Portfolio Overview 始终展示已执行的真实状态。

• Stock：🟢 **贵州茅台(600519)** | Current Executed Weight：10.00% | Simulated Target Weight：16.00% | Simulated Delta Amount：15,000.00
• Stock：⚪ **五粮液(000858)** | Current Executed Weight：8.00% | Simulated Target Weight：8.00% | Simulated Delta Amount：0.00

────────


*报告生成时间：2026-03-30 09:30:45*"""
        self.assertEqual(expected, feishu)


if __name__ == "__main__":
    unittest.main()
