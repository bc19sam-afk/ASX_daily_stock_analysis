# -*- coding: utf-8 -*-
"""Unit tests for backtest engine."""

import unittest
from dataclasses import dataclass
from datetime import date, timedelta

from src.core.backtest_engine import BacktestEngine, EvaluationConfig


@dataclass
class Bar:
    date: date
    high: float
    low: float
    close: float


class BacktestEngineTestCase(unittest.TestCase):
    def _bars(self, start: date, closes, highs=None, lows=None):
        highs = highs or closes
        lows = lows or closes
        bars = []
        for i, c in enumerate(closes):
            bars.append(Bar(date=start + timedelta(days=i + 1), high=highs[i], low=lows[i], close=c))
        return bars

    def test_buy_win_when_up(self):
        cfg = EvaluationConfig(eval_window_days=3, neutral_band_pct=2.0)
        bars = self._bars(date(2024, 1, 1), [102, 104, 105], highs=[103, 105, 106], lows=[101, 103, 104])
        res = BacktestEngine.evaluate_single(
            operation_advice="买入",
            analysis_date=date(2024, 1, 1),
            start_price=100,
            forward_bars=bars,
            stop_loss=95,
            take_profit=110,
            config=cfg,
        )
        self.assertEqual(res["eval_status"], "completed")
        self.assertEqual(res["outcome"], "win")
        self.assertTrue(res["direction_correct"])  # up

    def test_sell_win_when_down_cash(self):
        cfg = EvaluationConfig(eval_window_days=3, neutral_band_pct=2.0)
        bars = self._bars(date(2024, 1, 1), [98, 97, 96], highs=[99, 98, 97], lows=[97, 96, 95])
        res = BacktestEngine.evaluate_single(
            operation_advice="卖出",
            analysis_date=date(2024, 1, 1),
            start_price=100,
            forward_bars=bars,
            stop_loss=95,
            take_profit=110,
            config=cfg,
        )
        self.assertEqual(res["position_recommendation"], "cash")
        self.assertEqual(res["outcome"], "win")
        self.assertEqual(res["simulated_return_pct"], 0.0)
        self.assertEqual(res["first_hit"], "not_applicable")

    def test_wait_maps_to_cash_and_flat_direction(self):
        cfg = EvaluationConfig(eval_window_days=3, neutral_band_pct=2.0)
        # Stock drops ~5%: AI said wait (neutral), stock moved significantly → loss
        bars = self._bars(date(2024, 1, 1), [98, 96, 95], highs=[99, 97, 96], lows=[97, 95, 94])
        res = BacktestEngine.evaluate_single(
            operation_advice="观望",
            analysis_date=date(2024, 1, 1),
            start_price=100,
            forward_bars=bars,
            stop_loss=95,
            take_profit=110,
            config=cfg,
        )
        self.assertEqual(res["position_recommendation"], "cash")
        self.assertEqual(res["direction_expected"], "flat")
        self.assertEqual(res["outcome"], "loss")

    def test_hold_win_when_flat(self):
        cfg = EvaluationConfig(eval_window_days=3, neutral_band_pct=2.0)
        bars = self._bars(date(2024, 1, 1), [100.5, 100.2, 101], highs=[101, 101, 101], lows=[99.8, 99.9, 100])
        res = BacktestEngine.evaluate_single(
            operation_advice="持有",
            analysis_date=date(2024, 1, 1),
            start_price=100,
            forward_bars=bars,
            stop_loss=None,
            take_profit=None,
            config=cfg,
        )
        self.assertEqual(res["outcome"], "win")

    def test_hold_win_when_up(self):
        cfg = EvaluationConfig(eval_window_days=3, neutral_band_pct=2.0)
        bars = self._bars(date(2024, 1, 1), [102, 103, 104], highs=[103, 104, 105], lows=[101, 102, 103])
        res = BacktestEngine.evaluate_single(
            operation_advice="持有",
            analysis_date=date(2024, 1, 1),
            start_price=100,
            forward_bars=bars,
            stop_loss=None,
            take_profit=None,
            config=cfg,
        )
        self.assertEqual(res["outcome"], "win")

    def test_stop_loss_hit_first(self):
        cfg = EvaluationConfig(eval_window_days=3, neutral_band_pct=2.0)
        bars = self._bars(date(2024, 1, 1), [99, 98, 97], highs=[101, 100, 99], lows=[94, 97, 96])
        res = BacktestEngine.evaluate_single(
            operation_advice="买入",
            analysis_date=date(2024, 1, 1),
            start_price=100,
            forward_bars=bars,
            stop_loss=95,
            take_profit=110,
            config=cfg,
        )
        self.assertTrue(res["hit_stop_loss"])
        self.assertEqual(res["first_hit"], "stop_loss")
        self.assertEqual(res["simulated_exit_reason"], "stop_loss")

    def test_take_profit_hit_first(self):
        cfg = EvaluationConfig(eval_window_days=3, neutral_band_pct=2.0)
        bars = self._bars(date(2024, 1, 1), [105, 106, 107], highs=[111, 107, 108], lows=[103, 105, 106])
        res = BacktestEngine.evaluate_single(
            operation_advice="买入",
            analysis_date=date(2024, 1, 1),
            start_price=100,
            forward_bars=bars,
            stop_loss=95,
            take_profit=110,
            config=cfg,
        )
        self.assertTrue(res["hit_take_profit"])
        self.assertEqual(res["first_hit"], "take_profit")
        self.assertEqual(res["simulated_exit_reason"], "take_profit")

    def test_ambiguous_same_day(self):
        cfg = EvaluationConfig(eval_window_days=2, neutral_band_pct=2.0)
        bars = self._bars(date(2024, 1, 1), [100, 100], highs=[111, 100], lows=[94, 99])
        res = BacktestEngine.evaluate_single(
            operation_advice="买入",
            analysis_date=date(2024, 1, 1),
            start_price=100,
            forward_bars=bars,
            stop_loss=95,
            take_profit=110,
            config=cfg,
        )
        self.assertEqual(res["first_hit"], "ambiguous")
        self.assertEqual(res["simulated_exit_reason"], "ambiguous_stop_loss")

    def test_buy_loss_when_down(self):
        cfg = EvaluationConfig(eval_window_days=3, neutral_band_pct=2.0)
        bars = self._bars(date(2024, 1, 1), [98, 96, 95], highs=[99, 97, 96], lows=[97, 95, 94])
        res = BacktestEngine.evaluate_single(
            operation_advice="买入",
            analysis_date=date(2024, 1, 1),
            start_price=100,
            forward_bars=bars,
            stop_loss=93,
            take_profit=110,
            config=cfg,
        )
        self.assertEqual(res["eval_status"], "completed")
        self.assertEqual(res["outcome"], "loss")
        self.assertFalse(res["direction_correct"])

    def test_hold_loss_when_down(self):
        cfg = EvaluationConfig(eval_window_days=3, neutral_band_pct=2.0)
        bars = self._bars(date(2024, 1, 1), [98, 96, 95], highs=[99, 97, 96], lows=[97, 95, 94])
        res = BacktestEngine.evaluate_single(
            operation_advice="持有",
            analysis_date=date(2024, 1, 1),
            start_price=100,
            forward_bars=bars,
            stop_loss=None,
            take_profit=None,
            config=cfg,
        )
        self.assertEqual(res["direction_expected"], "not_down")
        self.assertEqual(res["outcome"], "loss")
        self.assertFalse(res["direction_correct"])

    def test_sell_loss_when_up(self):
        cfg = EvaluationConfig(eval_window_days=3, neutral_band_pct=2.0)
        bars = self._bars(date(2024, 1, 1), [102, 104, 106], highs=[103, 105, 107], lows=[101, 103, 105])
        res = BacktestEngine.evaluate_single(
            operation_advice="卖出",
            analysis_date=date(2024, 1, 1),
            start_price=100,
            forward_bars=bars,
            stop_loss=None,
            take_profit=None,
            config=cfg,
        )
        self.assertEqual(res["position_recommendation"], "cash")
        self.assertEqual(res["direction_expected"], "down")
        self.assertEqual(res["outcome"], "loss")
        self.assertFalse(res["direction_correct"])

    def test_neutral_outcome(self):
        cfg = EvaluationConfig(eval_window_days=3, neutral_band_pct=2.0)
        bars = self._bars(date(2024, 1, 1), [100.5, 100.2, 100.8], highs=[101, 101, 101], lows=[100, 100, 100])
        res = BacktestEngine.evaluate_single(
            operation_advice="买入",
            analysis_date=date(2024, 1, 1),
            start_price=100,
            forward_bars=bars,
            stop_loss=None,
            take_profit=None,
            config=cfg,
        )
        self.assertEqual(res["direction_expected"], "up")
        self.assertEqual(res["outcome"], "neutral")
        self.assertIsNone(res["direction_correct"])

    def test_direction_correct_false_buy_down(self):
        cfg = EvaluationConfig(eval_window_days=3, neutral_band_pct=2.0)
        bars = self._bars(date(2024, 1, 1), [97, 95, 94], highs=[98, 96, 95], lows=[96, 94, 93])
        res = BacktestEngine.evaluate_single(
            operation_advice="buy",
            analysis_date=date(2024, 1, 1),
            start_price=100,
            forward_bars=bars,
            stop_loss=None,
            take_profit=None,
            config=cfg,
        )
        self.assertEqual(res["direction_expected"], "up")
        self.assertEqual(res["outcome"], "loss")
        self.assertFalse(res["direction_correct"])

    def test_structured_fields_override_conflicting_legacy_advice(self):
        cfg = EvaluationConfig(eval_window_days=3, neutral_band_pct=2.0)
        bars = self._bars(date(2024, 1, 1), [98, 97, 96], highs=[99, 98, 97], lows=[97, 96, 95])
        res = BacktestEngine.evaluate_single(
            operation_advice="买入",  # conflicting legacy text
            final_decision="SELL",
            position_action="CLOSE",
            target_weight=0.0,
            current_weight=0.2,
            analysis_date=date(2024, 1, 1),
            start_price=100,
            forward_bars=bars,
            stop_loss=None,
            take_profit=None,
            config=cfg,
        )
        self.assertEqual(res["decision_source"], "final_decision")
        self.assertEqual(res["direction_expected"], "down")
        self.assertEqual(res["position_recommendation"], "cash")
        self.assertEqual(res["outcome"], "win")

    def test_hold_invested_vs_hold_near_zero_exposure(self):
        cfg = EvaluationConfig(eval_window_days=3, neutral_band_pct=2.0)
        bars = self._bars(date(2024, 1, 1), [99.5, 99.0, 98.5], highs=[100.0, 99.8, 99.2], lows=[99.2, 98.8, 98.3])

        invested = BacktestEngine.evaluate_single(
            operation_advice="观望",
            final_decision="HOLD",
            position_action="HOLD",
            target_weight=0.15,
            current_weight=0.12,
            analysis_date=date(2024, 1, 1),
            start_price=100,
            forward_bars=bars,
            stop_loss=None,
            take_profit=None,
            config=cfg,
        )
        self.assertEqual(invested["position_recommendation"], "long")
        self.assertEqual(invested["direction_expected"], "not_down")

        near_zero = BacktestEngine.evaluate_single(
            operation_advice="持有",
            final_decision="HOLD",
            position_action="HOLD",
            target_weight=0.001,
            current_weight=0.0,
            analysis_date=date(2024, 1, 1),
            start_price=100,
            forward_bars=bars,
            stop_loss=None,
            take_profit=None,
            config=cfg,
        )
        self.assertEqual(near_zero["position_recommendation"], "cash")
        self.assertEqual(near_zero["direction_expected"], "flat")

    def test_insufficient_data(self):
        cfg = EvaluationConfig(eval_window_days=5, neutral_band_pct=2.0)
        bars = self._bars(date(2024, 1, 1), [100, 101])
        res = BacktestEngine.evaluate_single(
            operation_advice="买入",
            analysis_date=date(2024, 1, 1),
            start_price=100,
            forward_bars=bars,
            stop_loss=None,
            take_profit=None,
            config=cfg,
        )
        self.assertEqual(res["eval_status"], "insufficient_data")

    def test_unrecognized_advice_defaults_to_cash(self):
        cfg = EvaluationConfig(eval_window_days=3, neutral_band_pct=2.0)
        bars = self._bars(date(2024, 1, 1), [102, 104, 105], highs=[103, 105, 106], lows=[101, 103, 104])
        res = BacktestEngine.evaluate_single(
            operation_advice="some gibberish text",
            analysis_date=date(2024, 1, 1),
            start_price=100,
            forward_bars=bars,
            stop_loss=None,
            take_profit=None,
            config=cfg,
        )
        self.assertEqual(res["position_recommendation"], "cash")

    def test_action_effectiveness_in_summary(self):
        @dataclass
        class Row:
            eval_status: str
            position_recommendation: str
            outcome: str
            direction_correct: bool
            stock_return_pct: float
            simulated_return_pct: float
            hit_stop_loss: bool
            hit_take_profit: bool
            first_hit: str
            first_hit_trading_days: int
            operation_advice: str

        rows = [
            Row("completed", "long", "win", True, 5, 5, False, True, "take_profit", 2, "买入"),
            Row("completed", "long", "loss", False, -3, -3, True, False, "stop_loss", 1, "加仓"),
            Row("completed", "cash", "win", True, -2, 0, None, None, "not_applicable", None, "减仓"),
            Row("completed", "cash", "win", True, -4, 0, None, None, "not_applicable", None, "卖出"),
        ]
        summary = BacktestEngine.compute_summary(
            results=rows,
            scope="overall",
            code="__overall__",
            eval_window_days=10,
            engine_version="v1",
        )
        action_eff = summary["diagnostics"]["action_effectiveness"]
        self.assertIn("OPEN", action_eff)
        self.assertIn("ADD", action_eff)
        self.assertIn("REDUCE", action_eff)
        self.assertIn("CLOSE", action_eff)

    def test_none_empty_advice_defaults_to_cash(self):
        for advice in [None, "", "   "]:
            pos = BacktestEngine.infer_position_recommendation(advice)
            direction = BacktestEngine.infer_direction_expected(advice)
            self.assertEqual(pos, "cash", f"Expected cash for advice={advice!r}")
            self.assertEqual(direction, "flat", f"Expected flat for advice={advice!r}")

    def test_negated_sell_not_classified_bearish(self):
        # "do not sell" negates "sell" — should NOT be direction=down
        self.assertNotEqual(BacktestEngine.infer_direction_expected("do not sell"), "down")

    def test_chinese_negated_sell_not_bearish(self):
        # "不要卖出" = "don't sell" — should NOT be direction=down
        self.assertNotEqual(BacktestEngine.infer_direction_expected("不要卖出"), "down")

    def test_wait_then_buy_classified_as_cash(self):
        # "wait" matches first in priority order → cash
        pos = BacktestEngine.infer_position_recommendation("wait for a dip then buy")
        self.assertEqual(pos, "cash")


if __name__ == "__main__":
    unittest.main()
