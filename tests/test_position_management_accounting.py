# -*- coding: utf-8 -*-

import os
import tempfile
import threading
import time
import unittest
from datetime import date
from unittest.mock import patch

from src.analyzer import AnalysisResult
from src.core.pipeline import StockAnalysisPipeline
from src.core.position_manager import PositionManager
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

    def test_concurrent_without_automatic_lock_can_drift_account_snapshot(self):
        self.db.save_account_snapshot(snapshot_date=date.today(), cash=10000, equity_value=0, total_value=10000)
        self.pipeline.query_source = "api"  # 非自动路径：不启用串行化锁

        barrier = threading.Barrier(2, timeout=2)
        original_get_latest = self.db.get_latest_account_snapshot

        def synchronized_get_latest():
            snapshot = original_get_latest()
            barrier.wait()
            return snapshot

        with patch.object(self.db, "get_latest_account_snapshot", side_effect=synchronized_get_latest):
            self._run_parallel_position_updates(
                pipeline=self.pipeline,
                codes=["A01", "B01"],
                query_prefix="q_race_unlocked",
            )

        # 两个线程都在同一旧快照基线上计算，会导致快照总资产偏离恒等式（现金+权益）
        snapshot = self.db.get_latest_account_snapshot()
        self.assertIsNotNone(snapshot)
        self.assertNotAlmostEqual(snapshot.total_value, 10000.0, places=2)

    def test_concurrent_automatic_updates_are_serialized_and_consistent(self):
        for query_source in ("system", "cli"):
            with self.subTest(query_source=query_source):
                self._rebuild_pipeline_with_fresh_db()
                self.db.save_account_snapshot(snapshot_date=date.today(), cash=10000, equity_value=0, total_value=10000)
                self.pipeline.query_source = query_source  # 自动路径：启用串行化锁

                original_get_latest = self.db.get_latest_account_snapshot
                active_counter = {"value": 0, "max": 0}
                counter_lock = threading.Lock()

                def tracked_get_latest():
                    with counter_lock:
                        active_counter["value"] += 1
                        active_counter["max"] = max(active_counter["max"], active_counter["value"])
                    try:
                        time.sleep(0.05)
                        return original_get_latest()
                    finally:
                        with counter_lock:
                            active_counter["value"] -= 1

                with patch.object(self.db, "get_latest_account_snapshot", side_effect=tracked_get_latest):
                    self._run_parallel_position_updates(
                        pipeline=self.pipeline,
                        codes=["A02", "B02"],
                        query_prefix=f"q_race_locked_{query_source}",
                    )

                # 读取基线阶段应被串行化（最大并发读取为 1）
                self.assertEqual(active_counter["max"], 1)

                # 自动路径并发执行后仍应保持组合快照一致
                snapshot = self.db.get_latest_account_snapshot()
                self.assertIsNotNone(snapshot)
                self.assertAlmostEqual(snapshot.cash, 8000.0, places=2)
                self.assertAlmostEqual(snapshot.equity_value, 2000.0, places=2)
                self.assertAlmostEqual(snapshot.total_value, 10000.0, places=2)

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


if __name__ == "__main__":
    unittest.main()
