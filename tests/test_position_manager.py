# -*- coding: utf-8 -*-

import unittest

from src.core.position_manager import PositionManager


class PositionManagerTestCase(unittest.TestCase):
    def setUp(self):
        self.manager = PositionManager()

    def test_open_when_no_position_and_buy(self):
        decision = self.manager.decide(
            current_weight=0.0,
            avg_cost=0,
            available_cash=10000,
            final_decision="BUY",
            market_regime="NEUTRAL",
            event_risk="LOW",
            data_quality_flag="OK",
        )
        self.assertEqual(decision.action, "OPEN")
        self.assertGreater(decision.target_weight, 0)

    def test_reduce_when_risk_off(self):
        decision = self.manager.decide(
            current_weight=0.25,
            avg_cost=10,
            available_cash=1000,
            final_decision="HOLD",
            market_regime="RISK_OFF",
            event_risk="MEDIUM",
            data_quality_flag="OK",
        )
        self.assertEqual(decision.action, "REDUCE")
        self.assertLess(decision.target_weight, 0.25)

    def test_close_on_sell(self):
        decision = self.manager.decide(
            current_weight=0.2,
            avg_cost=10,
            available_cash=1000,
            final_decision="SELL",
            market_regime="NEUTRAL",
            event_risk="LOW",
            data_quality_flag="OK",
        )
        self.assertEqual(decision.action, "CLOSE")
        self.assertEqual(decision.target_weight, 0.0)


if __name__ == "__main__":
    unittest.main()
