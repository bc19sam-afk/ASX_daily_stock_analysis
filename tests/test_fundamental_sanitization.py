import unittest

from src.analyzer import AnalysisResult, GeminiAnalyzer


class TestFundamentalSanitization(unittest.TestCase):
    def setUp(self) -> None:
        self.analyzer = GeminiAnalyzer(api_key=None)

    def test_format_prompt_sanitizes_abnormal_fundamentals_to_na(self) -> None:
        context = {
            "code": "CBA.AX",
            "date": "2026-04-03",
            "today": {"close": 99.1},
            "fundamentals": {
                "PE": -12.4,
                "股息率": "999%",
                "EPS增速": "2000%",
                "派息率": "130%",
                "ROE": "18%",
            },
        }

        prompt = self.analyzer._format_prompt(context, "CBA")

        self.assertEqual(context["fundamentals"]["PE"], "N/A")
        self.assertEqual(context["fundamentals"]["股息率"], "N/A")
        self.assertEqual(context["fundamentals"]["EPS增速"], "N/A")
        self.assertEqual(context["fundamentals"]["派息率"], "N/A")
        self.assertEqual(context["fundamentals"]["ROE"], "18%")
        self.assertIn("基本面数据质量约束", prompt)
        self.assertIn("降级为 N/A", prompt)

    def test_guard_downgrades_fundamental_narrative_and_confidence(self) -> None:
        context = {"_fundamentals_sanitized_fields": ["PE", "股息率"]}
        result = AnalysisResult(
            code="CBA.AX",
            name="CBA",
            sentiment_score=85,
            trend_prediction="看多",
            operation_advice="买入",
            confidence_level="高",
            fundamental_analysis="估值和分红均优异，基本面强劲",
            risk_warning="波动率上升",
        )

        guarded = self.analyzer._apply_fundamental_sanitization_guard(result, context)

        self.assertEqual(
            guarded.fundamental_analysis,
            "N/A（关键基本面指标存在异常值，已禁用基本面自动解读）",
        )
        self.assertEqual(guarded.confidence_level, "中")
        self.assertEqual(guarded.data_quality_flag, "MISSING")
        self.assertIn("PE", guarded.risk_warning)
        self.assertIn("股息率", guarded.risk_warning)


if __name__ == "__main__":
    unittest.main()
