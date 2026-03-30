# -*- coding: utf-8 -*-

import os
import tempfile
import threading
import time
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from src.analyzer import AnalysisResult
from src.core.pipeline import StockAnalysisPipeline
from src.core.position_manager import PositionManager
from src.enums import ReportType
from src.storage import DatabaseManager


class PositionManagementAccountingTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        DatabaseManager.reset_instance()
        self.db = DatabaseManager(db_url=f"sqlite:///{os.path.join(self.tmp.name, 'pm_test.db')}")
        self.pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        self.pipeline.db = self.db
        self.pipeline.position_manager = PositionManager()

    def tearDown(self):
        DatabaseManager.reset_instance()
        self.tmp.cleanup()

    def _result(self, code: str, final_decision: str, market_regime: str = "NEUTRAL") -> AnalysisResult:
        r = AnalysisResult(
            code=code,
            name=f"股票{code}",
            sentiment_score=60,
            trend_prediction="震荡",
            operation_advice="持有",
        )
        r.final_decision = final_decision
        r.market_regime = market_regime
        r.event_risk = "LOW"
        r.data_quality_flag = "OK"
        return r

    def _run_parallel_position_updates(self, *, pipeline: StockAnalysisPipeline, codes: list[str], query_prefix: str) -> None:
        start_gate = threading.Event()
        errors = []
        threads = []

        def worker(code: str):
            try:
                start_gate.wait(timeout=2)
                result = self._result(code, final_decision="BUY")
                pipeline._apply_position_management(
                    result=result,
                    query_id=f"{query_prefix}_{code}",
                    current_price=100,
                )
            except Exception as exc:  # pragma: no cover - helper for test diagnostics
                errors.append(exc)

        for code in codes:
            t = threading.Thread(target=worker, args=(code,), daemon=True)
            threads.append(t)
            t.start()

        start_gate.set()
        for t in threads:
            t.join(timeout=5)

        self.assertFalse(errors, f"parallel workers failed: {errors}")

    def _rebuild_pipeline_with_fresh_db(self) -> None:
        DatabaseManager.reset_instance()
        self.db = DatabaseManager(db_url=f"sqlite:///{os.path.join(self.tmp.name, f'pm_test_{time.time_ns()}.db')}")
        self.pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        self.pipeline.db = self.db
        self.pipeline.position_manager = PositionManager()

    def test_reduce_does_not_overstate_equity(self):
        self.db.save_account_snapshot(snapshot_date=date.today(), cash=1000, equity_value=9000, total_value=10000)
        self.db.upsert_portfolio_position(
            code="AAA",
            name="AAA",
            quantity=100,
            avg_cost=95,
            current_price=90,
            weight=0.9,
            market_value=9000,
        )

        result = self._result("AAA", final_decision="HOLD", market_regime="RISK_OFF")
        self.pipeline._apply_position_management(result=result, query_id="q_reduce", current_price=90)

        snap = self.db.get_latest_account_snapshot()
        self.assertIsNotNone(snap)
        self.assertAlmostEqual(snap.equity_value, 1000.0, places=2)
        self.assertAlmostEqual(snap.cash, 9000.0, places=2)
        self.assertAlmostEqual(snap.total_value, 10000.0, places=2)

    def test_close_large_position_restores_cash(self):
        self.db.save_account_snapshot(snapshot_date=date.today(), cash=100, equity_value=9900, total_value=10000)
        self.db.upsert_portfolio_position(
            code="BBB",
            name="BBB",
            quantity=110,
            avg_cost=92,
            current_price=90,
            weight=0.99,
            market_value=9900,
        )

        result = self._result("BBB", final_decision="SELL")
        self.pipeline._apply_position_management(result=result, query_id="q_close", current_price=90)

        snap = self.db.get_latest_account_snapshot()
        self.assertAlmostEqual(snap.cash, 10000.0, places=2)
        self.assertAlmostEqual(snap.equity_value, 0.0, places=2)
        self.assertAlmostEqual(snap.total_value, 10000.0, places=2)

    def test_multi_symbol_sequential_updates_keep_snapshot_consistent(self):
        self.db.save_account_snapshot(snapshot_date=date.today(), cash=10000, equity_value=0, total_value=10000)

        result_a = self._result("AAA", final_decision="BUY")
        self.pipeline._apply_position_management(result=result_a, query_id="q_multi_a", current_price=100)

        result_b = self._result("BBB", final_decision="BUY")
        self.pipeline._apply_position_management(result=result_b, query_id="q_multi_b", current_price=50)

        snap = self.db.get_latest_account_snapshot()
        self.assertAlmostEqual(snap.cash, 8000.0, places=2)
        self.assertAlmostEqual(snap.equity_value, 2000.0, places=2)
        self.assertAlmostEqual(snap.total_value, 10000.0, places=2)

        holdings = self.db.get_portfolio_positions(only_open=True)
        self.assertEqual(len(holdings), 2)

    def test_concurrent_api_updates_are_serialized_and_consistent(self):
        self.db.save_account_snapshot(snapshot_date=date.today(), cash=10000, equity_value=0, total_value=10000)
        self.pipeline.query_source = "api"
        self._run_parallel_position_updates(
            pipeline=self.pipeline,
            codes=["A01", "B01"],
            query_prefix="q_race_api",
        )

        snapshot = self.db.get_latest_account_snapshot()
        self.assertIsNotNone(snapshot)
        self.assertAlmostEqual(snapshot.cash, 8000.0, places=2)
        self.assertAlmostEqual(snapshot.equity_value, 2000.0, places=2)
        self.assertAlmostEqual(snapshot.total_value, 10000.0, places=2)
        self.assertAlmostEqual(snapshot.cash + snapshot.equity_value, snapshot.total_value, places=2)

    def test_concurrent_writes_are_serialized_for_all_write_capable_sources(self):
        for query_source in ("system", "cli", "api", "bot", "web"):
            with self.subTest(query_source=query_source):
                self._rebuild_pipeline_with_fresh_db()
                self.db.save_account_snapshot(snapshot_date=date.today(), cash=10000, equity_value=0, total_value=10000)
                self.pipeline.query_source = query_source

                self._run_parallel_position_updates(
                    pipeline=self.pipeline,
                    codes=["A02", "B02"],
                    query_prefix=f"q_race_locked_{query_source}",
                )

                # 自动路径并发执行后仍应保持组合快照一致
                snapshot = self.db.get_latest_account_snapshot()
                self.assertIsNotNone(snapshot)
                self.assertAlmostEqual(snapshot.cash, 8000.0, places=2)
                self.assertAlmostEqual(snapshot.equity_value, 2000.0, places=2)
                self.assertAlmostEqual(snapshot.total_value, 10000.0, places=2)
                self.assertAlmostEqual(snapshot.cash + snapshot.equity_value, snapshot.total_value, places=2)

    def test_overlapping_same_symbol_updates_keep_single_position_and_lineage(self):
        self.db.save_account_snapshot(snapshot_date=date.today(), cash=10000, equity_value=0, total_value=10000)
        self.pipeline.query_source = "api"

        start_gate = threading.Event()
        threads = []

        def worker(suffix: str):
            result = self._result("ZZZ", final_decision="BUY")
            start_gate.wait(timeout=2)
            self.pipeline._apply_position_management(
                result=result,
                query_id=f"q_overlap_{suffix}",
                current_price=100,
            )

        for suffix in ("1", "2"):
            t = threading.Thread(target=worker, args=(suffix,), daemon=True)
            threads.append(t)
            t.start()

        start_gate.set()
        for t in threads:
            t.join(timeout=5)

        position = self.db.get_portfolio_position("ZZZ")
        self.assertIsNotNone(position)
        self.assertEqual(position.status, "OPEN")

        open_positions = self.db.get_portfolio_positions(only_open=True)
        self.assertEqual(len([p for p in open_positions if p.code == "ZZZ"]), 1)

        journal = self.db.get_trade_journal(code="ZZZ", limit=10)
        self.assertEqual(len(journal), 2)
        for entry in journal:
            self.assertIsNotNone(entry.query_id)

        snapshot = self.db.get_latest_account_snapshot()
        self.assertIsNotNone(snapshot)
        self.assertAlmostEqual(snapshot.cash + snapshot.equity_value, snapshot.total_value, places=2)

    def test_journal_and_history_delta_amount_match_actual_notional(self):
        self.db.save_account_snapshot(snapshot_date=date.today(), cash=1000, equity_value=9000, total_value=10000)
        self.db.upsert_portfolio_position(
            code="CCC",
            name="CCC",
            quantity=100,
            avg_cost=95,
            current_price=90,
            weight=0.9,
            market_value=9000,
        )

        result = self._result("CCC", final_decision="HOLD", market_regime="RISK_OFF")
        self.pipeline._apply_position_management(result=result, query_id="q_delta", current_price=90)

        journal = self.db.get_trade_journal(code="CCC", limit=1)[0]
        expected_delta = round((journal.target_quantity - journal.current_quantity) * journal.current_price, 2)
        self.assertAlmostEqual(journal.delta_amount, expected_delta, places=2)

        self.db.save_analysis_history(
            result=result,
            query_id="q_delta",
            report_type="simple",
            news_content=None,
            context_snapshot={},
            save_snapshot=False,
        )
        history = self.db.get_analysis_history(query_id="q_delta", limit=1)[0]
        self.assertAlmostEqual(history.delta_amount, expected_delta, places=2)

    def test_missing_price_non_executable_path_does_not_mutate_account_state(self):
        self.db.save_account_snapshot(snapshot_date=date.today(), cash=10000, equity_value=0, total_value=10000)

        result = self._result("DDD", final_decision="BUY")
        self.pipeline._apply_position_management(result=result, query_id="q_missing_price", current_price=None)

        # Portfolio position should remain unchanged (no new row created)
        self.assertIsNone(self.db.get_portfolio_position("DDD"))

        # No executed adjustment should be recorded in journal
        self.assertEqual(self.db.get_trade_journal(code="DDD", limit=10), [])

        # Account snapshot should remain unchanged
        snapshot = self.db.get_latest_account_snapshot()
        self.assertIsNotNone(snapshot)
        self.assertAlmostEqual(snapshot.cash, 10000.0, places=2)
        self.assertAlmostEqual(snapshot.equity_value, 0.0, places=2)
        self.assertAlmostEqual(snapshot.total_value, 10000.0, places=2)

        # Analysis result should clearly indicate non-executable hold
        self.assertEqual(result.position_action, "HOLD")
        self.assertAlmostEqual(result.current_weight, 0.0, places=4)
        self.assertAlmostEqual(result.target_weight, 0.0, places=4)
        self.assertAlmostEqual(result.delta_amount, 0.0, places=2)
        self.assertIn("execution_blocked=price_unavailable", result.action_reason)

    def test_missing_price_uses_existing_market_value_for_nonzero_exposure_and_path_parity(self):
        self.db.save_account_snapshot(snapshot_date=date.today(), cash=9000, equity_value=1000, total_value=10000)
        self.db.upsert_portfolio_position(
            code="NOPX",
            name="NOPX",
            quantity=10,
            avg_cost=100,
            current_price=None,
            weight=0.0,  # stale/invalid stored weight should not zero-out exposure
            market_value=1000,
        )

        ro_result = self._result("NOPX", final_decision="HOLD")
        self.pipeline._apply_position_management(
            result=ro_result,
            query_id="q_missing_price_ro",
            current_price=None,
            persist=False,
        )

        rw_result = self._result("NOPX", final_decision="HOLD")
        self.pipeline._apply_position_management(
            result=rw_result,
            query_id="q_missing_price_rw",
            current_price=None,
            persist=True,
        )

        self.assertEqual(ro_result.position_action, "HOLD")
        self.assertEqual(rw_result.position_action, "HOLD")
        self.assertAlmostEqual(ro_result.current_weight, 0.1, places=4)
        self.assertAlmostEqual(rw_result.current_weight, 0.1, places=4)
        self.assertAlmostEqual(ro_result.target_weight, rw_result.target_weight, places=4)
        self.assertAlmostEqual(ro_result.delta_amount, 0.0, places=2)
        self.assertAlmostEqual(rw_result.delta_amount, 0.0, places=2)

        # Non-executable branch should not write journal rows in persist mode either.
        self.assertEqual(self.db.get_trade_journal(code="NOPX", limit=10), [])

    def test_atomic_rollback_when_journal_fails_for_new_position_insert(self):
        self.db.save_account_snapshot(snapshot_date=date.today(), cash=10000, equity_value=0, total_value=10000)
        result = self._result("EEE", final_decision="BUY")

        with patch.object(
            self.db,
            "save_trade_journal_in_session",
            side_effect=RuntimeError("journal failed"),
        ):
            with self.assertRaises(RuntimeError):
                self.pipeline._apply_position_management(result=result, query_id="q_atomic_insert", current_price=100)

        # position insert should be rolled back
        self.assertIsNone(self.db.get_portfolio_position("EEE"))
        # journal should not exist
        self.assertEqual(self.db.get_trade_journal(code="EEE", limit=10), [])
        # snapshot should not be overwritten
        snapshot = self.db.get_latest_account_snapshot()
        self.assertIsNotNone(snapshot)
        self.assertAlmostEqual(snapshot.cash, 10000.0, places=2)
        self.assertAlmostEqual(snapshot.equity_value, 0.0, places=2)
        self.assertAlmostEqual(snapshot.total_value, 10000.0, places=2)

    def test_atomic_rollback_when_snapshot_fails_for_existing_position_update(self):
        self.db.save_account_snapshot(snapshot_date=date.today(), cash=10000, equity_value=0, total_value=10000)
        self.db.upsert_portfolio_position(
            code="FFF",
            name="FFF",
            quantity=10,
            avg_cost=100,
            current_price=100,
            weight=0.1,
            market_value=1000,
        )
        before_pos = self.db.get_portfolio_position("FFF")
        self.assertIsNotNone(before_pos)

        result = self._result("FFF", final_decision="SELL")
        with patch.object(
            self.db,
            "save_account_snapshot_in_session",
            side_effect=RuntimeError("snapshot failed"),
        ):
            with self.assertRaises(RuntimeError):
                self.pipeline._apply_position_management(result=result, query_id="q_atomic_update", current_price=100)

        # existing position update should be rolled back to previous value
        after_pos = self.db.get_portfolio_position("FFF")
        self.assertIsNotNone(after_pos)
        self.assertAlmostEqual(after_pos.quantity, 10.0, places=4)
        self.assertAlmostEqual(after_pos.market_value, 1000.0, places=2)

        # journal insert should also be rolled back
        self.assertEqual(self.db.get_trade_journal(code="FFF", limit=10), [])

        # snapshot remains unchanged
        snapshot = self.db.get_latest_account_snapshot()
        self.assertIsNotNone(snapshot)
        self.assertAlmostEqual(snapshot.cash, 10000.0, places=2)
        self.assertAlmostEqual(snapshot.equity_value, 0.0, places=2)
        self.assertAlmostEqual(snapshot.total_value, 10000.0, places=2)

    def test_atomic_success_persists_position_journal_and_snapshot(self):
        self.db.save_account_snapshot(snapshot_date=date.today(), cash=10000, equity_value=0, total_value=10000)
        result = self._result("GGG", final_decision="BUY")

        self.pipeline._apply_position_management(result=result, query_id="q_atomic_success", current_price=100)

        pos = self.db.get_portfolio_position("GGG")
        self.assertIsNotNone(pos)
        self.assertGreater(pos.quantity, 0)
        self.assertGreater(pos.market_value, 0)

        journal = self.db.get_trade_journal(code="GGG", limit=10)
        self.assertEqual(len(journal), 1)

        snapshot = self.db.get_latest_account_snapshot()
        self.assertIsNotNone(snapshot)
        self.assertLess(snapshot.cash, 10000.0)
        self.assertGreater(snapshot.equity_value, 0.0)
        self.assertAlmostEqual(snapshot.total_value, 10000.0, places=2)

    def test_read_only_position_management_does_not_persist_accounting_tables(self):
        self.db.save_account_snapshot(snapshot_date=date.today(), cash=10000, equity_value=0, total_value=10000)
        self.db.upsert_portfolio_position(
            code="HHH",
            name="HHH",
            quantity=10,
            avg_cost=100,
            current_price=100,
            weight=0.1,
            market_value=1000,
        )
        snapshot_before = self.db.get_latest_account_snapshot()
        pos_before = self.db.get_portfolio_position("HHH")
        journal_count_before = len(self.db.get_trade_journal(limit=100))

        result = self._result("HHH", final_decision="SELL")
        self.pipeline._apply_position_management(
            result=result,
            query_id="q_read_only",
            current_price=100,
            persist=False,
        )

        pos_after = self.db.get_portfolio_position("HHH")
        self.assertIsNotNone(pos_after)
        self.assertAlmostEqual(pos_after.quantity, float(pos_before.quantity), places=4)
        self.assertAlmostEqual(pos_after.market_value, float(pos_before.market_value), places=2)
        self.assertEqual(len(self.db.get_trade_journal(limit=100)), journal_count_before)

        snapshot_after = self.db.get_latest_account_snapshot()
        self.assertIsNotNone(snapshot_after)
        self.assertAlmostEqual(snapshot_after.cash, float(snapshot_before.cash), places=2)
        self.assertAlmostEqual(snapshot_after.equity_value, float(snapshot_before.equity_value), places=2)
        self.assertAlmostEqual(snapshot_after.total_value, float(snapshot_before.total_value), places=2)

    def test_read_only_matches_persisted_executable_math_with_affordability_fallback(self):
        self.db.save_account_snapshot(snapshot_date=date.today(), cash=100, equity_value=9900, total_value=10000)
        self.db.upsert_portfolio_position(
            code="AFB",
            name="AFB",
            quantity=10,
            avg_cost=100,
            current_price=100,
            weight=0.30,  # 故意制造权重与数量不一致，覆盖漂移场景
            market_value=1000,
        )

        ro_result = self._result("AFB", final_decision="BUY")
        self.pipeline._apply_position_management(
            result=ro_result,
            query_id="q_ro_fallback",
            current_price=100,
            persist=False,
        )

        rw_result = self._result("AFB", final_decision="BUY")
        self.pipeline._apply_position_management(
            result=rw_result,
            query_id="q_rw_fallback",
            current_price=100,
            persist=True,
        )

        self.assertEqual(ro_result.position_action, rw_result.position_action)
        self.assertAlmostEqual(ro_result.current_weight, rw_result.current_weight, places=4)
        self.assertAlmostEqual(ro_result.target_weight, rw_result.target_weight, places=4)
        self.assertAlmostEqual(ro_result.delta_amount, rw_result.delta_amount, places=2)
        self.assertEqual(ro_result.position_action, "ADD")
        self.assertAlmostEqual(ro_result.current_weight, 0.1, places=4)
        self.assertAlmostEqual(ro_result.target_weight, 0.11, places=4)
        self.assertAlmostEqual(ro_result.delta_amount, 100.0, places=2)

        latest_journal = self.db.get_trade_journal(code="AFB", limit=1)[0]
        self.assertAlmostEqual(latest_journal.target_quantity, 11.0, places=4)
        self.assertAlmostEqual(latest_journal.delta_amount, ro_result.delta_amount, places=2)

    def test_stale_stored_weight_does_not_drive_position_decision_math(self):
        self.db.save_account_snapshot(snapshot_date=date.today(), cash=9000, equity_value=1000, total_value=10000)
        self.db.upsert_portfolio_position(
            code="STL",
            name="STL",
            quantity=10,
            avg_cost=100,
            current_price=100,
            weight=0.90,  # stale weight should be ignored by decision logic
            market_value=1000,
        )

        result = self._result("STL", final_decision="HOLD")
        self.pipeline._apply_position_management(
            result=result,
            query_id="q_stale_weight",
            current_price=100,
            persist=False,
        )

        # With live recompute current_weight=1000/10000=0.1, HOLD should remain HOLD.
        self.assertEqual(result.position_action, "HOLD")
        self.assertAlmostEqual(result.current_weight, 0.1, places=4)
        self.assertAlmostEqual(result.target_weight, 0.1, places=4)
        self.assertAlmostEqual(result.delta_amount, 0.0, places=2)

    def test_analyze_stock_defaults_to_read_only_position_management(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.db = self.db
        pipeline.config = SimpleNamespace(analysis_read_only=True, save_context_snapshot=False)
        pipeline.fetcher_manager = SimpleNamespace(
            get_realtime_quote=lambda code: None,
            get_chip_distribution=lambda code: None,
        )
        pipeline.trend_analyzer = MagicMock()
        pipeline.search_service = SimpleNamespace(is_available=False)
        pipeline.analyzer = MagicMock(return_value=None)
        pipeline.analyzer.analyze.return_value = self._result("RO1", final_decision="BUY")
        pipeline.save_context_snapshot = False

        with patch.object(pipeline, "_apply_position_management") as mock_apply:
            result = pipeline.analyze_stock(
                code="RO1",
                report_type=ReportType.SIMPLE,
                query_id="q_analyze_ro",
                df_attrs={},
                market_overview=None,
            )

        self.assertIsNotNone(result)
        self.assertTrue(mock_apply.called)
        self.assertFalse(mock_apply.call_args.kwargs["persist"])

    def test_analyze_stock_persists_when_analysis_read_only_disabled(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.db = self.db
        pipeline.config = SimpleNamespace(analysis_read_only=False, save_context_snapshot=False)
        pipeline.fetcher_manager = SimpleNamespace(
            get_realtime_quote=lambda code: SimpleNamespace(name=f"股票{code}", price=100.0, change_pct=1.2),
            get_chip_distribution=lambda code: None,
        )
        pipeline.trend_analyzer = MagicMock()
        pipeline.search_service = SimpleNamespace(is_available=False)
        pipeline.analyzer = MagicMock()
        pipeline.analyzer.analyze.return_value = self._result("RW1", final_decision="BUY")
        pipeline.position_manager = PositionManager()
        pipeline.save_context_snapshot = False

        self.db.save_account_snapshot(snapshot_date=date.today(), cash=10000, equity_value=0, total_value=10000)

        with patch.object(pipeline, "_apply_decision_structure") as mock_decision:
            mock_decision.return_value = None
            result = pipeline.analyze_stock(
                code="RW1",
                report_type=ReportType.SIMPLE,
                query_id="q_analyze_rw",
                df_attrs={},
                market_overview=None,
            )

        self.assertIsNotNone(result)
        self.assertIsNotNone(self.db.get_portfolio_position("RW1"))
        self.assertEqual(len(self.db.get_trade_journal(code="RW1", limit=10)), 1)
        snapshot_after = self.db.get_latest_account_snapshot()
        self.assertIsNotNone(snapshot_after)
        self.assertLess(snapshot_after.cash, 10000.0)


if __name__ == "__main__":
    unittest.main()
