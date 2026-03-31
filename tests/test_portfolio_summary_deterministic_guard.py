import unittest

from src.analyzer import AnalysisResult, GeminiAnalyzer


class PortfolioSummaryDeterministicGuardTestCase(unittest.TestCase):
    def _build_result(self, **overrides) -> AnalysisResult:
        base = dict(
            code="AAA",
            name="样例A",
            sentiment_score=70,
            trend_prediction="震荡",
            operation_advice="建议买入",
            final_decision="HOLD",
            position_action="HOLD",
            target_weight=0.10,
            delta_amount=0.0,
        )
        base.update(overrides)
        return AnalysisResult(**base)

    def test_portfolio_summary_does_not_emit_stock_level_buy_wording_from_ai_text(self) -> None:
        analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
        results = [
            self._build_result(
                code="AAA",
                name="样例A",
                operation_advice="强烈建议优先买入",
                final_decision="HOLD",
                position_action="HOLD",
                target_weight=0.12,
                delta_amount=0.0,
            ),
            self._build_result(
                code="BBB",
                name="样例B",
                operation_advice="可考虑加仓",
                final_decision="SELL",
                position_action="REDUCE",
                target_weight=0.03,
                delta_amount=-2000.0,
            ),
        ]

        summary = analyzer.generate_portfolio_summary(results)

        self.assertIn("仅基于确定性动作模型汇总", summary)
        self.assertIn("BUY 0 / HOLD 1 / SELL 1", summary)
        self.assertIn("REDUCE 1", summary)
        self.assertIn("调仓净额：-2,000.00", summary)
        self.assertIn("不输出个股买卖命名", summary)
        self.assertNotIn("样例A", summary)
        self.assertNotIn("AAA", summary)
        self.assertNotIn("强烈建议优先买入", summary)


if __name__ == "__main__":
    unittest.main()
