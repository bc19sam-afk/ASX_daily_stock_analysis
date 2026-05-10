# -*- coding: utf-8 -*-
"""Display-only similar signal history statistics."""

import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional

from api.v1.endpoints import history as history_endpoint
from src.services.signal_history_stats_service import SignalHistoryStatsService
from src.storage import AnalysisHistory, DatabaseManager, StockDaily


FORBIDDEN_DISPLAY_TERMS = (
    "manual_actionable",
    "execution_ready",
    "risk_plan",
    "manual_checklist",
    "order_quantity",
    "target_quantity",
    "final_decision",
    "position_action",
    "entry_reference",
    "entry_price",
    "entry_source",
    "execution",
    "sizing",
)


class SignalHistoryStatsServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self._db_path = os.path.join(self._temp_dir.name, "signal_history_stats.db")
        DatabaseManager.reset_instance()
        self.db = DatabaseManager(db_url=f"sqlite:///{self._db_path}")

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        self._temp_dir.cleanup()

    def _add_signal(
        self,
        *,
        query_id: str,
        code: str = "BHP.AX",
        created_at: datetime = datetime(2024, 1, 20, 12, 0, 0),
        final_decision: str = "BUY",
        position_action: str = "OPEN",
        validation_status: str = "PASS",
        basis_date: Optional[str] = "2024-01-01",
        raw_overrides: Optional[Dict[str, Any]] = None,
        context_snapshot: Optional[Dict[str, Any]] = None,
    ) -> None:
        raw = {
            "analysis_status": "OK",
            "validation_status": validation_status,
            "final_decision": final_decision,
            "position_action": position_action,
            "market_snapshot": {"date": basis_date} if basis_date else {},
        }
        if raw_overrides:
            raw.update(raw_overrides)
        if context_snapshot is None and basis_date:
            context_snapshot = {"enhanced_context": {"date": basis_date}}

        with self.db.get_session() as session:
            session.add(
                AnalysisHistory(
                    query_id=query_id,
                    code=code,
                    name=code,
                    report_type="detailed",
                    sentiment_score=60,
                    operation_advice="历史参考",
                    trend_prediction="震荡",
                    analysis_summary="sample",
                    final_decision=final_decision,
                    position_action=position_action,
                    target_weight=0.05,
                    current_weight=0.0,
                    delta_amount=0.0,
                    raw_result=json.dumps(raw),
                    context_snapshot=json.dumps(context_snapshot) if context_snapshot is not None else None,
                    created_at=created_at,
                )
            )
            session.commit()

    def _add_daily_rows(
        self,
        *,
        code: str = "BHP.AX",
        start: date = date(2024, 1, 1),
        closes: list[float | None],
        lows: Optional[list[float | None]] = None,
    ) -> None:
        lows = lows or closes
        with self.db.get_session() as session:
            for offset, close in enumerate(closes):
                low = lows[offset] if offset < len(lows) else close
                session.add(
                    StockDaily(
                        code=code,
                        date=start + timedelta(days=offset),
                        open=close,
                        high=close,
                        low=low,
                        close=close,
                    )
                )
            session.commit()

    def test_uses_technical_basis_date_not_created_at_date(self) -> None:
        self._add_signal(query_id="current")
        self._add_signal(query_id="prior")
        self._add_daily_rows(closes=[10.0, 11.0, 12.0, 13.0, 14.0, 15.0], lows=[10.0, 9.5, 9.8, 10.0, 10.2, 10.4])

        current = self.db.get_analysis_history(query_id="current", limit=1)[0]
        stats = SignalHistoryStatsService(self.db).build_for_record(current)

        self.assertEqual(stats["status"], "ok")
        self.assertEqual(stats["analysis_basis_date"], "2024-01-01")
        self.assertEqual(stats["sample_size"], 1)
        self.assertEqual(stats["windows"][0]["horizon_days"], 5)
        self.assertEqual(stats["windows"][0]["sample_size"], 1)
        self.assertAlmostEqual(stats["windows"][0]["average_return"], 50.0)
        self.assertAlmostEqual(stats["windows"][0]["max_drawdown"], -5.0)

    def test_missing_trusted_basis_date_fails_closed(self) -> None:
        self._add_signal(query_id="current", basis_date=None, context_snapshot=None)

        current = self.db.get_analysis_history(query_id="current", limit=1)[0]
        stats = SignalHistoryStatsService(self.db).build_for_record(current)

        self.assertEqual(stats["status"], "insufficient_data")
        self.assertEqual(stats["reason"], "missing_trusted_analysis_basis_date")
        self.assertEqual(stats["sample_size"], 0)
        self.assertTrue(stats["display_only"])

    def test_forward_returns_are_display_only_and_do_not_add_action_fields(self) -> None:
        self._add_signal(query_id="current")
        self._add_signal(query_id="prior")
        self._add_daily_rows(closes=[10.0, 11.0, 12.0, 13.0, 14.0, 15.0])

        report = history_endpoint.get_history_detail("current", db_manager=self.db)
        payload = report.summary.model_dump()
        stats = payload["similar_signal_performance"]
        serialized_stats = json.dumps(stats, ensure_ascii=False)

        self.assertEqual(payload["final_decision"], "BUY")
        self.assertEqual(payload["position_action"], "OPEN")
        self.assertTrue(stats["display_only"])
        self.assertIn("不改变当前建议", stats["note"])
        for forbidden in FORBIDDEN_DISPLAY_TERMS[:6]:
            self.assertNotIn(forbidden, payload)
        for forbidden in FORBIDDEN_DISPLAY_TERMS:
            self.assertNotIn(forbidden, serialized_stats)

    def test_block_hold_grouping_stays_display_only(self) -> None:
        self._add_signal(
            query_id="current",
            final_decision="HOLD",
            position_action="HOLD",
            validation_status="BLOCK",
        )
        self._add_signal(
            query_id="prior",
            final_decision="HOLD",
            position_action="HOLD",
            validation_status="BLOCK",
        )
        self._add_daily_rows(closes=[10.0, 10.0, 10.0, 10.0, 10.0, 10.0])

        current = self.db.get_analysis_history(query_id="current", limit=1)[0]
        stats = SignalHistoryStatsService(self.db).build_for_record(current)

        self.assertTrue(stats["display_only"])
        self.assertEqual(stats["similarity_label"], "同类历史信号")
        self.assertEqual(stats["sample_size"], 1)
        serialized_stats = json.dumps(stats)
        for forbidden in FORBIDDEN_DISPLAY_TERMS:
            self.assertNotIn(forbidden, serialized_stats)

    def test_low_sample_warning_is_visible(self) -> None:
        self._add_signal(query_id="current")
        self._add_signal(query_id="prior")
        self._add_daily_rows(closes=[10.0, 11.0, 12.0, 13.0, 14.0, 15.0])

        current = self.db.get_analysis_history(query_id="current", limit=1)[0]
        stats = SignalHistoryStatsService(self.db).build_for_record(current)

        self.assertTrue(stats["low_sample"])
        self.assertEqual(stats["warning"], "样本较少，参考价值有限")
        self.assertEqual(stats["windows"][0]["confidence_label"], "样本较少，参考价值有限")

    def test_history_detail_includes_similar_signal_performance(self) -> None:
        self._add_signal(query_id="current-report", code="CUR.AX")
        self._add_signal(query_id="prior-sample", code="OLD.AX")
        self._add_daily_rows(code="CUR.AX", closes=[10.0, 10.5, 10.6, 10.7, 10.8, 11.0])
        self._add_daily_rows(code="OLD.AX", closes=[10.0, 10.5, 10.6, 10.7, 10.8, 11.0])

        report = history_endpoint.get_history_detail("current-report", db_manager=self.db)

        stats = report.summary.similar_signal_performance
        self.assertIsNotNone(stats)
        self.assertEqual(stats["contract_version"], "similar_signal_history_v1")
        self.assertTrue(stats["display_only"])
        self.assertEqual(stats["windows"][0]["sample_size"], 1)


if __name__ == "__main__":
    unittest.main()
