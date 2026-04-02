# -*- coding: utf-8 -*-
"""Tests for stable rendering of Analysis Results Summary table."""

import unittest
from unittest.mock import patch
from datetime import datetime as real_datetime

from src.analyzer import AnalysisResult
from src.formatters import format_feishu_markdown, markdown_to_html_document
from src.notification import NotificationService, NotificationBuilder


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
        self.assertIn("- 持仓市值: **0.00**", report)
        self.assertIn("- 账户总值: **100,000.00**", report)
        self.assertIn("| Stock | Deterministic Action Today (Primary / Not Executed) | AI Commentary (Secondary) |", report)
        self.assertIn("| Stock | Current Executed Weight | Simulated Target Weight | Simulated Delta Amount |", report)
        self.assertIn("| Stock | Deterministic Action Today (Primary / Not Executed) | AI Commentary (Secondary) |", report)
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

        self.assertIn("逢回调分批买入 \\| 保持纪律 关注成交量变化 · 评分 75 · 震荡上行", report)
        self.assertIn("ADD · 目标18.00% · 模拟Δ3,200.00", report)

        html = markdown_to_html_document(report)
        self.assertIn("<table>", html)
        self.assertIn("<th>Stock</th>", html)
        self.assertIn("<th>Deterministic Action Today (Primary / Not Executed)</th>", html)

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
            "Deterministic Action Today (Primary / Not Executed)：ADD · 目标18.00% · 模拟Δ3,200.00 | "
            "AI Commentary (Secondary)：区间交易 | 高抛低吸 · 评分 75 · 震荡上行"
        )
        expected_sim_line = (
            "• Stock：🟢 **贵州茅台(600519)** | "
            "Current Executed Weight：0.00% | "
            "Simulated Target Weight：18.00% | "
            "Simulated Delta Amount：3,200.00"
        )
        self.assertIn(expected_action_line, feishu)
        self.assertIn(expected_sim_line, feishu)

    @patch("src.notification.get_db")
    def test_dashboard_report_suppresses_actionable_ai_commentary_when_conflict(self, mock_get_db) -> None:
        mock_get_db.return_value.get_portfolio_overview.return_value = {}
        service = self._build_service()

        result = self._build_result(
            operation_advice="建议卖出并减仓",
            position_action="ADD",
            final_decision="BUY",
        )
        report = service.generate_dashboard_report([result], report_date="2026-03-30")

        self.assertIn("AI解读与确定性主动作存在方向冲突，已转为中性说明", report)
        self.assertNotIn("建议卖出并减仓", report)

    @patch("src.notification.get_db")
    def test_wechat_dashboard_suppresses_actionable_ai_commentary_when_conflict(self, mock_get_db) -> None:
        mock_get_db.return_value.get_portfolio_overview.return_value = {
            "cash": 120000.0,
            "equity_value": 180000.0,
            "total_value": 300000.0,
            "holdings": [],
        }
        service = self._build_service()
        result = self._build_result(
            operation_advice="建议卖出并减仓",
            position_action="ADD",
            final_decision="BUY",
        )

        wechat = service.generate_wechat_dashboard([result])
        self.assertIn("AI解读与确定性主动作存在方向冲突，已转为中性说明", wechat)
        self.assertNotIn("建议卖出并减仓", wechat)

    def test_single_stock_report_suppresses_actionable_ai_position_commentary_when_conflict(self) -> None:
        service = self._build_service()
        result = self._build_result(
            operation_advice="建议卖出并减仓",
            position_action="ADD",
            final_decision="BUY",
            dashboard={
                "core_conclusion": {
                    "position_advice": {
                        "no_position": "建议卖出并减仓",
                        "has_position": "建议卖出并减仓",
                    }
                }
            },
        )

        report = service.generate_single_stock_report(result)
        self.assertIn("AI解读与确定性主动作存在方向冲突，已转为中性说明", report)
        self.assertNotIn("建议卖出并减仓", report)

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
        self.assertIn("持仓市值: 0.00", wechat)
        self.assertIn("总资产: 120,000.00", wechat)
        self.assertIn("**B) 今日建议动作（未执行）**", wechat)
        self.assertIn("ADD · 目标18.00% · 模拟Δ3,200.00", wechat)
        self.assertIn("**C) 目标仓位（模拟，不代表已成交）**", wechat)
        self.assertIn("执行中 0.00% → 模拟目标 18.00% (Δ3,200.00)", wechat)

    @patch("src.notification.get_db")
    def test_dashboard_report_preserves_ai_commentary_when_not_conflict(self, mock_get_db) -> None:
        mock_get_db.return_value.get_portfolio_overview.return_value = {}
        service = self._build_service()

        result = self._build_result(
            operation_advice="区间交易，耐心等待",
            position_action="ADD",
            final_decision="BUY",
        )
        report = service.generate_dashboard_report([result], report_date="2026-03-30")

        self.assertIn("区间交易，耐心等待", report)

    @patch("src.notification.get_db")
    def test_section_c_reconciliation_explains_cash_unmanaged_and_residual(self, mock_get_db) -> None:
        mock_get_db.return_value.get_portfolio_overview.return_value = {
            "cash": 20000.0,
            "equity_value": 40000.0,
            "total_value": 60000.0,
            "holdings": [
                {"code": "600519", "name": "贵州茅台", "quantity": 100.0, "market_value": 30000.0},
                {"code": "601318", "name": "中国平安", "quantity": 100.0, "market_value": 10000.0},
            ],
        }
        service = self._build_service()
        analyzed_result = self._build_result(
            code="600519",
            name="贵州茅台",
            target_weight=0.40,
            delta_amount=5000.0,
        )

        report = service.generate_dashboard_report([analyzed_result], report_date="2026-03-30")

        self.assertIn("### C 段闭环说明（为什么目标仓位不一定等于 100%）", report)
        self.assertIn("已分析标的目标仓位合计：**40.00%**", report)
        self.assertIn("未纳入今日分析的持仓权重：**16.67%**", report)
        self.assertIn("目标现金权重：**43.33%**", report)
        self.assertIn("闭环残差：**0.0000%**", report)
        self.assertIn("已分析标的目标仓位合计 + 未纳入今日分析的持仓权重 + 目标现金权重 + 闭环残差 = 100%", report)
        self.assertIn("四舍五入/容差", report)

    @patch("src.notification.get_db")
    def test_section_c_reconciliation_normalizes_code_case_for_unmanaged_weight(self, mock_get_db) -> None:
        mock_get_db.return_value.get_portfolio_overview.return_value = {
            "cash": 20000.0,
            "equity_value": 40000.0,
            "total_value": 60000.0,
            "holdings": [
                {"code": "bhp.ax", "name": "BHP", "quantity": 100.0, "market_value": 30000.0},
                {"code": "TLS.AX", "name": "TLS", "quantity": 100.0, "market_value": 10000.0},
            ],
        }
        service = self._build_service()
        analyzed_result = self._build_result(
            code="BHP.AX",
            name="BHP",
            target_weight=0.40,
            delta_amount=5000.0,
        )

        report = service.generate_dashboard_report([analyzed_result], report_date="2026-03-30")

        self.assertIn("| BHP(BHP.AX) | 100.00 | 50.00% |", report)
        self.assertIn("| 🟢 **BHP(BHP.AX)** | 50.00% | 40.00% | 5,000.00 |", report)
        self.assertIn("未纳入今日分析的持仓权重：**16.67%**", report)

    @patch("src.notification.datetime")
    def test_daily_report_includes_data_time_baseline_and_mixed_source_disclosure(self, mock_datetime) -> None:
        mock_datetime.now.return_value = real_datetime(2026, 3, 30, 9, 30, 45)
        service = self._build_service()
        service._report_summary_only = False
        result = self._build_result(
            market_snapshot={
                "date": "2026-03-29",
                "close": "10.00",
                "price": "10.30",
                "source": "tencent",
            },
            execution_price_source="realtime",
        )

        report = service.generate_daily_report([result], report_date="2026-03-30")
        self.assertIn("## 🕒 数据时间基准", report)
        self.assertIn("技术面判断：基于 **2026-03-29 日线（收盘口径）**。", report)
        self.assertIn("新闻更新：截至 **2026-03-30 09:30**。", report)
        self.assertIn("执行参考价格：**1/1** 只使用实时价格（realtime price）；**0/1** 只使用 latest close（日线收盘口径）；**0/1** 只为 close-only basis。", report)
        self.assertIn("旧日线信号 + 新实时价格”混用（实时 1 只，非实时 0 只）", report)
        self.assertIn("**价格基准**：realtime price（实时价格）", report)

    @patch("src.notification.datetime")
    def test_data_baseline_discloses_mixed_daily_dates_instead_of_first_result_only(self, mock_datetime) -> None:
        mock_datetime.now.return_value = real_datetime(2026, 3, 30, 9, 30, 45)
        service = self._build_service()
        service._report_summary_only = False
        results = [
            self._build_result(code="AAA", market_snapshot={"date": "2026-03-29"}),
            self._build_result(code="BBB", market_snapshot={"date": "2026-03-28"}),
        ]
        report = service.generate_daily_report(results, report_date="2026-03-30")
        self.assertIn("技术面判断：基于 **多只股票日线日期不一致（混合日期）**。", report)
        self.assertIn("日期说明：本次技术面涉及多个日线日期（2026-03-28, 2026-03-29）。", report)

    @patch("src.notification.datetime")
    def test_data_baseline_marks_realtime_when_only_current_price_exists(self, mock_datetime) -> None:
        mock_datetime.now.return_value = real_datetime(2026, 3, 30, 9, 30, 45)
        service = self._build_service()
        service._report_summary_only = False
        result = self._build_result(
            current_price=12.34,
            execution_price_source="realtime",
            market_snapshot={"date": "2026-03-29", "price": "N/A"},
        )
        report = service.generate_daily_report([result], report_date="2026-03-30")
        self.assertIn("执行参考价格：**1/1** 只使用实时价格（realtime price）；**0/1** 只使用 latest close（日线收盘口径）；**0/1** 只为 close-only basis。", report)

    @patch("src.notification.datetime")
    def test_data_baseline_uses_explicit_price_source_instead_of_inferring_realtime(self, mock_datetime) -> None:
        mock_datetime.now.return_value = real_datetime(2026, 3, 30, 9, 30, 45)
        service = self._build_service()
        service._report_summary_only = False
        result = self._build_result(
            current_price=12.34,
            execution_price_source="latest_close",
            market_snapshot={"date": "2026-03-29", "price": "N/A", "close": "12.34"},
        )
        report = service.generate_daily_report([result], report_date="2026-03-30")
        self.assertIn("执行参考价格：**0/1** 只使用实时价格（realtime price）；**1/1** 只使用 latest close（日线收盘口径）；**0/1** 只为 close-only basis。", report)
        self.assertIn("**价格基准**：latest close（日线收盘口径）", report)

    def test_single_stock_report_labels_sniper_points_as_ai_reference_only(self) -> None:
        service = self._build_service()
        result = self._build_result(
            dashboard={
                "battle_plan": {
                    "sniper_points": {
                        "ideal_buy": "10.50",
                        "secondary_buy": "10.20",
                        "stop_loss": "9.80",
                        "take_profit": "11.60",
                    }
                }
            },
        )

        report = service.generate_single_stock_report(result)
        self.assertIn("| AI参考买入位 | AI风险提示位 | AI参考目标位 |", report)
        self.assertIn("| 10.50 | 9.80 | 11.60 |", report)

    @patch("src.notification.datetime")
    def test_build_stock_summary_marks_realtime_when_only_current_price_exists(self, mock_datetime) -> None:
        mock_datetime.now.return_value = real_datetime(2026, 3, 30, 9, 30, 45)
        result = self._build_result(
            current_price=12.34,
            execution_price_source="realtime",
            market_snapshot={"date": "2026-03-29", "price": "N/A"},
        )
        summary = NotificationBuilder.build_stock_summary([result])
        self.assertIn("执行参考价=实时 1/1，latest close 0/1，close-only 0/1", summary)
        self.assertIn("价格基准：realtime price（实时价格）", summary)

    @patch("src.notification.datetime")
    @patch("src.notification.get_db")
    def test_dashboard_report_snapshot_regression(self, mock_get_db, mock_datetime) -> None:
        mock_get_db.return_value.get_portfolio_overview.return_value = {
            "cash": 200000.0,
            "equity_value": 300000.0,
            "total_value": 500000.0,
            "holdings": [
                {"code": "600519", "name": "贵州茅台", "quantity": 100, "weight": 0.36, "market_value": 180000.0},
                {"code": "000858", "name": "五粮液", "quantity": 200, "weight": 0.24, "market_value": 120000.0},
            ],
        }
        mock_datetime.now.return_value = real_datetime(2026, 3, 30, 9, 30, 45)
        service = self._build_service()

        report = service.generate_dashboard_report(self._build_regression_results(), report_date="2026-03-30")

        expected = """# 🎯 2026-03-30 决策仪表盘

> 共分析 **2** 只股票 | 🟢买入:1 🟡观望:1 🔴卖出:0

## 🕒 数据时间基准

- 技术面判断：基于 **最新可用日线（通常为昨日收盘）**。
- 新闻更新：截至 **2026-03-30 09:30**。
- 执行参考价格：**0/2** 只使用实时价格（realtime price）；**0/2** 只使用 latest close（日线收盘口径）；**2/2** 只为 close-only basis。

## A. Current Portfolio Overview (Executed / Real State)

- 可用现金: **200,000.00**
- 持仓市值: **300,000.00**
- 账户总值: **500,000.00**

| 当前持仓 | 数量 | 权重 | 估值来源 | 今日分析覆盖 |
|---------|------|------|----------|--------------|
| 贵州茅台(600519) | 100.00 | 36.00% | stored_market_value_fallback | yes |
| 五粮液(000858) | 200.00 | 24.00% | stored_market_value_fallback | yes |

注：`估值来源=report_time_price` 表示使用报告时点价格；`stored_market_value_fallback` 表示缺少报告时点价格，回退至账户快照市值。
注：`今日分析覆盖=yes` 表示该持仓在今日 analysis universe 中；`no` 表示账户持有但今日未分析。

## B. Recommended Actions Today

> 以下内容以确定性动作模型为主（final_decision / position_action / target_weight / delta_amount），尚未执行，不代表真实账户已变化。

| Stock | Deterministic Action Today (Primary / Not Executed) | AI Commentary (Secondary) |
|---|---|---|
| 🟢 **贵州茅台(600519)** | ADD · 目标16.00% · 模拟Δ15,000.00 | 区间交易 · 评分 78 · 震荡上行 |
| ⚪ **五粮液(000858)** | HOLD · 目标8.00% · 模拟Δ0.00 | 持有观察 · 评分 52 · 区间震荡 |

## C. Hypothetical Target Allocation (Simulated / Recommended)

> 以下目标仓位为模拟结果，仅用于计划参考。Portfolio Overview 始终展示已执行的真实状态。

| Stock | Current Executed Weight | Simulated Target Weight | Simulated Delta Amount |
|---|---:|---:|---:|
| 🟢 **贵州茅台(600519)** | 36.00% | 16.00% | 15,000.00 |
| ⚪ **五粮液(000858)** | 24.00% | 8.00% | 0.00 |

### C 段闭环说明（为什么目标仓位不一定等于 100%）

- 已分析标的目标仓位合计：**24.00%**
- 未纳入今日分析的持仓权重：**0.00%**
- 目标现金权重：**76.00%**
- 闭环残差：**0.0000%**
- 闭环关系：**已分析标的目标仓位合计 + 未纳入今日分析的持仓权重 + 目标现金权重 + 闭环残差 = 100%**
- 说明：残差在四舍五入/容差范围内，可视为数值舍入带来的极小差异。

---


*报告生成时间：2026-03-30 09:30:45*"""
        self.assertEqual(expected, report)
        self.assertIn("## A. Current Portfolio Overview (Executed / Real State)", report)
        self.assertIn("## B. Recommended Actions Today", report)
        self.assertIn("## C. Hypothetical Target Allocation (Simulated / Recommended)", report)

    @patch("src.notification.get_db")
    def test_dashboard_section_c_current_weight_uses_same_source_as_section_a(self, mock_get_db) -> None:
        mock_get_db.return_value.get_portfolio_overview.return_value = {
            "cash": 100000.0,
            "equity_value": 50000.0,
            "total_value": 150000.0,
            "holdings": [
                {"code": "600519", "name": "贵州茅台", "quantity": 10, "weight": 0.25, "market_value": 37500.0},
            ],
        }
        service = self._build_service()
        result = self._build_result(
            code="600519",
            current_weight=0.05,  # intentionally inconsistent with overview
            target_weight=0.3,
            delta_amount=8000.0,
        )

        report = service.generate_dashboard_report([result], report_date="2026-03-30")

        self.assertIn("| 贵州茅台(600519) | 10.00 | 27.27% |", report)
        self.assertIn("| 🟢 **贵州茅台(600519)** | 27.27% | 30.00% | 8,000.00 |", report)
        self.assertNotIn("| 🟢 **贵州茅台(600519)** | 5.00% | 30.00% | 8,000.00 |", report)

    @patch("src.notification.get_db")
    def test_section_c_current_weight_source_is_consistent_across_dashboard_feishu_wechat(self, mock_get_db) -> None:
        mock_get_db.return_value.get_portfolio_overview.return_value = {
            "cash": 100000.0,
            "equity_value": 50000.0,
            "total_value": 150000.0,
            "holdings": [
                {"code": "600519", "name": "贵州茅台", "quantity": 10, "weight": 0.25, "market_value": 37500.0},
            ],
        }
        service = self._build_service()
        result = self._build_result(
            code="600519",
            current_weight=0.05,  # intentionally inconsistent with overview-based rendering
            target_weight=0.3,
            delta_amount=8000.0,
        )

        dashboard = service.generate_dashboard_report([result], report_date="2026-03-30")
        feishu = format_feishu_markdown(dashboard)
        wechat = service.generate_wechat_dashboard([result])

        self.assertIn("| 🟢 **贵州茅台(600519)** | 27.27% | 30.00% | 8,000.00 |", dashboard)
        self.assertIn("Current Executed Weight：27.27% | Simulated Target Weight：30.00% | Simulated Delta Amount：8,000.00", feishu)
        self.assertIn("执行中 27.27% → 模拟目标 30.00% (Δ8,000.00)", wechat)
        self.assertNotIn("Current Executed Weight：5.00%", feishu)
        self.assertNotIn("执行中 5.00% → 模拟目标 30.00% (Δ8,000.00)", wechat)

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

