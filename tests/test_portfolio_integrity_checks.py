# -*- coding: utf-8 -*-

import os
import tempfile
import unittest
from datetime import date

from sqlalchemy import select

from scripts.manual_portfolio_workflows import record_trade
from src.storage import DatabaseManager, PortfolioPosition


class PortfolioIntegrityChecksTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        DatabaseManager.reset_instance()
        self.db = DatabaseManager(db_url=f"sqlite:///{os.path.join(self.tmp.name, 'integrity_checks.db')}")

    def tearDown(self):
        DatabaseManager.reset_instance()
        self.tmp.cleanup()

    def test_pure_cash_account_is_valid(self):
        self.db.save_account_snapshot(
            snapshot_date=date.today(),
            cash=1000.0,
            equity_value=0.0,
            total_value=1000.0,
        )

        result = self.db.check_portfolio_account_integrity()
        self.assertTrue(result["is_valid"])
        self.assertEqual(result["errors"], [])

    def test_open_position_quantity_non_positive_is_invalid(self):
        with self.db.get_session() as session:
            self.db.save_account_snapshot_in_session(
                session=session,
                snapshot_date=date.today(),
                cash=900.0,
                equity_value=100.0,
                total_value=1000.0,
            )
            self.db.upsert_portfolio_position_in_session(
                session=session,
                code="AAA",
                name="AAA",
                quantity=10.0,
                avg_cost=10.0,
                current_price=10.0,
                weight=0.1,
                market_value=100.0,
            )
            session.flush()
            row = session.execute(
                select(PortfolioPosition)
                .where(PortfolioPosition.code == "AAA")
                .limit(1)
            ).scalar_one()
            row.quantity = 0.0
            row.status = "OPEN"

            result = self.db.check_portfolio_account_integrity(session=session)
            self.assertFalse(result["is_valid"])
            self.assertTrue(any("Invalid OPEN position AAA" in msg for msg in result["errors"]))

            session.rollback()

    def test_latest_journal_cash_contradiction_is_invalid(self):
        with self.db.get_session() as session:
            self.db.save_account_snapshot_in_session(
                session=session,
                snapshot_date=date.today(),
                cash=1000.0,
                equity_value=0.0,
                total_value=1000.0,
            )
            self.db.save_trade_journal_in_session(
                session=session,
                query_id="manual_trade_workflow",
                code="AAA",
                action_date=date.today(),
                action="OPEN",
                final_decision="BUY",
                market_regime="MANUAL",
                event_risk="NA",
                data_quality_flag="MANUAL",
                current_weight=0.0,
                target_weight=0.1,
                delta_amount=100.0,
                current_quantity=0.0,
                target_quantity=10.0,
                current_price=10.0,
                available_cash_before=1000.0,
                available_cash_after=800.0,
                reason="manual_buy fee=0",
            )

            result = self.db.check_portfolio_account_integrity(session=session, journal_code="AAA")
            self.assertFalse(result["is_valid"])
            self.assertTrue(any("cash_after" in msg for msg in result["errors"]))

            session.rollback()

    def test_stale_weight_does_not_mislead_overview_and_is_warning_only(self):
        self.db.save_account_snapshot(
            snapshot_date=date.today(),
            cash=200.0,
            equity_value=800.0,
            total_value=1000.0,
        )
        self.db.upsert_portfolio_position(
            code="AAA",
            name="AAA",
            quantity=10,
            avg_cost=60,
            current_price=60,
            weight=0.95,  # stale / wrong stored value
            market_value=600.0,
        )
        self.db.upsert_portfolio_position(
            code="BBB",
            name="BBB",
            quantity=10,
            avg_cost=20,
            current_price=20,
            weight=0.05,  # stale / wrong stored value
            market_value=200.0,
        )

        integrity = self.db.check_portfolio_account_integrity()
        self.assertTrue(integrity["is_valid"])
        self.assertTrue(any("Position weight mismatch" in msg for msg in integrity["warnings"]))

        overview = self.db.get_portfolio_overview()
        weights = {item["code"]: item["weight"] for item in overview["holdings"]}
        self.assertAlmostEqual(overview["equity_value"], 800.0, places=2)
        self.assertAlmostEqual(overview["total_value"], 1000.0, places=2)
        self.assertAlmostEqual(weights["AAA"], 0.6, places=6)
        self.assertAlmostEqual(weights["BBB"], 0.2, places=6)

    def test_snapshot_mismatch_is_detected(self):
        self.db.save_account_snapshot(
            snapshot_date=date.today(),
            cash=100.0,
            equity_value=500.0,
            total_value=700.0,  # should be 600
        )
        self.db.upsert_portfolio_position(
            code="AAA",
            name="AAA",
            quantity=50,
            avg_cost=10,
            current_price=10,
            weight=0.714285,
            market_value=500.0,
        )

        result = self.db.check_portfolio_account_integrity()
        self.assertFalse(result["is_valid"])
        self.assertTrue(any("Snapshot total mismatch" in msg for msg in result["errors"]))

    def test_contradictory_journal_position_state_is_detected(self):
        with self.db.get_session() as session:
            self.db.save_account_snapshot_in_session(
                session=session,
                snapshot_date=date.today(),
                cash=950.0,
                equity_value=50.0,
                total_value=1000.0,
            )
            self.db.upsert_portfolio_position_in_session(
                session=session,
                code="AAA",
                name="AAA",
                quantity=5.0,
                avg_cost=10.0,
                current_price=10.0,
                weight=0.05,
                market_value=50.0,
            )
            # make latest journal contradict current position
            self.db.save_trade_journal_in_session(
                session=session,
                query_id="manual_trade_workflow",
                code="AAA",
                action_date=date.today(),
                action="CLOSE",
                final_decision="SELL",
                market_regime="MANUAL",
                event_risk="NA",
                data_quality_flag="MANUAL",
                current_weight=0.05,
                target_weight=0.0,
                delta_amount=-50.0,
                current_quantity=5.0,
                target_quantity=0.0,
                current_price=10.0,
                available_cash_before=900.0,
                available_cash_after=950.0,
                reason="manual_close fee=0",
            )

            result = self.db.check_portfolio_account_integrity(session=session, journal_code="AAA")
            self.assertFalse(result["is_valid"])
            self.assertTrue(any("Journal/position quantity mismatch" in msg for msg in result["errors"]))
            self.assertTrue(any("Journal/position status mismatch" in msg for msg in result["errors"]))

            session.rollback()

    def test_portfolio_overview_values_are_recomputed_consistently(self):
        self.db.save_account_snapshot(
            snapshot_date=date.today(),
            cash=300.0,
            equity_value=9999.0,  # intentionally stale
            total_value=10299.0,  # intentionally stale
        )
        self.db.upsert_portfolio_position(
            code="AAA",
            name="AAA",
            quantity=10,
            avg_cost=10,
            current_price=10,
            weight=0.1,
            market_value=100.0,
        )
        self.db.upsert_portfolio_position(
            code="BBB",
            name="BBB",
            quantity=10,
            avg_cost=20,
            current_price=20,
            weight=0.2,
            market_value=200.0,
        )

        overview = self.db.get_portfolio_overview()
        self.assertAlmostEqual(overview["cash"], 300.0, places=2)
        self.assertAlmostEqual(overview["equity_value"], 300.0, places=2)
        self.assertAlmostEqual(overview["total_value"], 600.0, places=2)
        self.assertAlmostEqual(sum(item["weight"] for item in overview["holdings"]), 0.5, places=6)

    def test_trade_on_one_symbol_does_not_fail_integrity_due_to_other_stale_weight(self):
        self.db.save_account_snapshot(
            snapshot_date=date.today(),
            cash=1000.0,
            equity_value=1000.0,
            total_value=2000.0,
        )
        self.db.upsert_portfolio_position(
            code="AAA",
            name="AAA",
            quantity=50.0,
            avg_cost=10.0,
            current_price=10.0,
            weight=0.25,
            market_value=500.0,
        )
        self.db.upsert_portfolio_position(
            code="BBB",
            name="BBB",
            quantity=50.0,
            avg_cost=10.0,
            current_price=10.0,
            weight=0.25,
            market_value=500.0,
        )

        record_trade(self.db, code="AAA", side="BUY", quantity=10, price=10, fee=100)

        # record_trade only rewrites traded symbol weight today; untouched BBB may stay stale.
        # Integrity should remain valid and only emit weight warnings.
        result = self.db.check_portfolio_account_integrity()
        self.assertTrue(result["is_valid"])
        self.assertEqual(result["errors"], [])
        self.assertTrue(any("weight mismatch" in msg.lower() for msg in result["warnings"]))


if __name__ == "__main__":
    unittest.main()
