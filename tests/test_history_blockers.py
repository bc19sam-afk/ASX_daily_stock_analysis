# -*- coding: utf-8 -*-
"""Blocker fixes for analysis_history migration and history detail fields."""

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from src.analyzer import AnalysisResult
from src.services.history_service import HistoryService
from src.storage import DatabaseManager


class HistoryBlockersTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        DatabaseManager.reset_instance()

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        self._temp_dir.cleanup()

    def _db_url(self, file_name: str) -> str:
        return f"sqlite:///{os.path.join(self._temp_dir.name, file_name)}"

    def test_startup_auto_migrates_analysis_history_decision_columns(self) -> None:
        db_path = os.path.join(self._temp_dir.name, "legacy.db")
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                """
                CREATE TABLE analysis_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query_id VARCHAR(64),
                    code VARCHAR(10) NOT NULL,
                    name VARCHAR(50),
                    report_type VARCHAR(16),
                    sentiment_score INTEGER,
                    operation_advice VARCHAR(20),
                    trend_prediction VARCHAR(50),
                    analysis_summary TEXT,
                    raw_result TEXT,
                    news_content TEXT,
                    context_snapshot TEXT,
                    ideal_buy FLOAT,
                    secondary_buy FLOAT,
                    stop_loss FLOAT,
                    take_profit FLOAT,
                    created_at DATETIME
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

        db = DatabaseManager(self._db_url("legacy.db"))
        records = db.get_analysis_history(limit=1)
        self.assertEqual(records, [])

        conn = sqlite3.connect(db_path)
        try:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(analysis_history)").fetchall()}
        finally:
            conn.close()

        for col in (
            "alpha_decision",
            "final_decision",
            "watchlist_state",
            "market_regime",
            "news_sentiment",
            "event_risk",
            "sector_tone",
            "data_quality_flag",
        ):
            self.assertIn(col, cols)

    def test_get_history_detail_returns_decision_metadata(self) -> None:
        db = DatabaseManager(self._db_url("history.db"))
        service = HistoryService(db)

        result = AnalysisResult(
            code="AAPL",
            name="苹果",
            sentiment_score=70,
            trend_prediction="震荡",
            operation_advice="持有",
            analysis_summary="测试摘要",
            alpha_decision="BUY",
            final_decision="HOLD",
            watchlist_state="ACTIVE",
            market_regime="RISK_OFF",
            news_sentiment="NEG",
            event_risk="HIGH",
            sector_tone="NEU",
            data_quality_flag="OK",
        )
        db.save_analysis_history(
            result=result,
            query_id="query-history-detail",
            report_type="detailed",
            news_content="",
        )

        detail = service.get_history_detail("query-history-detail")
        self.assertIsNotNone(detail)
        self.assertEqual(detail["alpha_decision"], "BUY")
        self.assertEqual(detail["final_decision"], "HOLD")
        self.assertEqual(detail["watchlist_state"], "ACTIVE")
        self.assertEqual(detail["market_regime"], "RISK_OFF")
        self.assertEqual(detail["news_sentiment"], "NEG")
        self.assertEqual(detail["event_risk"], "HIGH")
        self.assertEqual(detail["sector_tone"], "NEU")
        self.assertEqual(detail["data_quality_flag"], "OK")

    def test_migration_script_skips_when_db_is_missing(self) -> None:
        missing_path = os.path.join(self._temp_dir.name, "missing.db")
        script_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "scripts",
            "migrate_analysis_history_decision_columns.py",
        )
        completed = subprocess.run(
            [sys.executable, script_path, "--db", missing_path],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0)
        self.assertIn("[SKIP] DB not found", completed.stdout)


if __name__ == "__main__":
    unittest.main()
