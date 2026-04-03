# -*- coding: utf-8 -*-

import os
import tempfile
import unittest
from datetime import date

from src.services.paper_portfolio_service import PaperPortfolioService
from src.storage import DatabaseManager, PaperPortfolioSnapshot


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
        self.assertIn("invalid current price", overview["latest_simulated_trades"][0]["reason"])
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

    def test_insufficient_cash_buy_is_skipped_and_cash_never_negative(self):
        self.service.init_from_current()
        overview = self.service.apply_analysis_results([
            {
                "code": "BBB",
                "position_action": "OPEN",
                "analysis_status": "OK",
                "current_price": 10.0,
                "target_quantity": 50,  # 500 > current cash 100
            }
        ])
        self.assertGreaterEqual(overview["cash"], 0.0)
        self.assertEqual(overview["cash"], 100.0)
        self.assertEqual(len([h for h in overview["holdings"] if h["code"] == "BBB"]), 0)
        self.assertIn("insufficient cash", overview["latest_simulated_trades"][0]["reason"])
        self.assertFalse(overview["latest_simulated_trades"][0]["executed"])

    def test_malformed_target_payload_is_skipped_without_crash(self):
        self.service.init_from_current()
        overview = self.service.apply_analysis_results([
            {
                "code": "AAA",
                "position_action": "ADD",
                "analysis_status": "OK",
                "current_price": 10.0,
                "target_weight": "abc",
            },
            {
                "code": "AAA",
                "position_action": "HOLD",
                "analysis_status": "OK",
                "current_price": 10.0,
            },
        ])
        self.assertEqual(overview["cash"], 100.0)
        holding = next(x for x in overview["holdings"] if x["code"] == "AAA")
        self.assertEqual(holding["quantity"], 10.0)
        reasons = [t["reason"] for t in overview["latest_simulated_trades"][:2]]
        self.assertTrue(any("missing target info" in str(r) for r in reasons))

    def test_target_weight_uses_updated_portfolio_value_after_previous_trade(self):
        self.service.init_from_current()
        overview = self.service.apply_analysis_results([
            # First trade updates total value from 200 to 300 by repricing/executing AAA at 20.
            {"code": "AAA", "position_action": "REDUCE", "analysis_status": "OK", "current_price": 20.0, "target_quantity": 5},
            # Second trade must use updated total_value=300, so target qty should be 15 shares.
            {"code": "BBB", "position_action": "OPEN", "analysis_status": "OK", "current_price": 10.0, "target_weight": 0.5},
        ])
        holdings = {h["code"]: h for h in overview["holdings"]}
        self.assertEqual(holdings["AAA"]["quantity"], 5.0)
        self.assertEqual(holdings["BBB"]["quantity"], 15.0)
        self.assertEqual(overview["cash"], 50.0)

    def test_zero_delta_after_clamp_is_logged_as_noop_not_executed(self):
        self.service.init_from_current()
        overview = self.service.apply_analysis_results([
            # REDUCE but target is above current, so it is clamped to current qty => delta=0.
            {"code": "AAA", "position_action": "REDUCE", "analysis_status": "OK", "current_price": 10.0, "target_quantity": 15},
        ])
        trade = overview["latest_simulated_trades"][0]
        self.assertFalse(trade["executed"])
        self.assertIn("no-op", str(trade["reason"]).lower())
        holding = next(x for x in overview["holdings"] if x["code"] == "AAA")
        self.assertEqual(holding["quantity"], 10.0)

    def test_snapshot_matches_holdings_after_open_trade(self):
        self.service.init_from_current()
        overview = self.service.apply_analysis_results([
            {"code": "BBB", "position_action": "OPEN", "analysis_status": "OK", "current_price": 5.0, "target_quantity": 4},
        ])

        holdings = overview["holdings"]
        equity_from_holdings = round(sum(float(h["market_value"]) for h in holdings), 2)
        total_from_holdings = round(float(overview["cash"]) + equity_from_holdings, 2)

        with self.db.get_session() as session:
            latest_snapshot = session.query(PaperPortfolioSnapshot).order_by(
                PaperPortfolioSnapshot.snapshot_date.desc(),
                PaperPortfolioSnapshot.created_at.desc(),
            ).first()

        self.assertIsNotNone(latest_snapshot)
        self.assertAlmostEqual(float(latest_snapshot.cash), float(overview["cash"]), places=2)
        self.assertAlmostEqual(float(latest_snapshot.equity_value), equity_from_holdings, places=2)
        self.assertAlmostEqual(float(latest_snapshot.total_value), total_from_holdings, places=2)

    def test_nan_and_inf_price_are_skipped_as_invalid(self):
        self.service.init_from_current()
        overview = self.service.apply_analysis_results([
            {"code": "BBB", "position_action": "OPEN", "analysis_status": "OK", "current_price": "nan", "target_quantity": 3},
            {"code": "CCC", "position_action": "OPEN", "analysis_status": "OK", "current_price": "inf", "target_quantity": 3},
        ])

        self.assertEqual(len([h for h in overview["holdings"] if h["code"] in {"BBB", "CCC"}]), 0)
        latest_two = overview["latest_simulated_trades"][:2]
        self.assertTrue(all(not t["executed"] for t in latest_two))
        self.assertTrue(all("invalid current price" in str(t["reason"]).lower() for t in latest_two))

    def test_existing_holding_target_weight_uses_repriced_current_symbol(self):
        self.service.init_from_current()
        overview = self.service.apply_analysis_results([
            # AAA is existing holding. Reprice from 10 -> 20, then target_weight 0.5 should land near 5 shares.
            {"code": "AAA", "position_action": "REDUCE", "analysis_status": "OK", "current_price": 20.0, "target_weight": 0.5},
        ])
        holding = next(x for x in overview["holdings"] if x["code"] == "AAA")
        # total value for target calc should be cash(100)+repriced AAA(200)=300; 50% => 150 => qty 7.5 at 20.
        self.assertAlmostEqual(float(holding["quantity"]), 7.5, places=6)

    def test_duplicate_symbol_in_same_batch_uses_latest_quantity(self):
        self.service.init_from_current()
        overview = self.service.apply_analysis_results([
            {"code": "BBB", "position_action": "OPEN", "analysis_status": "OK", "current_price": 10.0, "target_quantity": 2},
            {"code": "BBB", "position_action": "ADD", "analysis_status": "OK", "current_price": 10.0, "target_quantity": 5},
        ])
        holdings = {h["code"]: h for h in overview["holdings"]}
        self.assertEqual(float(holdings["BBB"]["quantity"]), 5.0)
        # cash: 100 - (2*10) - (3*10) = 50
        self.assertEqual(float(overview["cash"]), 50.0)


if __name__ == "__main__":
    unittest.main()
