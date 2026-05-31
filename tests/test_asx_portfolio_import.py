# -*- coding: utf-8 -*-

import tempfile
import unittest
from pathlib import Path

from scripts.manual_portfolio_workflows import HoldingInput, init_portfolio
from src.services.asx_portfolio_import_service import AsxPortfolioImportService
from src.storage import DatabaseManager


class AsxPortfolioImportServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        DatabaseManager.reset_instance()
        self.db = DatabaseManager(db_url=f"sqlite:///{Path(self.tmp.name) / 'portfolio_import.db'}")
        self.service = AsxPortfolioImportService(self.db)

    def tearDown(self):
        DatabaseManager.reset_instance()
        self.tmp.cleanup()

    def _write_csv(self, name: str, content: str) -> Path:
        path = Path(self.tmp.name) / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_preview_reports_row_errors_and_keeps_ledger_unchanged(self):
        init_portfolio(self.db, cash=1000.0, holdings=[])
        csv_path = self._write_csv(
            "preview.csv",
            """trade_date,settlement_date,code,side,quantity,price,brokerage,currency,broker,account_label,HIN,dividend,franking_credit
2026-05-20,2026-05-22,BHP,BUY,4,25,3,AUD,SelfWealth,Main,HIN-001,,
2026-05-21,2026-05-23,CBA,HOLD,2,100,3,AUD,SelfWealth,Main,HIN-001,,
""",
        )

        result = self.service.preview_csv(csv_path)

        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["row_count"], 2)
        self.assertEqual(result["valid_row_count"], 1)
        self.assertEqual(result["invalid_row_count"], 1)
        self.assertAlmostEqual(result["totals"]["buy_notional"], 100.0, places=2)
        self.assertAlmostEqual(result["totals"]["fees"], 3.0, places=2)
        self.assertAlmostEqual(result["totals"]["net_cash_impact"], -103.0, places=2)
        self.assertTrue(any("line 3" in err.lower() and "side" in err.lower() for err in result["errors"]))
        self.assertEqual(self.db.get_trade_journal(limit=10), [])

    def test_preview_keeps_bad_dates_in_error_rows_instead_of_raising(self):
        init_portfolio(self.db, cash=1000.0, holdings=[])
        csv_path = self._write_csv(
            "bad_dates.csv",
            """trade_date,settlement_date,code,side,quantity,price,brokerage,currency,broker,account_label,HIN
bad-date,2026-05-22,BHP,BUY,4,25,3,AUD,SelfWealth,Main,HIN-001
""",
        )

        result = self.service.preview_csv(csv_path)

        self.assertEqual(result["status"], "invalid")
        self.assertTrue(any("trade_date" in error.lower() for error in result["errors"]))
        self.assertEqual(self.db.get_trade_journal(limit=10), [])

    def test_apply_writes_asx_standardized_ledger_and_preserves_reserved_metadata(self):
        init_portfolio(self.db, cash=1000.0, holdings=[])
        csv_path = self._write_csv(
            "apply.csv",
            """trade_date,settlement_date,code,side,quantity,price,brokerage,currency,broker,account_label,HIN,dividend,franking_credit
2026-05-20,2026-05-22,BHP,BUY,4,25,3,AUD,SelfWealth,Main,HIN-001,12.34,5.67
""",
        )

        result = self.service.apply_csv(csv_path)

        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["applied_count"], 1)
        self.assertTrue(result["integrity"]["is_valid"])
        self.assertTrue(any("dividend" in warning.lower() or "franking" in warning.lower() for warning in result["warnings"]))

        position = self.db.get_portfolio_position("BHP.AX")
        self.assertIsNotNone(position)
        self.assertAlmostEqual(position.quantity, 4.0, places=6)
        self.assertAlmostEqual(position.avg_cost, 25.75, places=2)

        snapshot = self.db.get_latest_account_snapshot()
        self.assertAlmostEqual(snapshot.cash, 897.0, places=2)
        self.assertAlmostEqual(snapshot.equity_value, 100.0, places=2)
        self.assertAlmostEqual(snapshot.total_value, 997.0, places=2)

        journal = self.db.get_trade_journal(limit=10)
        self.assertEqual(len(journal), 1)
        self.assertEqual(journal[0].code, "BHP.AX")
        self.assertEqual(journal[0].action, "OPEN")
        self.assertIn("broker=SelfWealth", journal[0].reason)
        self.assertIn("account_label=Main", journal[0].reason)
        self.assertIn("settlement_date=2026-05-22", journal[0].reason)
        self.assertIn("custody_metadata_present=true", journal[0].reason)
        self.assertNotIn("HIN-001", journal[0].reason)

    def test_preview_reports_parser_counters_and_dedup_without_mutation(self):
        init_portfolio(self.db, cash=1000.0, holdings=[])
        csv_path = self._write_csv(
            "preview_dedup.csv",
            """trade_date,settlement_date,code,side,quantity,price,brokerage,currency,broker,account_label,HIN
2026-05-20,2026-05-22,BHP,BUY,4,25,3,AUD,SelfWealth,Main,HIN-001
2026-05-20,2026-05-22,BHP,BUY,4,25,3,AUD,SelfWealth,Main,HIN-001
""",
        )

        result = self.service.preview_csv(csv_path)

        self.assertEqual(result["status"], "preview")
        self.assertEqual(result["parser"]["id"], "generic_asx")
        self.assertIn("fee", result["parser"]["required_fields"])
        self.assertIn("brokerage", result["parser"]["column_aliases"]["fee"])
        self.assertEqual(result["counters"]["parsed_count"], 2)
        self.assertEqual(result["counters"]["valid_count"], 2)
        self.assertEqual(result["counters"]["duplicate_count"], 1)
        self.assertEqual(result["counters"]["would_apply_count"], 1)
        self.assertEqual(result["counters"]["applied_count"], 0)
        self.assertEqual(result["counters"]["skipped_count"], 1)
        self.assertEqual(result["dedup"]["file_duplicate_count"], 1)
        self.assertEqual(result["dedup"]["existing_duplicate_count"], 0)
        self.assertEqual(len(result["rows"]), 2)
        duplicate_rows = [row for row in result["rows"] if row["dedup"]["duplicate"]]
        self.assertEqual(len(duplicate_rows), 1)
        self.assertEqual(duplicate_rows[0]["dedup"]["reason"], "duplicate_in_file")
        self.assertEqual(self.db.get_trade_journal(limit=10), [])
        self.assertIsNone(self.db.get_portfolio_position("BHP.AX"))
        self.assertAlmostEqual(self.db.get_latest_account_snapshot().cash, 1000.0, places=2)

    def test_apply_skips_same_file_and_previously_imported_duplicate_trades(self):
        init_portfolio(self.db, cash=1000.0, holdings=[])
        csv_path = self._write_csv(
            "apply_dedup.csv",
            """trade_date,settlement_date,code,side,quantity,price,brokerage,currency,broker,account_label,HIN
2026-05-20,2026-05-22,BHP,BUY,4,25,3,AUD,SelfWealth,Main,HIN-001
2026-05-20,2026-05-22,BHP,BUY,4,25,3,AUD,SelfWealth,Main,HIN-001
""",
        )

        first = self.service.apply_csv(csv_path)

        self.assertEqual(first["status"], "applied")
        self.assertEqual(first["applied_count"], 1)
        self.assertEqual(first["counters"]["applied_count"], 1)
        self.assertEqual(first["counters"]["duplicate_count"], 1)
        self.assertEqual(first["dedup"]["file_duplicate_count"], 1)
        position = self.db.get_portfolio_position("BHP.AX")
        self.assertAlmostEqual(position.quantity, 4.0, places=6)
        snapshot = self.db.get_latest_account_snapshot()
        self.assertAlmostEqual(snapshot.cash, 897.0, places=2)
        self.assertEqual(len(self.db.get_trade_journal(limit=10)), 1)

        second = self.service.apply_csv(csv_path)

        self.assertEqual(second["status"], "applied")
        self.assertEqual(second["applied_count"], 0)
        self.assertEqual(second["counters"]["applied_count"], 0)
        self.assertEqual(second["counters"]["duplicate_count"], 2)
        self.assertEqual(second["dedup"]["existing_duplicate_count"], 1)
        self.assertEqual(second["dedup"]["file_duplicate_count"], 1)
        self.assertEqual(len(self.db.get_trade_journal(limit=10)), 1)
        position_after = self.db.get_portfolio_position("BHP.AX")
        self.assertAlmostEqual(position_after.quantity, 4.0, places=6)
        snapshot_after = self.db.get_latest_account_snapshot()
        self.assertAlmostEqual(snapshot_after.cash, 897.0, places=2)

    def test_generic_parser_accepts_registered_column_aliases(self):
        init_portfolio(self.db, cash=1000.0, holdings=[])
        csv_path = self._write_csv(
            "alias_headers.csv",
            """Trade Date,Settlement Date,Symbol,Buy/Sell,Units,Unit Price,Brokerage,CCY,Broker,Account Label
2026-05-20,2026-05-22,BHP,B,4,25,3,AUD,SelfWealth,Main
""",
        )

        result = self.service.preview_csv(csv_path, parser_id="generic")

        self.assertEqual(result["status"], "preview")
        self.assertEqual(result["parser"]["id"], "generic_asx")
        self.assertEqual(result["counters"]["would_apply_count"], 1)
        self.assertEqual(result["rows"][0]["code"], "BHP.AX")
        self.assertEqual(result["rows"][0]["side"], "BUY")
        self.assertEqual(self.db.get_trade_journal(limit=10), [])

    def test_apply_rejects_sell_rows_that_exceed_holding_without_mutation(self):
        init_portfolio(
            self.db,
            cash=1000.0,
            holdings=[HoldingInput(code="BHP.AX", quantity=1.0, avg_cost=25.0)],
        )
        csv_path = self._write_csv(
            "oversell.csv",
            """trade_date,settlement_date,code,side,quantity,price,brokerage,currency,broker,account_label,HIN
2026-05-20,2026-05-22,BHP,SELL,2,25,3,AUD,SelfWealth,Main,HIN-001
""",
        )
        position_before = self.db.get_portfolio_position("BHP.AX")
        journal_before = len(self.db.get_trade_journal(limit=10))

        result = self.service.apply_csv(csv_path)

        self.assertEqual(result["status"], "invalid")
        self.assertTrue(any("cannot sell" in error.lower() or "exceed" in error.lower() for error in result["errors"]))
        self.assertEqual(len(self.db.get_trade_journal(limit=10)), journal_before)
        position_after = self.db.get_portfolio_position("BHP.AX")
        self.assertAlmostEqual(position_after.quantity, position_before.quantity, places=6)


if __name__ == "__main__":
    unittest.main()