**🕒 数据时间基准**

- 技术面判断：基于 **最新可用日线（通常为昨日收盘）**。
- 新闻更新：截至 **2026-03-30 09:30**。
- 执行参考价格：**0/2** 只使用实时价格（realtime price）；**0/2** 只使用 latest close（日线收盘口径）；**2/2** 只为 close-only basis。

**A) 当前账户状态（已执行）**
- 现金: 200,000.00
- 持仓市值: 0.00
- 总资产: 200,000.00

**B) 今日建议动作（未执行）**

🟢 **贵州茅台(600519)**: ADD · 目标16.00% · 模拟Δ15,000.00 (AI次要参考: 区间交易 / 78)
⚪ **五粮液(000858)**: HOLD · 目标8.00% · 模拟Δ0.00 (AI次要参考: 持有观察 / 52)

**C) 目标仓位（模拟，不代表已成交）**
🟢 贵州茅台(600519): 执行中 0.00% → 模拟目标 16.00% (Δ15,000.00)
⚪ 五粮液(000858): 执行中 0.00% → 模拟目标 8.00% (Δ0.00)
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
                {"code": "600519", "name": "贵州茅台", "quantity": 100, "weight": 0.36, "market_value": 180000.0},
                {"code": "000858", "name": "五粮液", "quantity": 200, "weight": 0.24, "market_value": 120000.0},
            ],
        }
        mock_datetime.now.return_value = real_datetime(2026, 3, 30, 9, 30, 45)
        service = self._build_service()
        dashboard = service.generate_dashboard_report(self._build_regression_results(), report_date="2026-03-30")

        feishu = format_feishu_markdown(dashboard)
        expected = """**🎯 2026-03-30 决策仪表盘**

💬 共分析 **2** 只股票 | 🟢买入:1 🟡观望:1 🔴卖出:0

**🕒 数据时间基准**

• 技术面判断：基于 **最新可用日线（通常为昨日收盘）**。
• 新闻更新：截至 **2026-03-30 09:30**。
• 执行参考价格：**0/2** 只使用实时价格（realtime price）；**0/2** 只使用 latest close（日线收盘口径）；**2/2** 只为 close-only basis。

**A. Current Portfolio Overview (Executed / Real State)**

• 可用现金: **200,000.00**
• 持仓市值: **300,000.00**
• 账户总值: **500,000.00**

• 当前持仓：贵州茅台(600519) | 数量：100.00 | 权重：36.00% | 估值来源：stored_market_value_fallback | 今日分析覆盖：yes
• 当前持仓：五粮液(000858) | 数量：200.00 | 权重：24.00% | 估值来源：stored_market_value_fallback | 今日分析覆盖：yes

注：`估值来源=report_time_price` 表示使用报告时点价格；`stored_market_value_fallback` 表示缺少报告时点价格，回退至账户快照市值。
注：`今日分析覆盖=yes` 表示该持仓在今日 analysis universe 中；`no` 表示账户持有但今日未分析。

**B. Recommended Actions Today**

💬 以下内容以确定性动作模型为主（final_decision / position_action / target_weight / delta_amount），尚未执行，不代表真实账户已变化。

• Stock：🟢 **贵州茅台(600519)** | Deterministic Action Today (Primary / Not Executed)：ADD · 目标16.00% · 模拟Δ15,000.00 | AI Commentary (Secondary)：区间交易 · 评分 78 · 震荡上行
• Stock：⚪ **五粮液(000858)** | Deterministic Action Today (Primary / Not Executed)：HOLD · 目标8.00% · 模拟Δ0.00 | AI Commentary (Secondary)：持有观察 · 评分 52 · 区间震荡

**C. Hypothetical Target Allocation (Simulated / Recommended)**

💬 以下目标仓位为模拟结果，仅用于计划参考。Portfolio Overview 始终展示已执行的真实状态。

• Stock：🟢 **贵州茅台(600519)** | Current Executed Weight：36.00% | Simulated Target Weight：16.00% | Simulated Delta Amount：15,000.00
• Stock：⚪ **五粮液(000858)** | Current Executed Weight：24.00% | Simulated Target Weight：8.00% | Simulated Delta Amount：0.00

**C 段闭环说明（为什么目标仓位不一定等于 100%）**

• 已分析标的目标仓位合计：**24.00%**
• 未纳入今日分析的持仓权重：**0.00%**
• 目标现金权重：**76.00%**
• 闭环残差：**0.0000%**
• 闭环关系：**已分析标的目标仓位合计 + 未纳入今日分析的持仓权重 + 目标现金权重 + 闭环残差 = 100%**
• 说明：残差在四舍五入/容差范围内，可视为数值舍入带来的极小差异。

────────


*报告生成时间：2026-03-30 09:30:45*"""
        self.assertEqual(expected, feishu)

    @patch("src.notification.get_db")
    def test_dashboard_overview_uses_executed_quantities_cash_and_report_time_prices(self, mock_get_db) -> None:
        mock_get_db.return_value.get_portfolio_overview.return_value = {
            "cash": 112.01,
            "holdings": [
                {"code": "BHP.AX", "name": "BHP", "quantity": 66, "market_value": 10.0, "weight": 0.99},
                {"code": "SHL.AX", "name": "SHL", "quantity": 172, "market_value": 10.0, "weight": 0.01},
            ],
        }
        service = self._build_service()
        results = [
            self._build_result(code="BHP.AX", name="BHP", current_price=50.0),
            self._build_result(code="SHL.AX", name="SHL", current_price=20.0),
        ]

        report = service.generate_dashboard_report(results, report_date="2026-03-30")
        self.assertIn("- 可用现金: **112.01**", report)
        self.assertIn("- 持仓市值: **6,740.00**", report)
        self.assertIn("- 账户总值: **6,852.01**", report)
        self.assertIn("| BHP(BHP.AX) | 66.00 | 48.16% |", report)
        self.assertIn("| SHL(SHL.AX) | 172.00 | 50.20% |", report)

    @patch("src.notification.get_db")
    def test_dashboard_overview_exposes_valuation_source_and_analysis_coverage(self, mock_get_db) -> None:
        mock_get_db.return_value.get_portfolio_overview.return_value = {
            "cash": 112.01,
            "holdings": [
                {"code": "BHP.AX", "name": "BHP", "quantity": 66, "market_value": 3432.0},
                {"code": "LAU.AX", "name": "LAU", "quantity": 2958, "market_value": 1996.65},
                {"code": "TLS.AX", "name": "TLS", "quantity": 100, "market_value": 300.0},
            ],
        }
        service = self._build_service()
        results = [
            self._build_result(code="BHP.AX", name="BHP", current_price=52.0),
            self._build_result(code="LAU.AX", name="LAU", current_price=None),
        ]

        report = service.generate_dashboard_report(results, report_date="2026-03-30")
        self.assertIn("| 当前持仓 | 数量 | 权重 | 估值来源 | 今日分析覆盖 |", report)
        # BHP uses report-time price and is analyzed today
        self.assertIn("| BHP(BHP.AX) | 66.00 | 58.76% | report_time_price | yes |", report)
        # LAU falls back to stored market_value and is analyzed today
        self.assertIn("| LAU(LAU.AX) | 2,958.00 | 34.19% | stored_market_value_fallback | yes |", report)
        # TLS is not in today's analysis results
        self.assertIn("| TLS(TLS.AX) | 100.00 | 5.14% | stored_market_value_fallback | no |", report)
        self.assertIn("`stored_market_value_fallback`", report)
        self.assertIn("`今日分析覆盖=yes`", report)

    @patch("src.notification.get_db")
    def test_market_snapshot_displays_yfinance_source_name(self, mock_get_db) -> None:
        mock_get_db.return_value.get_portfolio_overview.return_value = {"cash": 100.0, "holdings": []}
        service = self._build_service()
        service._report_summary_only = False
        result = self._build_result(
            code="BHP.AX",
            name="BHP",
            market_snapshot={
                "date": "2026-03-30",
                "close": "50.00",
                "prev_close": "49.00",
                "open": "49.50",
                "high": "50.20",
                "low": "49.30",
                "pct_chg": "2.04%",
                "change_amount": "1.00",
                "amplitude": "1.84%",
                "volume": "1.20 M",
                "amount": "60.00 M AUD",
                "price": "50.10",
                "volume_ratio": "N/A",
                "turnover_rate": "N/A",
                "source": "yfinance",
            },
        )

        report = service.generate_dashboard_report([result], report_date="2026-03-30")
        self.assertIn("| 当前价 | 量比 | 换手率 | 行情来源 |", report)
        self.assertIn("| 50.10 | N/A | N/A | Yahoo Finance |", report)

    @patch("src.notification.get_db")
    def test_dashboard_report_generation_is_read_only_against_db(self, mock_get_db) -> None:
        db = mock_get_db.return_value
        db.get_portfolio_overview.return_value = {"cash": 100.0, "holdings": []}
        service = self._build_service()
        _ = service.generate_dashboard_report([self._build_result()], report_date="2026-03-30")

        db.get_portfolio_overview.assert_called_once()
        db.upsert_portfolio_position.assert_not_called()
        db.save_account_snapshot.assert_not_called()
        db.save_trade_journal.assert_not_called()

    @patch("src.notification.get_db")
    def test_dashboard_counts_and_actions_share_primary_deterministic_source(self, mock_get_db) -> None:
        mock_get_db.return_value.get_portfolio_overview.return_value = {"cash": 100.0, "holdings": []}
        service = self._build_service()
        results = [
            self._build_result(
                code="600519",
                final_decision="HOLD",
                position_action="CLOSE",
                target_weight=0.0,
                delta_amount=-12000.0,
                operation_advice="继续持有",
            ),
            self._build_result(
                code="000858",
                name="五粮液",
                final_decision="BUY",
                position_action="ADD",
                target_weight=0.15,
                delta_amount=5000.0,
            ),
        ]

        report = service.generate_dashboard_report(results, report_date="2026-03-30")
        self.assertIn("🟢买入:1", report)
        self.assertIn("🔴卖出:1", report)
        self.assertIn("| 🔴 **贵州茅台(600519)** | CLOSE · 目标0.00% · 模拟Δ-12,000.00 |", report)

    @patch("src.notification.get_db")
    def test_recommended_actions_and_summary_counts_are_consistent(self, mock_get_db) -> None:
        mock_get_db.return_value.get_portfolio_overview.return_value = {"cash": 100.0, "holdings": []}
        service = self._build_service()
        result = self._build_result(
            final_decision="BUY",
            position_action="REDUCE",
            target_weight=0.05,
            delta_amount=-2000.0,
        )
        report = service.generate_dashboard_report([result], report_date="2026-03-30")
        self.assertIn("🔴卖出:1", report)
        self.assertIn("REDUCE · 目标5.00% · 模拟Δ-2,000.00", report)

    @patch("src.notification.get_db")
    def test_ai_narrative_is_labeled_secondary_and_conflict_is_explicit(self, mock_get_db) -> None:
        mock_get_db.return_value.get_portfolio_overview.return_value = {"cash": 100.0, "holdings": []}
        service = self._build_service()
        result = self._build_result(
            final_decision="HOLD",
            position_action="HOLD",
            operation_advice="必须立即卖出止损",
        )
        report = service.generate_dashboard_report([result], report_date="2026-03-30")
        self.assertIn("AI Commentary (Secondary)", report)
        self.assertIn("AI解读与确定性主动作存在方向冲突，已转为中性说明 · 评分 75 · 震荡上行", report)
        self.assertIn("⚠️(已抑制冲突态AI操作措辞)", report)

    @patch("src.notification.get_db")
    def test_per_stock_heading_uses_deterministic_action_semantics(self, mock_get_db) -> None:
        mock_get_db.return_value.get_portfolio_overview.return_value = {"cash": 100.0, "holdings": []}
        service = self._build_service()
        service._report_summary_only = False
        result = self._build_result(
            final_decision="BUY",
            position_action="HOLD",
            operation_advice="卖出",
            dashboard={"core_conclusion": {"one_sentence": "必须卖出", "time_sensitivity": "今日"}},
        )
        report = service.generate_dashboard_report([result], report_date="2026-03-30")
        self.assertIn("### 📌 核心结论", report)
        self.assertIn("**⚪ 持有/观望**", report)
        self.assertIn("**🧭 确定性动作(主指令)**: HOLD | 目标仓位 18.00% | 模拟Δ 3,200.00", report)
        self.assertIn("**💬 AI解读(次要参考)**: AI解读与确定性主动作存在方向冲突，已转为中性说明", report)
        self.assertIn("> **一句话决策**: AI总结与确定性主动作存在方向冲突，请仅按确定性主动作执行", report)
        self.assertNotIn("> **一句话决策**: 必须卖出", report)
        self.assertIn("⚠️ AI解读与确定性动作不一致；请以“确定性动作(主指令)”为准。", report)

    @patch("src.notification.get_db")
    def test_primary_action_stays_canonical_while_ai_commentary_remains_independent(self, mock_get_db) -> None:
        mock_get_db.return_value.get_portfolio_overview.return_value = {"cash": 100.0, "holdings": []}
        service = self._build_service()
        results = [
            self._build_result(code="AAA", final_decision="BUY", position_action="", operation_advice="可轻仓跟踪"),
            self._build_result(code="BBB", final_decision="HOLD", position_action="", operation_advice="可买入"),
            self._build_result(code="CCC", final_decision="SELL", position_action="", operation_advice="继续拿住"),
        ]
        report = service.generate_dashboard_report(results, report_date="2026-03-30")

        self.assertIn("| 🟢 **贵州茅台(AAA)** | OPEN · 目标18.00% · 模拟Δ3,200.00 | 可轻仓跟踪 · 评分 75 · 震荡上行 |", report)
        self.assertIn("| ⚪ **贵州茅台(BBB)** | HOLD · 目标18.00% · 模拟Δ3,200.00 | AI解读与确定性主动作存在方向冲突，已转为中性说明 · 评分 75 · 震荡上行 ⚠️(已抑制冲突态AI操作措辞) |", report)
        self.assertIn("| 🔴 **贵州茅台(CCC)** | CLOSE · 目标18.00% · 模拟Δ3,200.00 | 继续拿住 · 评分 75 · 震荡上行 |", report)

    @patch("src.notification.get_db")
    def test_position_advice_fallback_escapes_pipe_for_markdown_table_and_feishu(self, mock_get_db) -> None:
        mock_get_db.return_value.get_portfolio_overview.return_value = {"cash": 100.0, "holdings": []}
        service = self._build_service()
        service._report_summary_only = False
        result = self._build_result(
            final_decision="BUY",
            position_action="ADD",
            target_weight=0.18,
            delta_amount=3200.0,
            dashboard={
                "core_conclusion": {
                    "one_sentence": "按计划执行",
                    "time_sensitivity": "今日",
                    "position_advice": {
                        "has_position": "继续持有等待确认",
                    },
                }
            },
        )

        report = service.generate_dashboard_report([result], report_date="2026-03-30")
        self.assertIn("| 🆕 **空仓者** | ADD \\| 目标仓位 18.00% \\| 模拟Δ 3,200.00 \\| 目标数量 N/A（确定性引擎未提供） |", report)
        self.assertIn("| 💼 **持仓者** | ADD \\| 目标仓位 18.00% \\| 模拟Δ 3,200.00 \\| 目标数量 N/A（确定性引擎未提供） |", report)
        self.assertIn("**💬 AI仓位解读（次要评论，非执行指令）**", report)
        self.assertIn("- 💼 持仓者: 继续持有等待确认", report)

        feishu = format_feishu_markdown(report)
        self.assertIn("空仓者", feishu)
        self.assertIn("ADD | 目标仓位 18.00% | 模拟Δ 3,200.00 | 目标数量 N/A（确定性引擎未提供）", feishu)

    @patch("src.notification.get_db")
    def test_per_stock_deterministic_target_quantity_is_the_only_sizing_instruction(self, mock_get_db) -> None:
        mock_get_db.return_value.get_portfolio_overview.return_value = {"cash": 100.0, "holdings": []}
        service = self._build_service()
        service._report_summary_only = False
        result = self._build_result(
            target_weight=0.2,
            delta_amount=6000.0,
            dashboard={
                "core_conclusion": {
                    "one_sentence": "按计划执行",
                    "position_advice": {
                        "no_position": "建议买入1000股",
                        "has_position": "再加仓500股",
                    },
                }
            },
        )
        setattr(result, "target_quantity", 321.5)

        report = service.generate_dashboard_report([result], report_date="2026-03-30")
        self.assertIn("目标数量 322 股", report)
        self.assertIn("ADD \\| 目标仓位 20.00% \\| 模拟Δ 6,000.00 \\| 目标数量 322 股", report)
        self.assertIn("- 🆕 空仓者: AI仓位建议（非执行）", report)
        self.assertIn("- 💼 持仓者: 再加仓500股", report)
        self.assertIn("AI仓位解读（次要评论，非执行指令）", report)

    @patch("src.notification.get_db")
    def test_per_stock_ai_sizing_commentary_is_labeled_non_binding_when_target_quantity_missing(self, mock_get_db) -> None:
        mock_get_db.return_value.get_portfolio_overview.return_value = {"cash": 100.0, "holdings": []}
        service = self._build_service()
        service._report_summary_only = False
        result = self._build_result(
            dashboard={
                "core_conclusion": {
                    "one_sentence": "等待确认",
                    "position_advice": {"no_position": "建议买入1000股"},
                }
            },
        )

        report = service.generate_dashboard_report([result], report_date="2026-03-30")
        self.assertIn("目标数量 N/A（确定性引擎未提供）", report)
        self.assertIn("AI仓位解读（次要评论，非执行指令）", report)
        self.assertNotIn("| 🆕 **空仓者** | 建议买入1000股 |", report)
        self.assertIn("- 🆕 空仓者: AI仓位建议（非执行）", report)

    def test_wechat_dashboard_redacts_ai_share_count_guidance(self) -> None:
        service = self._build_service()
        service._report_summary_only = False
        result = self._build_result(
            dashboard={
                "core_conclusion": {
                    "position_advice": {
                        "no_position": "buy 100 shares now",
                        "has_position": "建议买入1000股",
                    },
                }
            },
        )

        wechat = service.generate_wechat_dashboard([result])
        self.assertIn("💬 AI空仓者评论(非执行): AI仓位建议（非执行）", wechat)
        self.assertIn("💬 AI持仓者评论(非执行): AI仓位建议（非执行）", wechat)
        self.assertNotIn("buy 100 shares now", wechat)
        self.assertNotIn("建议买入1000股", wechat)

    def test_wechat_dashboard_suppresses_conflicting_one_sentence(self) -> None:
        service = self._build_service()
        service._report_summary_only = False
        result = self._build_result(
            final_decision="BUY",
            position_action="HOLD",
            operation_advice="建议卖出",
            dashboard={
                "core_conclusion": {
                    "one_sentence": "必须卖出",
                }
            },
        )

        wechat = service.generate_wechat_dashboard([result])
        self.assertIn("📌 **AI总结与确定性主动作存在方向冲突，请仅按确定性主动作执行**", wechat)
        self.assertNotIn("📌 **必须卖出**", wechat)

    def test_single_stock_report_suppresses_conflicting_one_sentence(self) -> None:
        service = self._build_service()
        result = self._build_result(
            final_decision="BUY",
            position_action="HOLD",
            operation_advice="建议卖出",
            dashboard={
                "core_conclusion": {
                    "one_sentence": "必须卖出",
                }
            },
        )

        report = service.generate_single_stock_report(result)
        self.assertIn("**持有/观望**: AI总结与确定性主动作存在方向冲突，请仅按确定性主动作执行", report)
        self.assertNotIn("**持有/观望**: 必须卖出", report)

    @patch("src.notification.get_db")
    def test_per_stock_close_position_renders_zero_target_quantity_as_deterministic(self, mock_get_db) -> None:
        mock_get_db.return_value.get_portfolio_overview.return_value = {"cash": 100.0, "holdings": []}
        service = self._build_service()
        service._report_summary_only = False
        result = self._build_result(
            position_action="CLOSE",
            final_decision="SELL",
            target_weight=0.0,
            delta_amount=-3200.0,
            dashboard={
                "core_conclusion": {
                    "one_sentence": "按纪律清仓",
                    "position_advice": {"has_position": "建议全部卖出"},
                }
            },
        )
        setattr(result, "target_quantity", 0)

        report = service.generate_dashboard_report([result], report_date="2026-03-30")
        self.assertIn("CLOSE \\| 目标仓位 0.00% \\| 模拟Δ -3,200.00 \\| 目标数量 0 股", report)
        self.assertNotIn("目标数量 N/A（确定性引擎未提供）", report)

    def test_suppressed_hold_with_legacy_fractional_target_quantity_shows_no_execution_text(self) -> None:
        service = self._build_service()
        result = self._build_result(
            position_action="HOLD",
            final_decision="HOLD",
            target_weight=0.13,
            delta_amount=0.0,
        )
        setattr(result, "target_quantity", 12.75)
        setattr(result, "action_reason", "final_decision=BUY, execution_blocked=min_order_notional")

        text = service._format_deterministic_sizing_text(result)
        self.assertIn("HOLD | 目标仓位 13.00% | 模拟Δ 0.00 | 目标数量 保持当前持仓（不执行）", text)
        self.assertNotIn("目标数量 13 股", text)


if __name__ == "__main__":
    unittest.main()
