# -*- coding: utf-8 -*-
"""Unit tests for BacktestEngine.compute_summary()."""

import unittest
from dataclasses import dataclass

from src.backtest_summary import (
    backtest_claim_matches_summary,
    format_verified_backtest_summary,
    looks_like_backtest_claim,
    normalize_verified_backtest_summary,
)
from src.core.backtest_engine import BacktestEngine


@dataclass
class FakeRow:
    eval_status: str = "completed"
    position_recommendation: str = "long"
    outcome: str = "win"
    direction_correct: bool | None = True
    stock_return_pct: float | None = 1.0
    simulated_return_pct: float | None = 1.0
    hit_stop_loss: bool | None = False
    hit_take_profit: bool | None = False
    first_hit: str | None = "neither"
    first_hit_trading_days: int | None = None
    operation_advice: str | None = "买入"


class BacktestSummaryTestCase(unittest.TestCase):
    def test_verified_summary_normalizes_source_contract(self) -> None:
        summary = normalize_verified_backtest_summary(
            {
                "completed_count": 39,
                "win_rate_pct": 56.67,
                "direction_accuracy_pct": 61.54,
                "avg_stock_return_pct": 0.43,
                "stop_loss_trigger_rate": 12.5,
                "eval_window_days": 10,
                "engine_version": "v1",
                "computed_at": "2026-06-12T05:00:00",
            }
        )

        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(summary["sample_size"], 39)
        self.assertEqual(summary["win_rate"], 56.67)
        self.assertEqual(summary["win_rate_pct"], 56.67)
        self.assertEqual(summary["direction_accuracy"], 61.54)
        self.assertEqual(summary["direction_accuracy_pct"], 61.54)
        self.assertEqual(summary["source"], "backtest_service")
        self.assertEqual(summary["eval_window_days"], 10)
        self.assertEqual(summary["as_of"], "2026-06-12T05:00:00")
        self.assertIn("胜率：56.67%", format_verified_backtest_summary(summary))

    def test_verified_summary_rejects_missing_metrics(self) -> None:
        self.assertIsNone(normalize_verified_backtest_summary({"completed_count": 39}))

    def test_backtest_claim_matcher_fails_closed_without_numeric_claim(self) -> None:
        summary = {"completed_count": 39, "win_rate_pct": 56.67}

        self.assertFalse(backtest_claim_matches_summary(summary, "历史回测胜率较高，建议参考。"))

    def test_backtest_claim_matcher_does_not_capture_next_metric(self) -> None:
        summary = {"completed_count": 39, "win_rate_pct": 56.67, "direction_accuracy_pct": None}

        self.assertTrue(
            backtest_claim_matches_summary(summary, "历史回测方向准确率 N/A，胜率 56.67%，建议参考。")
        )

        real_direction_summary = {
            "completed_count": 39,
            "win_rate_pct": 56.67,
            "direction_accuracy_pct": 61.54,
        }
        self.assertFalse(
            backtest_claim_matches_summary(
                real_direction_summary,
                "历史回测方向准确率 N/A，胜率 56.67%，建议参考。",
            )
        )

    def test_backtest_claim_matcher_checks_every_supported_metric(self) -> None:
        summary = {
            "completed_count": 39,
            "win_rate_pct": 56.67,
            "avg_stock_return_pct": 0.43,
            "stop_loss_trigger_rate": 12.5,
        }

        self.assertFalse(
            backtest_claim_matches_summary(summary, "历史回测胜率 56.67%，平均收益 99%，建议参考。")
        )
        self.assertTrue(
            backtest_claim_matches_summary(summary, "历史回测胜率 56.67%，平均收益 0.43%，止损触发率 12.5%。")
        )

    def test_backtest_claim_matcher_catches_bare_report_metric_claims(self) -> None:
        summary = {"completed_count": 39, "win_rate_pct": 56.67, "direction_accuracy_pct": 61.54}

        self.assertTrue(looks_like_backtest_claim("胜率 78%，建议参考。"))
        self.assertTrue(looks_like_backtest_claim("准确率 81%，建议参考。"))
        self.assertFalse(backtest_claim_matches_summary(summary, "胜率 78%，建议参考。"))
        self.assertFalse(backtest_claim_matches_summary(summary, "准确率 81%，建议参考。"))
        self.assertTrue(backtest_claim_matches_summary(summary, "胜率 56.67%，准确率 61.54%，建议参考。"))

    def test_backtest_claim_matcher_rejects_unsupported_backtest_metrics(self) -> None:
        summary = {"completed_count": 39, "win_rate_pct": 56.67}

        for text in (
            "历史回测胜率 56.67%，最大回撤 30%，建议参考。",
            "历史回测胜率 56.67%，夏普比率 2.0，建议参考。",
            "历史回测胜率 56.67%，收益波动率 99%，建议参考。",
            "历史回测胜率 56.67%，命中率 88%，建议参考。",
        ):
            self.assertTrue(looks_like_backtest_claim(text), text)
            self.assertFalse(backtest_claim_matches_summary(summary, text), text)

    def test_backtest_claim_matcher_checks_metric_after_backtest_context(self) -> None:
        summary = {"completed_count": 39, "win_rate_pct": 56.67}

        for text in (
            "历史回测：胜率 78%，建议参考。",
            "历史回测显示：胜率 78%，建议参考。",
            "根据历史回测，胜率 78%，建议参考。",
        ):
            self.assertTrue(looks_like_backtest_claim(text), text)
            self.assertFalse(backtest_claim_matches_summary(summary, text), text)

        self.assertTrue(backtest_claim_matches_summary(summary, "根据历史回测，胜率 56.67%，建议参考。"))

    def test_backtest_claim_matcher_checks_sample_window_and_parenthesized_metrics(self) -> None:
        summary = {
            "completed_count": 39,
            "win_rate_pct": 56.67,
            "direction_accuracy_pct": 61.54,
            "eval_window_days": 10,
        }

        self.assertTrue(
            backtest_claim_matches_summary(
                summary,
                "历史回测样本数39、窗口10日、胜率（含中性）56.67%、方向准确率61.54%。",
            )
        )
        self.assertFalse(
            backtest_claim_matches_summary(
                summary,
                "历史回测样本数999、窗口20日、胜率（含中性）99%、方向准确率61.54%。",
            )
        )

    def test_backtest_claim_matcher_rejects_qualitative_piggyback_claim(self) -> None:
        summary = {"completed_count": 39, "win_rate_pct": 56.67}

        self.assertFalse(backtest_claim_matches_summary(summary, "历史回测表现优秀，胜率 56.67%，建议参考。"))
        self.assertFalse(backtest_claim_matches_summary(summary, "历史回测胜率 56.67%。历史回测表现优秀。"))
        self.assertFalse(backtest_claim_matches_summary(summary, "历史回测胜率 56.67%，表现较强，建议参考。"))
        self.assertFalse(backtest_claim_matches_summary(summary, "历史回测胜率 56.67%，整体表现较好，建议参考。"))
        self.assertFalse(backtest_claim_matches_summary(summary, "历史回测胜率 56.67%，结果优于平均，建议参考。"))
        self.assertFalse(backtest_claim_matches_summary(summary, "历史回测胜率 56.67%，说明策略可靠，建议参考。"))
        self.assertFalse(backtest_claim_matches_summary(summary, "历史回测胜率 56.67%，命中率高，建议参考。"))
        self.assertFalse(backtest_claim_matches_summary(summary, "历史回测胜率 56.67%，对当前建仓有支撑。"))
        self.assertTrue(looks_like_backtest_claim("历史回测表现优秀。"))

    def test_backtest_claim_detector_catches_common_qualitative_variants(self) -> None:
        summary = {"completed_count": 39, "win_rate_pct": 56.67}

        for text in (
            "历史回测表现较强。",
            "历史回测表现偏强。",
            "历史回测对当前判断有支持。",
            "历史回测结果优于平均。",
            "历史样本表现较强。",
        ):
            self.assertTrue(looks_like_backtest_claim(text), text)
            self.assertFalse(backtest_claim_matches_summary(summary, text), text)

    def test_backtest_claim_matcher_ignores_target_return_outside_backtest_sentence(self) -> None:
        summary = {"completed_count": 39, "win_rate_pct": 56.67}

        self.assertTrue(backtest_claim_matches_summary(summary, "历史回测胜率 56.67%。本次目标收益率 5%。"))
        self.assertTrue(backtest_claim_matches_summary(summary, "历史回测胜率 56.67%，近10日走势稳定。"))
        self.assertTrue(backtest_claim_matches_summary(summary, "历史回测胜率 56.67%，2026年样本已复核。"))
        self.assertFalse(backtest_claim_matches_summary(summary, "历史回测胜率 56.67%，回测收益率 99%。"))

    def test_backtest_claim_matcher_checks_prefix_window_label(self) -> None:
        summary = {
            "completed_count": 39,
            "win_rate_pct": 56.67,
            "direction_accuracy_pct": 61.54,
            "eval_window_days": 10,
        }

        self.assertTrue(backtest_claim_matches_summary(summary, "10天历史回测胜率 56.67%，建议参考。"))
        self.assertTrue(backtest_claim_matches_summary(summary, "近10日历史回测胜率 56.67%，建议参考。"))
        self.assertTrue(backtest_claim_matches_summary(summary, "10天历史胜率 56.67%，建议参考。"))
        self.assertFalse(backtest_claim_matches_summary(summary, "30天历史回测胜率 56.67%，建议参考。"))
        self.assertFalse(backtest_claim_matches_summary(summary, "30天历史胜率 56.67%，建议参考。"))
        self.assertFalse(backtest_claim_matches_summary(summary, "近30日历史胜率 56.67%，建议参考。"))
        self.assertFalse(backtest_claim_matches_summary(summary, "过去30天历史胜率56.67%。"))
        self.assertFalse(backtest_claim_matches_summary(summary, "30日历史准确率 61.54%。"))

    def test_backtest_claim_matcher_checks_suffix_window_label(self) -> None:
        summary = {"completed_count": 39, "win_rate_pct": 56.67, "eval_window_days": 10}

        self.assertTrue(backtest_claim_matches_summary(summary, "历史回测胜率 56.67%（10日窗口）。"))
        self.assertTrue(backtest_claim_matches_summary(summary, "历史回测胜率 56.67%，10日窗口。"))
        self.assertFalse(backtest_claim_matches_summary(summary, "历史回测胜率 56.67%（30日窗口）。"))
        self.assertFalse(backtest_claim_matches_summary(summary, "历史回测胜率 56.67%，30日窗口。"))

    def test_backtest_claim_detector_ignores_non_backtest_numeric_context(self) -> None:
        for text in (
            "同行估值样本数 12，PE 中位数合理。",
            "新闻样本数 3，情绪偏正面。",
            "财报历史收入增长稳定，样本数 10。",
            "财报历史收入增长稳定。",
            "本次目标平均收益 5%。",
            "组合平均收益 3%。",
            "准确率 60% 的财报预测。",
        ):
            self.assertFalse(looks_like_backtest_claim(text), text)

    def test_trigger_rates_use_applicable_denominators(self) -> None:
        # One row has stop-loss configured, one row doesn't.
        rows = [
            FakeRow(hit_stop_loss=True, hit_take_profit=None, first_hit="stop_loss"),
            FakeRow(hit_stop_loss=None, hit_take_profit=True, first_hit="take_profit"),
        ]

        summary = BacktestEngine.compute_summary(
            results=rows,
            scope="stock",
            code="600519",
            eval_window_days=3,
            engine_version="v1",
        )

        # stop_loss_trigger_rate denominator should be 1 (only applicable row)
        self.assertEqual(summary["stop_loss_trigger_rate"], 100.0)

        # take_profit_trigger_rate denominator should be 1 (only applicable row)
        self.assertEqual(summary["take_profit_trigger_rate"], 100.0)

        # ambiguous_rate denominator should be 2 (any target applicable)
        self.assertEqual(summary["ambiguous_rate"], 0.0)
        self.assertEqual(summary["decision_accuracy_pct"], summary["direction_accuracy_pct"])
        self.assertEqual(summary["decision_win_rate_pct"], summary["win_rate_pct"])


if __name__ == "__main__":
    unittest.main()
