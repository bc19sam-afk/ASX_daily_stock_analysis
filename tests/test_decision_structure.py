# -*- coding: utf-8 -*-
"""Tests for deterministic decision structure."""

import unittest
from types import SimpleNamespace

from src.analyzer import GeminiAnalyzer
from src.core.pipeline import StockAnalysisPipeline


class DecisionStructureTestCase(unittest.TestCase):
    def test_map_alpha_decision(self):
        self.assertEqual(StockAnalysisPipeline._map_alpha_decision("强烈买入"), "BUY")
        self.assertEqual(StockAnalysisPipeline._map_alpha_decision("买入"), "BUY")
        self.assertEqual(StockAnalysisPipeline._map_alpha_decision("持有"), "HOLD")
        self.assertEqual(StockAnalysisPipeline._map_alpha_decision("观望"), "HOLD")
        self.assertEqual(StockAnalysisPipeline._map_alpha_decision("卖出"), "SELL")
        self.assertEqual(StockAnalysisPipeline._map_alpha_decision("强烈卖出"), "SELL")

    def test_synthesize_final_decision_conservative(self):
        # BUY 可以降级到 HOLD
        self.assertEqual(
            StockAnalysisPipeline._synthesize_final_decision(
                alpha_decision="BUY",
                market_regime="RISK_OFF",
                news_sentiment="NEU",
                event_risk="MEDIUM",
                sector_tone="NEU",
                data_quality_flag="OK",
            ),
            "HOLD",
        )
        # HOLD 不直接降到 SELL（第一版保守规则）
        self.assertEqual(
            StockAnalysisPipeline._synthesize_final_decision(
                alpha_decision="HOLD",
                market_regime="RISK_OFF",
                news_sentiment="NEG",
                event_risk="HIGH",
                sector_tone="NEG",
                data_quality_flag="MISSING",
            ),
            "HOLD",
        )
        # SELL 保持 SELL
        self.assertEqual(
            StockAnalysisPipeline._synthesize_final_decision(
                alpha_decision="SELL",
                market_regime="RISK_ON",
                news_sentiment="POS",
                event_risk="LOW",
                sector_tone="POS",
                data_quality_flag="OK",
            ),
            "SELL",
        )

    def test_market_regime_inference(self):
        self.assertEqual(StockAnalysisPipeline._infer_market_regime(None), "NEUTRAL")
        self.assertEqual(
            StockAnalysisPipeline._infer_market_regime(
                {
                    "ASX 200": {"pct_chg": 0.8},
                    "S&P 500": {"pct_chg": 0.4},
                }
            ),
            "RISK_ON",
        )
        self.assertEqual(
            StockAnalysisPipeline._infer_market_regime(
                {
                    "ASX 200": {"pct_chg": -1.2},
                    "S&P 500": {"pct_chg": -0.3},
                }
            ),
            "RISK_OFF",
        )

    def test_overlay_unknown_fold(self):
        self.assertEqual(
            GeminiAnalyzer._normalize_enum("whatever", {"POS", "NEU", "NEG"}, default="UNKNOWN"),
            "UNKNOWN",
        )
        self.assertEqual(GeminiAnalyzer._fold_unknown("UNKNOWN", fallback="NEU"), "NEU")
        self.assertEqual(GeminiAnalyzer._fold_unknown("NEG", fallback="NEU"), "NEG")

    def test_resolve_execution_price_prefers_realtime_then_today_close(self):
        self.assertEqual(
            StockAnalysisPipeline._resolve_execution_price(
                enhanced_context={"realtime": {"price": 52.31}, "today": {"close": 51.8}},
            ),
            52.31,
        )
        self.assertEqual(
            StockAnalysisPipeline._resolve_execution_price(
                enhanced_context={"realtime": {"price": None}, "today": {"close": 51.8}},
            ),
            51.8,
        )
        self.assertIsNone(
            StockAnalysisPipeline._resolve_execution_price(
                enhanced_context={"realtime": {"price": None}, "today": {"close": None}},
            )
        )

    def test_resolve_execution_price_source_marks_latest_close_when_realtime_missing(self):
        self.assertEqual(
            StockAnalysisPipeline._resolve_execution_price_source(
                enhanced_context={"realtime": {"price": None}, "today": {"close": 51.8}},
            ),
            "latest_close",
        )
        self.assertEqual(
            StockAnalysisPipeline._resolve_execution_price_source(
                enhanced_context={"realtime": {"price": 52.31}, "today": {"close": 51.8}},
            ),
            "realtime",
        )

    def test_calculate_position_transition_normalizes_to_whole_shares(self):
        calc = StockAnalysisPipeline._calculate_position_transition(
            existing=None,
            quantity=0.0,
            current_weight=0.0,
            decision=SimpleNamespace(target_weight=0.1),
            cash=10000.0,
            total_value=10000.0,
            current_price=33.0,
            current_value=0.0,
        )
        self.assertIsNotNone(calc)
        self.assertEqual(calc["target_quantity"], 30)
        self.assertEqual(calc["action"], "OPEN")

    def test_calculate_position_transition_suppresses_small_notional_to_hold(self):
        calc = StockAnalysisPipeline._calculate_position_transition(
            existing=None,
            quantity=100.0,
            current_weight=0.1,
            decision=SimpleNamespace(target_weight=0.11),
            cash=9000.0,
            total_value=10000.0,
            current_price=10.0,
            current_value=1000.0,
            min_order_notional=200.0,
        )
        self.assertIsNotNone(calc)
        self.assertEqual(calc["action"], "HOLD")
        self.assertEqual(calc["target_quantity"], 100)
        self.assertEqual(calc["suppressed_by"], "min_order_notional")

    def test_affordability_fallback_uses_floor_and_cash_after_non_negative(self):
        calc = StockAnalysisPipeline._calculate_position_transition(
            existing=None,
            quantity=0.0,
            current_weight=0.0,
            decision=SimpleNamespace(target_weight=0.5),
            cash=100.0,
            total_value=1000.0,
            current_price=9.2,
            current_value=0.0,
        )
        self.assertIsNotNone(calc)
        self.assertEqual(calc["target_quantity"], 10)
        self.assertGreaterEqual(calc["cash_after"], 0.0)

    def test_precedence_order_applies_min_delta_before_min_order_notional(self):
        calc = StockAnalysisPipeline._calculate_position_transition(
            existing=None,
            quantity=349.0,
            current_weight=0.349,
            decision=SimpleNamespace(target_weight=0.35),
            cash=6510.0,
            total_value=10000.0,
            current_price=10.0,
            current_value=3490.0,
            min_delta_amount=20.0,
            min_order_notional=5.0,
        )
        self.assertIsNotNone(calc)
        self.assertEqual(calc["action"], "HOLD")
        self.assertEqual(calc["suppressed_by"], "min_delta_amount")


if __name__ == "__main__":
    unittest.main()
