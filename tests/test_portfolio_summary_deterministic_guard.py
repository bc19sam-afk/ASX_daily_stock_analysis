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

        self.assertIn("组合动作总览（今日建议）", summary)
        self.assertIn("建议新开仓：0 | 加仓：0 | 持有观察：1 | 减仓：1 | 清仓：0", summary)
        self.assertIn("计划调仓净额：-2,000.00（整体偏减仓）", summary)
        self.assertNotIn("样例A", summary)
        self.assertNotIn("AAA", summary)
        self.assertNotIn("强烈建议优先买入", summary)

    def test_portfolio_summary_net_flat_with_no_actions_is_observation_only(self) -> None:
        analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
        results = [
            self._build_result(code="AAA", position_action="HOLD", delta_amount=0.0),
            self._build_result(code="BBB", position_action="HOLD", delta_amount=0.0),
        ]

        summary = analyzer.generate_portfolio_summary(results)
        self.assertIn("计划调仓净额：0.00（以观察为主）", summary)

    def test_portfolio_summary_net_flat_with_offsetting_actions_is_active_rebalance(self) -> None:
        analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
        results = [
            self._build_result(code="AAA", position_action="ADD", delta_amount=2000.0, final_decision="BUY"),
            self._build_result(code="BBB", position_action="REDUCE", delta_amount=-2000.0, final_decision="SELL"),
        ]

        summary = analyzer.generate_portfolio_summary(results)
        self.assertIn("计划调仓净额：0.00（有换仓/再平衡动作，整体仓位中性）", summary)


if __name__ == "__main__":
    unittest.main()
