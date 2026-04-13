# -*- coding: utf-8 -*-
"""Notification/report rendering for validation gate."""

import unittest
from unittest.mock import patch

from src.analyzer import AnalysisResult
from src.notification import NotificationService


class NotificationValidationGateTestCase(unittest.TestCase):
    def _build_service(self) -> NotificationService:
        service = NotificationService.__new__(NotificationService)
        service._report_summary_only = True
        return service

    def _build_blocked_result(self) -> AnalysisResult:
        return AnalysisResult(
            code="BHP.AX",
            name="BHP",
            sentiment_score=70,
            trend_prediction="看多",
            operation_advice="不可决策，仅观察",
            final_decision="HOLD",
            position_action="HOLD",
            current_weight=0.1,
            target_weight=0.1,
            delta_amount=0.0,
            analysis_summary="等待数据修复",
            validation_status="BLOCK",
            validation_issues=["价格口径混用：信号基于旧日线，但执行价使用实时价格。"],
        )

    @patch("src.notification.get_db")
    def test_dashboard_report_surfaces_blocked_results_in_risk_block(self, mock_get_db) -> None:
        mock_get_db.return_value.get_portfolio_overview.return_value = {"cash": 100000.0, "holdings": []}
        service = self._build_service()

        report = service.generate_dashboard_report([self._build_blocked_result()], report_date="2026-04-14")

        self.assertIn("不可决策（仅观察）", report)
        self.assertIn("价格口径混用", report)
        self.assertIn("不可决策/仅观察", report)

    @patch("src.notification.get_db")
    def test_dashboard_report_keeps_blocked_holding_weight_and_excludes_simulated_row(self, mock_get_db) -> None:
        mock_get_db.return_value.get_portfolio_overview.return_value = {
            "cash": 5000.0,
            "equity_value": 10000.0,
            "total_value": 15000.0,
            "holdings": [
                {"code": "BHP.AX", "name": "BHP", "quantity": 100.0, "market_value": 10000.0, "weight": 2 / 3, "current_price": 100.0}
            ],
        }
        service = self._build_service()
        result = self._build_blocked_result()
        result.current_weight = 2 / 3
        result.target_weight = 2 / 3
        result.current_price = 100.0

        report = service.generate_dashboard_report([result], report_date="2026-04-14")

        self.assertIn("BLOCK **1**", report)
        self.assertIn("🟡观望:0", report)
        self.assertIn("当前/保持仓位 66.67%/66.67%", report)
        section_c = report.split("## 目标仓位模拟（计划视图）", 1)[1]
        self.assertNotIn("BHP.AX", section_c)

    @patch("src.notification.get_db")
    def test_wechat_dashboard_separates_blocked_bucket_from_hold_and_simulated_allocation(self, mock_get_db) -> None:
        mock_get_db.return_value.get_portfolio_overview.return_value = {
            "cash": 5000.0,
            "equity_value": 10000.0,
            "total_value": 15000.0,
            "holdings": [
                {"code": "BHP.AX", "name": "BHP", "quantity": 100.0, "market_value": 10000.0, "weight": 2 / 3, "current_price": 100.0}
            ],
        }
        service = self._build_service()
        result = self._build_blocked_result()
        result.current_weight = 2 / 3
        result.target_weight = 2 / 3

        wechat = service.generate_wechat_dashboard([result])

        self.assertIn("BLOCK 1 只", wechat)
        self.assertIn("🟡观望:0", wechat)
        self.assertIn("**B2) 不可决策（仅观察）**", wechat)
        section_c = wechat.split("**C) 目标仓位（模拟，不代表已成交）**", 1)[1]
        self.assertNotIn("BHP.AX", section_c)

    def test_wechat_summary_separates_blocked_bucket_from_hold_counts(self) -> None:
        service = self._build_service()

        summary = service.generate_wechat_summary([self._build_blocked_result()])

        self.assertIn("BLOCK **1**", summary)
        self.assertIn("🟡持有:0", summary)
        self.assertIn("**⚠️ 不可决策（仅观察）**", summary)
        self.assertIn("- BHP (BHP.AX)：价格口径混用", summary)

    def test_single_stock_report_shows_validation_gate_banner(self) -> None:
        service = self._build_service()
        result = self._build_blocked_result()
        result.current_weight = 0.25
        result.target_weight = 0.25
        result.target_quantity = 1000
        result.dashboard = {
            "core_conclusion": {
                "one_sentence": "等待验证问题修复",
                "position_advice": {
                    "no_position": "建议观察后再开仓",
                    "has_position": "建议继续持有并根据目标数量调整",
                },
            },
            "battle_plan": {
                "sniper_points": {
                    "ideal_buy": "10.0",
                    "stop_loss": "9.2",
                    "take_profit": "11.5",
                }
            },
        }

        report = service.generate_single_stock_report(result)

        self.assertIn("### ⚠️ 验证闸门", report)
        self.assertIn("BLOCK / 不可决策 / 仅观察", report)
        self.assertIn("价格口径混用", report)
        self.assertIn("当前不可决策，仅观察", report)
        self.assertIn("保留当前持仓，不执行调仓", report)
        self.assertNotIn("主动作（优先执行）", report)
        self.assertNotIn("确定性仓位指引(主指令)", report)
        self.assertNotIn("目标数量", report)
        self.assertNotIn("目标仓位", report)
        self.assertNotIn("操作点位", report)


if __name__ == "__main__":
    unittest.main()
