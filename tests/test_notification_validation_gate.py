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

    def test_single_stock_report_shows_validation_gate_banner(self) -> None:
        service = self._build_service()

        report = service.generate_single_stock_report(self._build_blocked_result())

        self.assertIn("### ⚠️ 验证闸门", report)
        self.assertIn("BLOCK / 不可决策 / 仅观察", report)
        self.assertIn("价格口径混用", report)


if __name__ == "__main__":
    unittest.main()
