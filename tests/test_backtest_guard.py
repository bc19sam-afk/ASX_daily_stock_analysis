# -*- coding: utf-8 -*-
"""Tests for deterministic backtest guard."""

import unittest

from src.analyzer import AnalysisResult
from src.core.pipeline import StockAnalysisPipeline


class BacktestGuardTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)

    @staticmethod
    def _result(final_decision: str = "BUY", confidence_level: str = "高") -> AnalysisResult:
        return AnalysisResult(
            code="CBA.AX",
            name="CBA",
            sentiment_score=70,
            trend_prediction="震荡",
            operation_advice="观察",
            final_decision=final_decision,
            confidence_level=confidence_level,
            risk_warning="原始风险提示",
        )

    def test_weak_backtest_buy_downgrades_to_hold_and_lower_confidence(self):
        result = self._result(final_decision="BUY", confidence_level="高")
        context = {
            "backtest_summary": {
                "total": 8,
                "direction_accuracy": 49,
                "win_rate": 50,
                "stop_loss_rate": 40,
            }
        }

        self.pipeline._apply_backtest_guard(result=result, enhanced_context=context)

        self.assertEqual(result.final_decision, "HOLD")
        self.assertEqual(result.confidence_level, "中")
        self.assertIn("历史回测表现偏弱", result.risk_warning)
        self.assertIn("保守降级", result.risk_warning)

    def test_insufficient_samples_no_downgrade(self):
        result = self._result(final_decision="BUY", confidence_level="中")
        context = {
            "backtest_summary": {
                "total": 4,
                "direction_accuracy": 10,
                "win_rate": 10,
                "stop_loss_rate": 99,
            }
        }

        self.pipeline._apply_backtest_guard(result=result, enhanced_context=context)

        self.assertEqual(result.final_decision, "BUY")
        self.assertEqual(result.confidence_level, "中")
        self.assertEqual(result.risk_warning, "原始风险提示")

    def test_weak_backtest_non_buy_keeps_direction_but_still_downgrades_confidence(self):
        result = self._result(final_decision="SELL", confidence_level="中")
        context = {
            "backtest_summary": {
                "total": 6,
                "direction_accuracy": 70,
                "win_rate": 40,
                "stop_loss_rate": 10,
            }
        }

        self.pipeline._apply_backtest_guard(result=result, enhanced_context=context)

        self.assertEqual(result.final_decision, "SELL")
        self.assertEqual(result.confidence_level, "低")
        self.assertIn("历史回测表现偏弱", result.risk_warning)

    def test_verified_backtest_summary_is_attached_for_report_consumers(self):
        result = self._result(final_decision="BUY", confidence_level="高")
        summary = {
            "total": 39,
            "win_rate": 56.67,
            "direction_accuracy": 61.54,
            "avg_return": 0.43,
            "stop_loss_rate": 12.5,
        }

        self.pipeline._attach_backtest_summary(result=result, enhanced_context={"backtest_summary": summary})

        self.assertIsNotNone(result.backtest_summary)
        self.assertEqual(result.backtest_summary["sample_size"], 39)
        self.assertEqual(result.backtest_summary["win_rate_pct"], 56.67)
        self.assertEqual(result.backtest_summary["direction_accuracy_pct"], 61.54)
        self.assertEqual(result.backtest_summary["source"], "backtest_service")
        self.assertEqual(result.final_decision, "BUY")
        self.assertEqual(result.confidence_level, "高")


if __name__ == "__main__":
    unittest.main()
