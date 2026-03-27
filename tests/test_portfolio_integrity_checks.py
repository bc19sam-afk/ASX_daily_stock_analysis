# -*- coding: utf-8 -*-

import os
import tempfile
import unittest
from datetime import date

from sqlalchemy import select

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

    def test_latest_journal_sanity_warns_on_cash_contradiction(self):
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
            self.assertTrue(result["is_valid"])
            self.assertTrue(any("cash_after" in msg for msg in result["warnings"]))

            session.rollback()


if __name__ == "__main__":
    unittest.main()
