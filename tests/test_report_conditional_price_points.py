# -*- coding: utf-8 -*-
"""Report rendering contract for conditional plan points."""

import unittest
from unittest.mock import patch

from src.analyzer import AnalysisResult
from src.notification import NotificationService


class ReportConditionalPricePointsTestCase(unittest.TestCase):
    def _build_service(self) -> NotificationService:
        service = NotificationService.__new__(NotificationService)
        service._report_summary_only = True
        return service

    def _build_result(self, **overrides) -> AnalysisResult:
        base = dict(
            code="BHP.AX",
            name="BHP",
            sentiment_score=72,
            trend_prediction="震荡上行",
            operation_advice="仅解释确定性动作",
            final_decision="BUY",
            position_action="ADD",
            current_weight=0.1,
            target_weight=0.15,
            delta_amount=1200.0,
            action_reason="deterministic action",
            execution_price_source="close_only",
            market_snapshot={"date": "2026-05-04", "price": 10.1},
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
        base.update(overrides)
        return AnalysisResult(**base)

    def test_single_stock_report_renders_conditional_plan_points_with_review_contract(self):
        service = self._build_service()

        report = service.generate_single_stock_report(self._build_result())

        self.assertIn("条件化计划点位", report)
        for phrase in ["来源", "触发条件", "失效条件", "执行前", "人工复核"]:
            self.assertIn(phrase, report)
        self.assertIn("价格口径", report)
        self.assertIn("close_only", report)
        self.assertIn("技术基准日", report)
        self.assertIn("2026-05-04", report)
        self.assertIn("未验证", report)
        self.assertIn("仅作观察参考", report)
        self.assertIn("不作为执行价格", report)
        self.assertNotIn("| AI参考买入位 | AI风险提示位 | AI参考目标位 |", report)
        self.assertNotIn("### 🎯 操作点位", report)

    def test_plan_point_parser_ignores_ma_period_number_and_uses_actual_price_level(self):
        service = self._build_service()
        result = self._build_result(
            name="GOOD GROUP",
            code="GMG.AX",
            market_snapshot={"date": "2026-05-07", "close": "30.85"},
            dashboard={
                "battle_plan": {
                    "sniper_points": {
                        "ideal_buy": "股价回踩MA5（约30.23 AUD）且盘中获得买盘支撑",
                    }
                }
            },
        )

        report = service.generate_single_stock_report(result)

        self.assertIn("| 理想买入观察位 | 30.23 |", report)
        self.assertNotIn("| 理想买入观察位 | 5.00 |", report)

    def test_plan_point_hides_numeric_reference_that_is_not_a_plausible_stock_price(self):
        service = self._build_service()
        result = self._build_result(
            name="LINDSAY AU",
            code="LAU.AX",
            market_snapshot={"date": "2026-05-07", "close": "0.62"},
            dashboard={
                "battle_plan": {
                    "sniper_points": {
                        "ideal_buy": "单笔亏损严格控制在100 AUD以内",
                    }
                }
            },
        )

        report = service.generate_single_stock_report(result)

        self.assertIn("| 理想买入观察位 | 需人工复核（原始点位疑似不是股价） |", report)
        self.assertIn("提取数值与昨收价偏离过大，已隐藏", report)
        self.assertNotIn("| 理想买入观察位 | 100.00 |", report)

    @patch("src.notification.get_db")
    def test_dashboard_observation_appendix_renders_conditions_not_naked_reference_points(self, mock_get_db):
        mock_get_db.return_value.get_portfolio_overview.return_value = {"cash": 100000.0, "holdings": []}
        service = self._build_service()
        service._report_summary_only = False
        result = self._build_result(
            final_decision="HOLD",
            position_action="HOLD",
            delta_amount=0.0,
            buy_reason="wait",
        )

        report = service.generate_dashboard_report([result], report_date="2026-05-05")

        self.assertIn("条件化计划点位", report)
        for phrase in ["来源", "触发条件", "失效条件", "执行前", "人工复核"]:
            self.assertIn(phrase, report)
        self.assertNotIn("参考位：参考买入位 10.50 | 风险提示位 9.80 | 参考目标位 11.60", report)

    def test_blocked_single_stock_report_does_not_show_plan_points(self):
        service = self._build_service()
        result = self._build_result(
            validation_status="BLOCK",
            validation_issues=["mixed_price_basis"],
            final_decision="HOLD",
            position_action="HOLD",
            target_weight=0.1,
            delta_amount=0.0,
        )

        report = service.generate_single_stock_report(result)

        self.assertIn("BLOCK / 不可决策 / 仅观察", report)
        self.assertNotIn("条件化计划点位", report)
        self.assertNotIn("10.50", report)
        self.assertNotIn("9.80", report)
        self.assertNotIn("11.60", report)


if __name__ == "__main__":
    unittest.main()
