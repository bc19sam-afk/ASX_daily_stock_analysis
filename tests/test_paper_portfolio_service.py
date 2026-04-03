# -*- coding: utf-8 -*-

import os
import tempfile
import unittest
from datetime import date

from src.services.paper_portfolio_service import PaperPortfolioService
from src.storage import DatabaseManager


class PaperPortfolioServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        DatabaseManager.reset_instance()
        self.db = DatabaseManager(db_url=f"sqlite:///{os.path.join(self.tmp.name, 'paper_portfolio.db')}")
        self.service = PaperPortfolioService(self.db)

        self.db.upsert_portfolio_position(
            code="AAA",
            name="AAA",
            quantity=10,
            avg_cost=10,
            current_price=10,
            weight=0.5,
            market_value=100,
        )
        self.db.save_account_snapshot(
            snapshot_date=date.today(),
            cash=100,
            equity_value=100,
            total_value=200,
            note="real_init",
        )

    def tearDown(self):
        DatabaseManager.reset_instance()
        self.tmp.cleanup()

    def test_init_from_current_copies_real_without_mutating_real(self):
        real_before = self.db.get_portfolio_overview()
        paper = self.service.init_from_current()

        real_after = self.db.get_portfolio_overview()
        self.assertEqual(real_before["cash"], real_after["cash"])
        self.assertEqual(real_before["total_value"], real_after["total_value"])
        self.assertEqual(len(real_after["holdings"]), 1)

        self.assertTrue(paper["initialized"])
        self.assertEqual(paper["cash"], real_before["cash"])
        self.assertEqual(paper["total_value"], real_before["total_value"])

    def test_apply_only_affects_paper_portfolio(self):
        self.service.init_from_current()
        real_before = self.db.get_portfolio_overview()

        self.service.apply_analysis_results([
            {"code": "AAA", "position_action": "CLOSE", "analysis_status": "OK", "current_price": 10.0}
        ])

        real_after = self.db.get_portfolio_overview()
        self.assertEqual(real_before["cash"], real_after["cash"])
        self.assertEqual(real_before["total_value"], real_after["total_value"])

    def test_failed_and_degraded_are_not_executed(self):
        self.service.init_from_current()
        overview = self.service.apply_analysis_results([
            {"code": "AAA", "position_action": "CLOSE", "analysis_status": "FAILED", "current_price": 10.0},
            {"code": "AAA", "position_action": "CLOSE", "analysis_status": "DEGRADED", "current_price": 10.0},
        ])
        holding = next(x for x in overview["holdings"] if x["code"] == "AAA")
        self.assertEqual(holding["quantity"], 10.0)
        self.assertTrue(all(not t["executed"] for t in overview["latest_simulated_trades"][:2]))

    def test_hold_action_is_not_executed(self):
        self.service.init_from_current()
        overview = self.service.apply_analysis_results([
            {"code": "AAA", "position_action": "HOLD", "analysis_status": "OK", "current_price": 10.0}
        ])
        holding = next(x for x in overview["holdings"] if x["code"] == "AAA")
        self.assertEqual(holding["quantity"], 10.0)
        self.assertFalse(overview["latest_simulated_trades"][0]["executed"])

    def test_open_add_reduce_close_update_holdings_cash_and_trades(self):
        self.service.init_from_current()
        overview = self.service.apply_analysis_results([
            {"code": "BBB", "position_action": "OPEN", "analysis_status": "OK", "current_price": 5.0, "target_quantity": 4},
            {"code": "AAA", "position_action": "ADD", "analysis_status": "OK", "current_price": 10.0, "target_quantity": 12},
            {"code": "AAA", "position_action": "REDUCE", "analysis_status": "OK", "current_price": 10.0, "target_quantity": 7},
            {"code": "BBB", "position_action": "CLOSE", "analysis_status": "OK", "current_price": 5.0},
        ])
        holdings = {h["code"]: h for h in overview["holdings"]}
        self.assertEqual(holdings["AAA"]["quantity"], 7.0)
        self.assertNotIn("BBB", holdings)
        self.assertEqual(overview["cash"], 130.0)
        executed = [t for t in overview["latest_simulated_trades"] if t["executed"]]
        self.assertGreaterEqual(len(executed), 4)

    def test_missing_price_is_skipped_with_reason(self):
        self.service.init_from_current()
        overview = self.service.apply_analysis_results([
            {"code": "AAA", "position_action": "REDUCE", "analysis_status": "OK", "target_quantity": 8}
        ])
        self.assertIn("missing current price", overview["latest_simulated_trades"][0]["reason"])
        holding = next(x for x in overview["holdings"] if x["code"] == "AAA")
        self.assertEqual(holding["quantity"], 10.0)

    def test_reinit_rejected_without_force_and_allowed_with_force(self):
        first = self.service.init_from_current(force=False)
        self.assertTrue(first["initialized"])

        with self.assertRaises(ValueError):
            self.service.init_from_current(force=False)

        self.db.save_account_snapshot(
            snapshot_date=date.today(),
            cash=150,
            equity_value=100,
            total_value=250,
            note="real_changed",
        )
        forced = self.service.init_from_current(force=True)
        self.assertEqual(forced["cash"], 150.0)


if __name__ == "__main__":
    unittest.main()
