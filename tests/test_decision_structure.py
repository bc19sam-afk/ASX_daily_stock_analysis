# -*- coding: utf-8 -*-
"""Tests for deterministic decision structure."""

import unittest

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


if __name__ == "__main__":
    unittest.main()
