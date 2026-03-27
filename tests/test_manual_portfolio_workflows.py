# -*- coding: utf-8 -*-

import os
import tempfile
import unittest
from argparse import Namespace
from unittest.mock import patch

from src.storage import DatabaseManager
import scripts.manual_portfolio_workflows as manual_workflows
from scripts.manual_portfolio_workflows import (
    HoldingInput,
    _parse_holding_rows,
    init_portfolio,
    record_trade,
)


class ManualPortfolioWorkflowTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        DatabaseManager.reset_instance()
        self.db = DatabaseManager(db_url=f"sqlite:///{os.path.join(self.tmp.name, 'manual_workflow.db')}")

    def tearDown(self):
        DatabaseManager.reset_instance()
        self.tmp.cleanup()

    def test_init_with_multiple_holdings(self):
        init_portfolio(
            self.db,
            cash=1000,
            holdings=[
                HoldingInput(code="AAA", quantity=10, avg_cost=10),
                HoldingInput(code="BBB", quantity=5, avg_cost=20),
            ],
        )

        snapshot = self.db.get_latest_account_snapshot()
        self.assertIsNotNone(snapshot)
        self.assertAlmostEqual(snapshot.cash, 1000.0, places=2)
        self.assertAlmostEqual(snapshot.equity_value, 200.0, places=2)
        self.assertAlmostEqual(snapshot.total_value, 1200.0, places=2)

        positions = self.db.get_portfolio_positions(only_open=True)
        self.assertEqual(len(positions), 2)

    def test_first_buy(self):
        init_portfolio(self.db, cash=1000, holdings=[])
        record_trade(self.db, code="AAA", side="BUY", quantity=10, price=20, fee=0)

        pos = self.db.get_portfolio_position("AAA")
        self.assertIsNotNone(pos)
        self.assertAlmostEqual(pos.quantity, 10.0, places=6)
        self.assertAlmostEqual(pos.avg_cost, 20.0, places=6)

        snapshot = self.db.get_latest_account_snapshot()
        self.assertAlmostEqual(snapshot.cash, 800.0, places=2)
        self.assertAlmostEqual(snapshot.equity_value, 200.0, places=2)

    def test_add_to_existing_position(self):
        init_portfolio(
            self.db,
            cash=1000,
            holdings=[HoldingInput(code="AAA", quantity=10, avg_cost=10)],
        )
        record_trade(self.db, code="AAA", side="BUY", quantity=5, price=20, fee=0)

        pos = self.db.get_portfolio_position("AAA")
        self.assertAlmostEqual(pos.quantity, 15.0, places=6)
        self.assertAlmostEqual(pos.avg_cost, (10 * 10 + 5 * 20) / 15, places=6)

    def test_partial_sell(self):
        init_portfolio(
            self.db,
            cash=1000,
            holdings=[HoldingInput(code="AAA", quantity=10, avg_cost=10)],
        )
        record_trade(self.db, code="AAA", side="SELL", quantity=4, price=15, fee=0)

        pos = self.db.get_portfolio_position("AAA")
        self.assertAlmostEqual(pos.quantity, 6.0, places=6)
        self.assertAlmostEqual(pos.avg_cost, 10.0, places=6)

        snapshot = self.db.get_latest_account_snapshot()
        self.assertAlmostEqual(snapshot.cash, 1060.0, places=2)

    def test_full_close(self):
        init_portfolio(
            self.db,
            cash=1000,
            holdings=[HoldingInput(code="AAA", quantity=10, avg_cost=10)],
        )
        record_trade(self.db, code="AAA", side="SELL", quantity=10, price=12, fee=0)

        pos = self.db.get_portfolio_position("AAA")
        self.assertIsNotNone(pos)
        self.assertEqual(pos.status, "CLOSED")
        self.assertAlmostEqual(pos.quantity, 0.0, places=6)

        snapshot = self.db.get_latest_account_snapshot()
        self.assertAlmostEqual(snapshot.equity_value, 0.0, places=2)

    def test_fee_handling(self):
        init_portfolio(self.db, cash=1000, holdings=[])

        record_trade(self.db, code="AAA", side="BUY", quantity=10, price=10, fee=5)
        snapshot_after_buy = self.db.get_latest_account_snapshot()
        self.assertAlmostEqual(snapshot_after_buy.cash, 895.0, places=2)

        record_trade(self.db, code="AAA", side="SELL", quantity=10, price=12, fee=3)
        snapshot_after_sell = self.db.get_latest_account_snapshot()
        self.assertAlmostEqual(snapshot_after_sell.cash, 1012.0, places=2)

    def test_init_rejects_duplicate_codes(self):
        args = Namespace(
            code_1="AAA", quantity_1="10", avg_cost_1="10",
            code_2="aaa", quantity_2="5", avg_cost_2="9",
            code_3="", quantity_3="", avg_cost_3="",
            code_4="", quantity_4="", avg_cost_4="",
            code_5="", quantity_5="", avg_cost_5="",
        )

        with self.assertRaises(ValueError) as exc:
            _parse_holding_rows(args)
        self.assertIn("Duplicate code", str(exc.exception))

    def test_record_trade_requires_init_first(self):
        with self.assertRaises(ValueError) as exc:
            record_trade(self.db, code="AAA", side="BUY", quantity=1, price=10, fee=0)
        self.assertIn("Init Portfolio workflow first", str(exc.exception))

    def test_init_portfolio_is_atomic_on_failure(self):
        original_snapshot_upsert = manual_workflows._upsert_snapshot_in_session

        def fail_snapshot_once(*args, **kwargs):
            raise RuntimeError("forced snapshot failure")

        with patch.object(manual_workflows, "_upsert_snapshot_in_session", side_effect=fail_snapshot_once):
            with self.assertRaises(RuntimeError):
                init_portfolio(
                    self.db,
                    cash=1000,
                    holdings=[HoldingInput(code="AAA", quantity=10, avg_cost=10)],
                )

        # Position should rollback together with snapshot write failure.
        self.assertEqual(len(self.db.get_portfolio_positions(only_open=False)), 0)
        self.assertIsNone(self.db.get_latest_account_snapshot())

        # Ensure helper still works after patch context.
        self.assertIsNotNone(original_snapshot_upsert)

    def test_record_trade_is_atomic_on_failure(self):
        init_portfolio(self.db, cash=1000, holdings=[])

        def fail_snapshot_once(*args, **kwargs):
            raise RuntimeError("forced snapshot failure")

        with patch.object(manual_workflows, "_upsert_snapshot_in_session", side_effect=fail_snapshot_once):
            with self.assertRaises(RuntimeError):
                record_trade(self.db, code="AAA", side="BUY", quantity=10, price=10, fee=0)

        # Position + journal should rollback when snapshot update fails.
        self.assertIsNone(self.db.get_portfolio_position("AAA"))
        self.assertEqual(len(self.db.get_trade_journal(limit=10)), 0)
        snapshot = self.db.get_latest_account_snapshot()
        self.assertAlmostEqual(snapshot.cash, 1000.0, places=2)


if __name__ == "__main__":
    unittest.main()
