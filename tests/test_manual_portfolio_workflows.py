# -*- coding: utf-8 -*-

import os
import tempfile
import unittest
from argparse import Namespace
from contextlib import contextmanager
from unittest.mock import patch

from src.storage import DatabaseManager
import scripts.manual_portfolio_workflows as manual_workflows
from datetime import date, datetime
from scripts.manual_portfolio_workflows import (
    HoldingInput,
    _parse_holding_rows,
    init_portfolio,
    record_cash_adjustment,
    record_trade,
)
from src.storage import AccountSnapshot, PortfolioPosition


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

    def test_init_portfolio_normalizes_common_asx_suffix_alias(self):
        init_portfolio(
            self.db,
            cash=1000,
            holdings=[HoldingInput(code="NHF.ASX", quantity=10, avg_cost=20)],
        )

        self.assertIsNone(self.db.get_portfolio_position("NHF.ASX"))
        self.assertIsNotNone(self.db.get_portfolio_position("NHF.AX"))

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

    def test_record_trade_normalizes_common_asx_suffix_alias(self):
        init_portfolio(self.db, cash=1000, holdings=[])
        record_trade(self.db, code="NHF.ASX", side="BUY", quantity=10, price=20, fee=0)

        self.assertIsNone(self.db.get_portfolio_position("NHF.ASX"))
        pos = self.db.get_portfolio_position("NHF.AX")
        self.assertIsNotNone(pos)
        self.assertAlmostEqual(pos.quantity, 10.0, places=6)
        journal = self.db.get_trade_journal(limit=10)
        self.assertEqual(journal[0].code, "NHF.AX")

    def test_record_trade_merges_existing_common_asx_suffix_alias(self):
        with self.db.get_session() as session:
            session.add(
                AccountSnapshot(
                    snapshot_date=date.today(),
                    cash=1000.0,
                    equity_value=200.0,
                    total_value=1200.0,
                    note="legacy_alias_fixture",
                    created_at=datetime.now(),
                )
            )
            session.add(
                PortfolioPosition(
                    code="NHF.ASX",
                    name="NHF.ASX",
                    quantity=10.0,
                    avg_cost=20.0,
                    current_price=20.0,
                    market_value=200.0,
                    weight=0.1667,
                    status="OPEN",
                    opened_at=datetime.now(),
                    updated_at=datetime.now(),
                )
            )
            session.commit()

        record_trade(self.db, code="NHF.AX", side="BUY", quantity=5, price=20, fee=0)

        self.assertIsNone(self.db.get_portfolio_position("NHF.ASX"))
        pos = self.db.get_portfolio_position("NHF.AX")
        self.assertIsNotNone(pos)
        self.assertAlmostEqual(pos.quantity, 15.0, places=6)
        self.assertEqual(pos.name, "NHF.AX")

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

    def test_cash_adjustment_adds_dividend_cash_before_buy(self):
        init_portfolio(self.db, cash=1940.37, holdings=[])

        record_cash_adjustment(self.db, amount=62.12, reason="LAU Dividend 2026-04-17")
        record_trade(self.db, code="XRO.AX", side="BUY", quantity=26, price=75.5, fee=3)

        snapshot = self.db.get_latest_account_snapshot()
        self.assertAlmostEqual(snapshot.cash, 36.49, places=2)

        pos = self.db.get_portfolio_position("XRO.AX")
        self.assertIsNotNone(pos)
        self.assertAlmostEqual(pos.quantity, 26.0, places=6)

    def test_cash_adjustment_records_cash_only_and_keeps_integrity(self):
        init_portfolio(self.db, cash=100.0, holdings=[])

        record_cash_adjustment(self.db, amount=25.5, reason="deposit")

        snapshot = self.db.get_latest_account_snapshot()
        self.assertAlmostEqual(snapshot.cash, 125.5, places=2)
        self.assertAlmostEqual(snapshot.total_value, 125.5, places=2)

        journal = self.db.get_trade_journal(limit=10)
        self.assertEqual(journal[0].code, "CASH")
        self.assertIn("manual_cash_adjustment", journal[0].reason)
        integrity = self.db.check_portfolio_account_integrity()
        self.assertTrue(integrity["is_valid"], integrity)

    def test_cash_adjustment_source_code_does_not_reconcile_as_stock_trade(self):
        init_portfolio(
            self.db,
            cash=100.0,
            holdings=[HoldingInput(code="LAU.AX", quantity=10, avg_cost=1)],
        )

        record_cash_adjustment(
            self.db,
            amount=62.12,
            reason="LAU Dividend 2026-04-17",
            code="LAU.AX",
        )

        snapshot = self.db.get_latest_account_snapshot()
        self.assertAlmostEqual(snapshot.cash, 162.12, places=2)
        pos = self.db.get_portfolio_position("LAU.AX")
        self.assertIsNotNone(pos)
        self.assertAlmostEqual(pos.quantity, 10.0, places=6)

        journal = self.db.get_trade_journal(limit=10)
        self.assertEqual(journal[0].code, "CASH")
        self.assertIn("source=LAU.AX", journal[0].reason)
        integrity = self.db.check_portfolio_account_integrity()
        self.assertTrue(integrity["is_valid"], integrity)

    def test_cash_adjustment_rejects_overdraw_without_mutation(self):
        init_portfolio(self.db, cash=10.0, holdings=[])
        snapshot_before = self.db.get_latest_account_snapshot()
        journal_before = len(self.db.get_trade_journal(limit=10))

        with self.assertRaises(ValueError) as exc:
            record_cash_adjustment(self.db, amount=-11.0, reason="fee")
        self.assertIn("negative", str(exc.exception).lower())

        snapshot_after = self.db.get_latest_account_snapshot()
        self.assertAlmostEqual(snapshot_after.cash, snapshot_before.cash, places=2)
        self.assertEqual(len(self.db.get_trade_journal(limit=10)), journal_before)

    def test_cash_adjustment_rejects_amount_that_rounds_to_zero(self):
        init_portfolio(self.db, cash=10.0, holdings=[])

        with self.assertRaises(ValueError) as exc:
            record_cash_adjustment(self.db, amount=0.004, reason="rounding")
        self.assertIn("non-zero", str(exc.exception))

        snapshot = self.db.get_latest_account_snapshot()
        self.assertAlmostEqual(snapshot.cash, 10.0, places=2)
        self.assertEqual(len(self.db.get_trade_journal(limit=10)), 0)

    def test_buy_exceeding_cash_fails_without_mutation(self):
        init_portfolio(self.db, cash=100.0, holdings=[])
        snapshot_before = self.db.get_latest_account_snapshot()
        self.assertIsNotNone(snapshot_before)
        journal_before = len(self.db.get_trade_journal(limit=10))

        with self.assertRaises(ValueError) as exc:
            record_trade(self.db, code="AAA", side="BUY", quantity=10, price=11, fee=1)
        self.assertIn("insufficient cash", str(exc.exception).lower())

        self.assertIsNone(self.db.get_portfolio_position("AAA"))
        self.assertEqual(len(self.db.get_trade_journal(limit=10)), journal_before)

        snapshot_after = self.db.get_latest_account_snapshot()
        self.assertAlmostEqual(snapshot_after.cash, snapshot_before.cash, places=2)
        self.assertAlmostEqual(snapshot_after.equity_value, snapshot_before.equity_value, places=2)
        self.assertAlmostEqual(snapshot_after.total_value, snapshot_before.total_value, places=2)

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

    def test_init_rejects_duplicate_asx_suffix_aliases(self):
        args = Namespace(
            code_1="NHF.ASX", quantity_1="10", avg_cost_1="10",
            code_2="nhf.ax", quantity_2="5", avg_cost_2="9",
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

    def test_init_portfolio_uses_explicit_write_lock_and_begin_immediate(self):
        call_order = []
        real_lock = self.db.get_portfolio_write_lock()
        real_begin = self.db.begin_portfolio_write_transaction

        @contextmanager
        def tracked_lock():
            call_order.append("lock_acquire_enter")
            with real_lock:
                call_order.append("lock_acquired")
                yield
            call_order.append("lock_release_exit")

        def tracked_begin(session):
            call_order.append("begin_immediate")
            return real_begin(session)

        with patch.object(self.db, "get_portfolio_write_lock", side_effect=tracked_lock):
            with patch.object(self.db, "begin_portfolio_write_transaction", side_effect=tracked_begin):
                init_portfolio(
                    self.db,
                    cash=1000,
                    holdings=[HoldingInput(code="AAA", quantity=10, avg_cost=10)],
                )

        self.assertIn("lock_acquired", call_order)
        self.assertIn("begin_immediate", call_order)
        self.assertLess(call_order.index("lock_acquired"), call_order.index("begin_immediate"))
        self.assertLess(call_order.index("begin_immediate"), call_order.index("lock_release_exit"))

    def test_record_trade_uses_explicit_write_lock_and_begin_immediate(self):
        init_portfolio(self.db, cash=1000, holdings=[])
        call_order = []
        real_lock = self.db.get_portfolio_write_lock()
        real_begin = self.db.begin_portfolio_write_transaction

        @contextmanager
        def tracked_lock():
            call_order.append("lock_acquire_enter")
            with real_lock:
                call_order.append("lock_acquired")
                yield
            call_order.append("lock_release_exit")

        def tracked_begin(session):
            call_order.append("begin_immediate")
            return real_begin(session)

        with patch.object(self.db, "get_portfolio_write_lock", side_effect=tracked_lock):
            with patch.object(self.db, "begin_portfolio_write_transaction", side_effect=tracked_begin):
                record_trade(self.db, code="AAA", side="BUY", quantity=10, price=10, fee=0)

        self.assertIn("lock_acquired", call_order)
        self.assertIn("begin_immediate", call_order)
        self.assertLess(call_order.index("lock_acquired"), call_order.index("begin_immediate"))
        self.assertLess(call_order.index("begin_immediate"), call_order.index("lock_release_exit"))

        snapshot = self.db.get_latest_account_snapshot()
        self.assertAlmostEqual(snapshot.cash, 900.0, places=2)
        self.assertAlmostEqual(snapshot.equity_value, 100.0, places=2)
        self.assertAlmostEqual(snapshot.total_value, 1000.0, places=2)
        pos = self.db.get_portfolio_position("AAA")
        self.assertIsNotNone(pos)
        self.assertAlmostEqual(pos.quantity, 10.0, places=6)
        self.assertAlmostEqual(pos.market_value, 100.0, places=2)
        journal = self.db.get_trade_journal(limit=10)
        self.assertEqual(len(journal), 1)
        self.assertEqual(journal[0].code, "AAA")


if __name__ == "__main__":
    unittest.main()
