# -*- coding: utf-8 -*-

import os
import tempfile
import threading
import time
import unittest
from datetime import date, datetime
from datetime import timezone
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from src.analyzer import AnalysisResult
from src.config import Config, get_config
from src.core.pipeline import StockAnalysisPipeline
from src.core.position_manager import PositionManager
from src.enums import ReportType
from src.notification import NotificationService
from src.storage import DatabaseManager


class PositionManagementAccountingTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        DatabaseManager.reset_instance()
        self.db = DatabaseManager(db_url=f"sqlite:///{os.path.join(self.tmp.name, 'pm_test.db')}")
        self.pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        self.pipeline.db = self.db
        self.pipeline.position_manager = PositionManager()
        self.pipeline.config = SimpleNamespace(
            min_position_delta_amount=0.0,
            min_order_notional=0.0,
            market_timezone="Australia/Sydney",
            market_calendar="ASX",
        )

    def tearDown(self):
        Config.reset_instance()
        DatabaseManager.reset_instance()
        self.tmp.cleanup()

    def _result(
        self,
        code: str,
        final_decision: str,
        market_regime: str = "NEUTRAL",
        sentiment_score: int = 60,
    ) -> AnalysisResult:
        r = AnalysisResult(
            code=code,
            name=f"股票{code}",
            sentiment_score=sentiment_score,
            trend_prediction="震荡",
            operation_advice="持有",
        )
        r.final_decision = final_decision
        r.market_regime = market_regime
        r.event_risk = "LOW"
        r.data_quality_flag = "OK"
        return r

    def _run_read_only_batch(
        self,
        results_by_code: dict[str, AnalysisResult],
        prices_by_code: dict[str, float],
        *,
        single_stock_notify: bool = False,
        send_notification: bool = False,
    ):
        self.pipeline.config = SimpleNamespace(
            analysis_read_only=True,
            save_context_snapshot=False,
            single_stock_notify=single_stock_notify,
            report_type=ReportType.SIMPLE.value,
            analysis_delay=0,
            market_timezone="Australia/Sydney",
            market_calendar="ASX",
            execution_price_policy="realtime_if_available",
            min_position_delta_amount=0.0,
            min_order_notional=0.0,
            max_single_buy_cash_fraction=0.34,
            max_single_buy_cash_amount=None,
        )
        self.pipeline.max_workers = 1
        self.pipeline.save_context_snapshot = False
        self.pipeline._now_for_testing = datetime(2026, 4, 15, 0, 30, tzinfo=timezone.utc)
        self.pipeline.fetcher_manager = SimpleNamespace(
            get_realtime_quote=lambda code: SimpleNamespace(
                name=f"股票{code}",
                price=prices_by_code[code],
                change_pct=0.0,
            ),
            prefetch_realtime_quotes=lambda codes: 0,
        )
        self.pipeline.search_service = SimpleNamespace(is_available=False)
        self.pipeline.trend_analyzer = MagicMock()
        self.sent_single_notifications = []

        def fake_single_report(result):
            self.sent_single_notifications.append((result.code, result.delta_amount, result.position_action))
            return f"{result.code}:{result.delta_amount}:{result.position_action}"

        self.pipeline.notifier = SimpleNamespace(
            is_available=lambda: True,
            generate_dashboard_report=lambda results: "dashboard",
            generate_single_stock_report=fake_single_report,
            send=lambda report, email_stock_codes=None: True,
        )
        self.pipeline.analyzer = MagicMock()

        def fake_analyze(enhanced_context, news_context=None):
            return results_by_code[enhanced_context["code"]]

        self.pipeline.analyzer.analyze.side_effect = fake_analyze

        def mark_pass(*, result, enhanced_context):
            result.validation_status = "PASS"
            result.validation_issues = []

        with patch.object(
            self.pipeline,
            "fetch_and_save_stock_data",
            return_value=(True, None, {}),
        ), patch.object(self.pipeline, "_fetch_market_overview", return_value={}), patch.object(
            self.pipeline,
            "_apply_decision_structure",
        ), patch.object(
            self.pipeline,
            "_apply_validation_gate",
            side_effect=mark_pass,
        ), patch.object(
            self.pipeline,
            "_send_notifications",
            return_value={},
        ):
            return self.pipeline.run(
                stock_codes=list(results_by_code.keys()),
                dry_run=False,
                send_notification=send_notification,
            )

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
        self.assertAlmostEqual(snap.equity_value, 990.0, places=2)
        self.assertAlmostEqual(snap.cash, 9010.0, places=2)
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

    def test_position_management_updates_ax_position_for_asx_alias_result_without_duplicate(self):
        self.db.save_account_snapshot(snapshot_date=date.today(), cash=8000, equity_value=2000, total_value=10000)
        self.db.upsert_portfolio_position(
            code="NHF.AX",
            name="NHF",
            quantity=100,
            avg_cost=20,
            current_price=20,
            weight=0.2,
            market_value=2000,
        )

        result = self._result("NHF.ASX", final_decision="BUY")
        self.pipeline._apply_position_management(result=result, query_id="q_alias", current_price=20)

        positions = self.db.get_portfolio_positions(only_open=False)
        self.assertEqual([position.code for position in positions], ["NHF.AX"])
        self.assertEqual(result.code, "NHF.AX")
        self.assertEqual(result.position_action, "ADD")
        self.assertAlmostEqual(result.current_weight, 0.2, places=4)
        self.assertAlmostEqual(positions[0].quantity, 125.0, places=6)

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

    def test_read_only_daily_batch_shares_cash_across_same_day_buy_candidates(self):
        self.db.save_account_snapshot(snapshot_date=date.today(), cash=1043.73, equity_value=10000, total_value=11043.73)
        results = self._run_read_only_batch(
            {
                "EGH.AX": self._result("EGH.AX", final_decision="BUY", sentiment_score=88),
                "GMG.AX": self._result("GMG.AX", final_decision="BUY", sentiment_score=61),
                "BHP.AX": self._result("BHP.AX", final_decision="BUY", sentiment_score=76),
            },
            {"EGH.AX": 10.0, "GMG.AX": 10.0, "BHP.AX": 10.0},
        )

        by_code = {result.code: result for result in results}
        buy_deltas = [
            result.delta_amount
            for result in by_code.values()
            if result.position_action in {"OPEN", "ADD"} and result.delta_amount > 0
        ]

        self.assertLessEqual(sum(buy_deltas), 1043.73 + 0.01)
        self.assertEqual(by_code["EGH.AX"].position_action, "OPEN")
        self.assertEqual(by_code["BHP.AX"].position_action, "OPEN")
        self.assertEqual(by_code["GMG.AX"].position_action, "OPEN")
        self.assertAlmostEqual(by_code["EGH.AX"].delta_amount, 350.0, places=2)
        self.assertAlmostEqual(by_code["BHP.AX"].delta_amount, 230.0, places=2)
        self.assertAlmostEqual(by_code["GMG.AX"].delta_amount, 150.0, places=2)

    def test_single_open_small_cash_account_respects_single_buy_cash_fraction(self):
        self.pipeline.config = SimpleNamespace(
            min_position_delta_amount=0.0,
            min_order_notional=0.0,
            max_single_buy_cash_fraction=0.34,
            max_single_buy_cash_amount=None,
        )
        self.db.save_account_snapshot(snapshot_date=date.today(), cash=1043.73, equity_value=10000, total_value=11043.73)

        result = self._result("SMALL.AX", final_decision="BUY")
        self.pipeline._apply_position_management(
            result=result,
            query_id="q_single_buy_cash_fraction",
            current_price=10.0,
            persist=False,
        )

        self.assertEqual(result.position_action, "OPEN")
        self.assertLessEqual(result.delta_amount, 1043.73 * 0.34 + 0.01)
        self.assertLess(result.delta_amount, 1043.73 * 0.5)
        self.assertIn("sizing_cap=single_buy_cash_cap(limit=354.87)", result.action_reason)

    def test_single_open_large_cash_account_keeps_ten_percent_target_when_cap_not_binding(self):
        self.pipeline.config = SimpleNamespace(
            min_position_delta_amount=0.0,
            min_order_notional=0.0,
            max_single_buy_cash_fraction=0.34,
            max_single_buy_cash_amount=None,
        )
        self.db.save_account_snapshot(snapshot_date=date.today(), cash=10000, equity_value=0, total_value=10000)

        result = self._result("LARGE.AX", final_decision="BUY")
        self.pipeline._apply_position_management(
            result=result,
            query_id="q_large_single_buy_cash_fraction",
            current_price=10.0,
            persist=False,
        )

        self.assertEqual(result.position_action, "OPEN")
        self.assertAlmostEqual(result.target_weight, 0.1, places=4)
        self.assertAlmostEqual(result.delta_amount, 1000.0, places=2)
        self.assertNotIn("sizing_cap=single_buy_cash_cap", result.action_reason)

    def test_single_open_respects_absolute_cash_amount_cap(self):
        self.pipeline.config = SimpleNamespace(
            min_position_delta_amount=0.0,
            min_order_notional=0.0,
            max_single_buy_cash_fraction=1.0,
            max_single_buy_cash_amount=250.0,
        )
        self.db.save_account_snapshot(snapshot_date=date.today(), cash=10000, equity_value=0, total_value=10000)

        result = self._result("CAP.AX", final_decision="BUY")
        self.pipeline._apply_position_management(
            result=result,
            query_id="q_single_buy_amount_cap",
            current_price=10.0,
            persist=False,
        )

        self.assertEqual(result.position_action, "OPEN")
        self.assertAlmostEqual(result.delta_amount, 250.0, places=2)
        self.assertLess(result.target_weight, 0.1)
        self.assertIn("sizing_cap=single_buy_cash_cap(limit=250.00)", result.action_reason)

    def test_batch_shared_cash_pool_stacks_with_single_buy_cash_fraction(self):
        self.db.save_account_snapshot(snapshot_date=date.today(), cash=1043.73, equity_value=10000, total_value=11043.73)
        results = self._run_read_only_batch(
            {
                "EGH.AX": self._result("EGH.AX", final_decision="BUY", sentiment_score=88),
                "GMG.AX": self._result("GMG.AX", final_decision="BUY", sentiment_score=61),
                "BHP.AX": self._result("BHP.AX", final_decision="BUY", sentiment_score=76),
            },
            {"EGH.AX": 10.0, "GMG.AX": 10.0, "BHP.AX": 10.0},
        )

        by_code = {result.code: result for result in results}
        first_budget = 1043.73
        first_delta = by_code["EGH.AX"].delta_amount
        second_budget = first_budget - first_delta
        second_delta = by_code["BHP.AX"].delta_amount
        third_budget = second_budget - second_delta
        third_delta = by_code["GMG.AX"].delta_amount

        self.assertEqual(by_code["EGH.AX"].position_action, "OPEN")
        self.assertEqual(by_code["BHP.AX"].position_action, "OPEN")
        self.assertEqual(by_code["GMG.AX"].position_action, "OPEN")
        self.assertLessEqual(first_delta, first_budget * 0.34 + 0.01)
        self.assertLessEqual(second_delta, second_budget * 0.34 + 0.01)
        self.assertLessEqual(third_delta, third_budget * 0.34 + 0.01)
        self.assertLessEqual(first_delta + second_delta + third_delta, 1043.73 + 0.01)

    def test_single_stock_notify_batch_sends_shared_cash_sized_results(self):
        self.db.save_account_snapshot(snapshot_date=date.today(), cash=1043.73, equity_value=10000, total_value=11043.73)
        results = self._run_read_only_batch(
            {
                "EGH.AX": self._result("EGH.AX", final_decision="BUY", sentiment_score=88),
                "GMG.AX": self._result("GMG.AX", final_decision="BUY", sentiment_score=61),
                "BHP.AX": self._result("BHP.AX", final_decision="BUY", sentiment_score=76),
            },
            {"EGH.AX": 10.0, "GMG.AX": 10.0, "BHP.AX": 10.0},
            single_stock_notify=True,
            send_notification=True,
        )

        by_code = {result.code: result for result in results}
        sent_by_code = {
            code: (delta_amount, position_action)
            for code, delta_amount, position_action in self.sent_single_notifications
        }
        sent_buy_deltas = [
            delta_amount
            for delta_amount, position_action in sent_by_code.values()
            if position_action in {"OPEN", "ADD"} and delta_amount > 0
        ]

        self.assertEqual(set(sent_by_code), {"EGH.AX", "GMG.AX", "BHP.AX"})
        self.assertLessEqual(sum(sent_buy_deltas), 1043.73 + 0.01)
        self.assertEqual(sent_by_code["EGH.AX"], (by_code["EGH.AX"].delta_amount, by_code["EGH.AX"].position_action))
        self.assertEqual(sent_by_code["BHP.AX"], (by_code["BHP.AX"].delta_amount, by_code["BHP.AX"].position_action))
        self.assertEqual(sent_by_code["GMG.AX"], (by_code["GMG.AX"].delta_amount, by_code["GMG.AX"].position_action))
        self.assertAlmostEqual(by_code["EGH.AX"].delta_amount, 350.0, places=2)
        self.assertAlmostEqual(by_code["BHP.AX"].delta_amount, 230.0, places=2)
        self.assertAlmostEqual(by_code["GMG.AX"].delta_amount, 150.0, places=2)

    def test_batch_position_management_failure_does_not_drop_other_histories(self):
        self.db.save_account_snapshot(snapshot_date=date.today(), cash=1000, equity_value=10000, total_value=11000)
        original_apply = self.pipeline._apply_position_management

        def fail_one_symbol(*, result, **kwargs):
            if result.code == "FAIL.AX":
                raise RuntimeError("forced sizing failure")
            return original_apply(result=result, **kwargs)

        with patch.object(self.pipeline, "_apply_position_management", side_effect=fail_one_symbol):
            results = self._run_read_only_batch(
                {
                    "FAIL.AX": self._result("FAIL.AX", final_decision="BUY", sentiment_score=90),
                    "OK.AX": self._result("OK.AX", final_decision="BUY", sentiment_score=80),
                },
                {"FAIL.AX": 10.0, "OK.AX": 10.0},
            )

        by_code = {result.code: result for result in results}
        self.assertEqual(by_code["FAIL.AX"].position_action, "HOLD")
        self.assertAlmostEqual(by_code["FAIL.AX"].delta_amount, 0.0, places=2)
        self.assertEqual(by_code["FAIL.AX"].action_reason, "position_management_failed")
        self.assertEqual(by_code["OK.AX"].position_action, "OPEN")
        self.assertGreater(by_code["OK.AX"].delta_amount, 0.0)

        histories = self.db.get_analysis_history(limit=10)
        histories_by_code = {history.code: history for history in histories}
        self.assertEqual(set(histories_by_code), {"FAIL.AX", "OK.AX"})
        self.assertEqual(histories_by_code["FAIL.AX"].position_action, "HOLD")
        self.assertEqual(histories_by_code["FAIL.AX"].action_reason, "position_management_failed")
        self.assertEqual(histories_by_code["OK.AX"].position_action, "OPEN")

    def test_read_only_daily_batch_adds_same_day_reduce_release_to_buy_budget(self):
        self.db.save_account_snapshot(snapshot_date=date.today(), cash=100, equity_value=2000, total_value=2100)
        self.db.upsert_portfolio_position(
            code="RED.AX",
            name="RED",
            quantity=20,
            avg_cost=100,
            current_price=100,
            weight=2000 / 2100,
            market_value=2000,
        )

        results = self._run_read_only_batch(
            {
                "RED.AX": self._result("RED.AX", final_decision="HOLD", market_regime="RISK_OFF"),
                "BUY.AX": self._result("BUY.AX", final_decision="BUY", sentiment_score=80),
            },
            {"RED.AX": 100.0, "BUY.AX": 100.0},
        )

        by_code = {result.code: result for result in results}
        self.assertEqual(by_code["RED.AX"].position_action, "REDUCE")
        self.assertLess(by_code["RED.AX"].delta_amount, 0.0)
        self.assertEqual(by_code["BUY.AX"].position_action, "OPEN")
        self.assertGreater(by_code["BUY.AX"].delta_amount, 100.0)
        self.assertLessEqual(
            by_code["BUY.AX"].delta_amount,
            100.0 + abs(by_code["RED.AX"].delta_amount) + 0.01,
        )

    def test_read_only_daily_batch_groups_by_effective_event_risk_decision(self):
        self.db.save_account_snapshot(snapshot_date=date.today(), cash=100, equity_value=2000, total_value=2100)
        self.db.upsert_portfolio_position(
            code="RISK.AX",
            name="RISK",
            quantity=20,
            avg_cost=100,
            current_price=100,
            weight=2000 / 2100,
            market_value=2000,
        )
        high_event_risk = self._result(
            "RISK.AX",
            final_decision="BUY",
            market_regime="RISK_OFF",
            sentiment_score=10,
        )
        high_event_risk.event_risk = "HIGH"

        results = self._run_read_only_batch(
            {
                "BUY.AX": self._result("BUY.AX", final_decision="BUY", sentiment_score=90),
                "RISK.AX": high_event_risk,
            },
            {"BUY.AX": 100.0, "RISK.AX": 100.0},
        )

        by_code = {result.code: result for result in results}
        self.assertEqual(by_code["RISK.AX"].final_decision, "HOLD")
        self.assertEqual(by_code["RISK.AX"].position_action, "REDUCE")
        self.assertLess(by_code["RISK.AX"].delta_amount, 0.0)
        self.assertEqual(by_code["BUY.AX"].position_action, "OPEN")
        self.assertGreater(by_code["BUY.AX"].delta_amount, 100.0)
        self.assertLessEqual(
            by_code["BUY.AX"].delta_amount,
            100.0 + abs(by_code["RISK.AX"].delta_amount) + 0.01,
        )

    def test_read_only_daily_batch_subtracts_cash_deficit_before_buy_selection(self):
        self.db.save_account_snapshot(snapshot_date=date.today(), cash=-500, equity_value=10000, total_value=9500)
        self.db.upsert_portfolio_position(
            code="RED.AX",
            name="RED",
            quantity=19,
            avg_cost=100,
            current_price=100,
            weight=1900 / 9500,
            market_value=1900,
        )
        self.db.upsert_portfolio_position(
            code="KEEP.AX",
            name="KEEP",
            quantity=81,
            avg_cost=100,
            current_price=100,
            weight=8100 / 9500,
            market_value=8100,
        )

        results = self._run_read_only_batch(
            {
                "RED.AX": self._result("RED.AX", final_decision="HOLD", market_regime="RISK_OFF"),
                "BUY.AX": self._result("BUY.AX", final_decision="BUY", sentiment_score=80),
            },
            {"RED.AX": 100.0, "BUY.AX": 100.0},
        )

        by_code = {result.code: result for result in results}
        self.assertAlmostEqual(by_code["RED.AX"].delta_amount, -900.0, places=2)
        self.assertEqual(by_code["BUY.AX"].position_action, "OPEN")
        self.assertAlmostEqual(by_code["BUY.AX"].delta_amount, 100.0, places=2)
        self.assertLessEqual(by_code["BUY.AX"].delta_amount, 400.0 * 0.34 + 0.01)

    def test_high_event_risk_downgrades_buy_to_hold(self):
        self.db.save_account_snapshot(snapshot_date=date.today(), cash=8000, equity_value=2000, total_value=10000)
        self.db.upsert_portfolio_position(
            code="LLM",
            name="LLM",
            quantity=20,
            avg_cost=100,
            current_price=100,
            weight=0.2,
            market_value=2000,
        )

        low_risk = self._result("LLM", final_decision="BUY", market_regime="NEUTRAL")
        low_risk.event_risk = "LOW"
        self.pipeline._apply_position_management(
            result=low_risk,
            query_id="q_llm_low",
            current_price=100,
            persist=False,
        )

        high_risk = self._result("LLM", final_decision="BUY", market_regime="NEUTRAL")
        high_risk.event_risk = "HIGH"
        self.pipeline._apply_position_management(
            result=high_risk,
            query_id="q_llm_high",
            current_price=100,
            persist=False,
        )

        self.assertEqual(low_risk.final_decision, "BUY")
        self.assertIn(low_risk.position_action, {"ADD", "OPEN"})
        self.assertEqual(high_risk.final_decision, "HOLD")
        self.assertEqual(high_risk.position_action, "HOLD")
        self.assertAlmostEqual(high_risk.target_weight, 0.2)
        self.assertAlmostEqual(high_risk.delta_amount, 0.0)
        self.assertIn("高事件风险", high_risk.action_reason)

    def test_high_event_risk_downgrades_sell_to_hold(self):
        self.db.save_account_snapshot(snapshot_date=date.today(), cash=8000, equity_value=2000, total_value=10000)
        self.db.upsert_portfolio_position(
            code="HISELL",
            name="HISELL",
            quantity=20,
            avg_cost=100,
            current_price=100,
            weight=0.2,
            market_value=2000,
        )

        result = self._result("HISELL", final_decision="SELL", market_regime="NEUTRAL")
        result.event_risk = "HIGH"
        self.pipeline._apply_position_management(
            result=result,
            query_id="q_llm_high_sell",
            current_price=100,
            persist=False,
        )

        self.assertEqual(result.final_decision, "HOLD")
        self.assertEqual(result.position_action, "HOLD")
        self.assertAlmostEqual(result.target_weight, 0.2)
        self.assertAlmostEqual(result.delta_amount, 0.0)
        self.assertIn("高事件风险", result.action_reason)

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
        self.assertEqual(ro_result.position_action, "REDUCE")
        self.assertAlmostEqual(ro_result.current_weight, 0.9091, places=4)
        self.assertAlmostEqual(ro_result.target_weight, 0.3636, places=4)
        self.assertAlmostEqual(ro_result.delta_amount, -600.0, places=2)
        self.assertEqual(ro_result.target_quantity, 4)

        latest_journal = self.db.get_trade_journal(code="AFB", limit=1)[0]
        self.assertEqual(latest_journal.target_quantity, 4.0)
        self.assertAlmostEqual(latest_journal.delta_amount, ro_result.delta_amount, places=2)

    def test_computed_target_quantity_is_attached_to_result_in_read_only_and_persist_modes(self):
        self.db.save_account_snapshot(snapshot_date=date.today(), cash=10000, equity_value=0, total_value=10000)

        ro_result = self._result("TQRO", final_decision="BUY")
        self.pipeline._apply_position_management(
            result=ro_result,
            query_id="q_target_qty_ro",
            current_price=100,
            persist=False,
        )

        rw_result = self._result("TQRW", final_decision="BUY")
        self.pipeline._apply_position_management(
            result=rw_result,
            query_id="q_target_qty_rw",
            current_price=100,
            persist=True,
        )

        self.assertEqual(ro_result.target_quantity, 10)
        self.assertEqual(rw_result.target_quantity, 10)

    def test_close_target_quantity_zero_is_preserved_and_reported_deterministically(self):
        self.db.save_account_snapshot(snapshot_date=date.today(), cash=9000, equity_value=1000, total_value=10000)
        self.db.upsert_portfolio_position(
            code="CLS",
            name="CLS",
            quantity=10,
            avg_cost=100,
            current_price=100,
            weight=0.1,
            market_value=1000,
        )

        ro_result = self._result("CLS", final_decision="SELL")
        self.pipeline._apply_position_management(
            result=ro_result,
            query_id="q_close_ro",
            current_price=100,
            persist=False,
        )

        rw_result = self._result("CLS", final_decision="SELL")
        self.pipeline._apply_position_management(
            result=rw_result,
            query_id="q_close_rw",
            current_price=100,
            persist=True,
        )

        self.assertEqual(ro_result.target_quantity, 0)
        self.assertEqual(rw_result.target_quantity, 0)

        service = NotificationService.__new__(NotificationService)
        formatted = service._format_deterministic_sizing_text(ro_result)
        self.assertIn("CLOSE | 目标仓位 0.00% | 模拟Δ -1,000.00 | 目标数量 0 股", formatted)
        self.assertNotIn("目标数量 N/A（确定性引擎未提供）", formatted)

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

    def test_live_portfolio_state_prefers_live_denominator_over_larger_snapshot_total(self):
        latest_snapshot = SimpleNamespace(cash=100.0, equity_value=10000.0, total_value=10100.0)
        existing = SimpleNamespace(quantity=1.0, avg_cost=10.0, current_price=10.0, market_value=10.0)
        open_positions = [SimpleNamespace(code="LIV", quantity=1.0, current_price=10.0, market_value=10.0)]

        state = self.pipeline._build_live_portfolio_state(
            code="LIV",
            existing=existing,
            open_positions=open_positions,
            latest_snapshot=latest_snapshot,
            current_price=10.0,
        )

        self.assertAlmostEqual(state["total_value"], 110.0, places=2)
        self.assertAlmostEqual(state["current_weight"], 1.0 / 11.0, places=6)

    def test_snapshot_equity_does_not_override_valid_live_equity(self):
        latest_snapshot = SimpleNamespace(cash=100.0, equity_value=5000.0, total_value=5100.0)
        existing = SimpleNamespace(quantity=1.0, avg_cost=100.0, current_price=200.0, market_value=200.0)
        open_positions = [SimpleNamespace(code="LEQ", quantity=1.0, current_price=200.0, market_value=200.0)]

        state = self.pipeline._build_live_portfolio_state(
            code="LEQ",
            existing=existing,
            open_positions=open_positions,
            latest_snapshot=latest_snapshot,
            current_price=200.0,
        )

        self.assertAlmostEqual(state["current_equity_value"], 200.0, places=2)
        self.assertAlmostEqual(state["total_value"], 300.0, places=2)
        self.assertAlmostEqual(state["current_weight"], 2.0 / 3.0, places=6)

    def test_snapshot_fallback_works_when_live_recompute_invalid(self):
        latest_snapshot = SimpleNamespace(cash=0.0, equity_value=0.0, total_value=500.0)
        existing = None
        open_positions = [SimpleNamespace(code="INV", quantity=0.0, current_price=0.0, market_value=0.0)]

        state = self.pipeline._build_live_portfolio_state(
            code="INV",
            existing=existing,
            open_positions=open_positions,
            latest_snapshot=latest_snapshot,
            current_price=None,
        )

        self.assertAlmostEqual(state["current_equity_value"], 0.0, places=2)
        self.assertAlmostEqual(state["total_value"], 500.0, places=2)
        self.assertAlmostEqual(state["current_weight"], 0.0, places=6)

    def test_stale_snapshot_total_no_longer_suppresses_target_weight_and_delta_amount(self):
        self.db.save_account_snapshot(snapshot_date=date.today(), cash=100, equity_value=10000, total_value=10100)
        self.db.upsert_portfolio_position(
            code="SUP",
            name="SUP",
            quantity=1,
            avg_cost=10,
            current_price=10,
            weight=0.1,
            market_value=10,
        )

        result = self._result("SUP", final_decision="BUY")
        self.pipeline._apply_position_management(
            result=result,
            query_id="q_stale_snapshot_total",
            current_price=10,
            persist=False,
        )

        self.assertEqual(result.position_action, "ADD")
        self.assertAlmostEqual(result.current_weight, 0.0909, places=4)
        self.assertAlmostEqual(result.target_weight, 0.1818, places=4)
        self.assertAlmostEqual(result.delta_amount, 10.0, places=2)

    def test_small_delta_amount_is_suppressed_to_hold(self):
        self.pipeline.config = SimpleNamespace(min_position_delta_amount=200.0, min_order_notional=0.0)
        self.db.save_account_snapshot(snapshot_date=date.today(), cash=6510, equity_value=3490, total_value=10000)
        self.db.upsert_portfolio_position(
            code="SDA",
            name="SDA",
            quantity=349,
            avg_cost=10,
            current_price=10,
            weight=0.349,
            market_value=3490,
        )

        result = self._result("SDA", final_decision="BUY")
        self.pipeline._apply_position_management(
            result=result,
            query_id="q_small_delta",
            current_price=10,
            persist=False,
        )

        self.assertEqual(result.position_action, "HOLD")
        self.assertEqual(result.target_quantity, 349)
        self.assertAlmostEqual(result.delta_amount, 0.0, places=2)
        self.assertIn("execution_blocked=min_delta_amount", result.action_reason)

    def test_small_order_notional_is_suppressed_to_hold(self):
        self.pipeline.config = SimpleNamespace(min_position_delta_amount=0.0, min_order_notional=200.0)
        self.db.save_account_snapshot(snapshot_date=date.today(), cash=6510, equity_value=3490, total_value=10000)
        self.db.upsert_portfolio_position(
            code="SON",
            name="SON",
            quantity=349,
            avg_cost=10,
            current_price=10,
            weight=0.349,
            market_value=3490,
        )

        result = self._result("SON", final_decision="BUY")
        self.pipeline._apply_position_management(
            result=result,
            query_id="q_small_notional",
            current_price=10,
            persist=False,
        )

        self.assertEqual(result.position_action, "HOLD")
        self.assertEqual(result.target_quantity, 349)
        self.assertAlmostEqual(result.delta_amount, 0.0, places=2)
        self.assertIn("execution_blocked=min_order_notional", result.action_reason)

    @patch.dict(os.environ, {}, clear=True)
    def test_config_defaults_suppress_noise_sized_delta_amounts(self):
        Config.reset_instance()
        self.pipeline.config = get_config()
        self.db.save_account_snapshot(snapshot_date=date.today(), cash=9990, equity_value=10, total_value=10000)
        self.db.upsert_portfolio_position(
            code="DFD",
            name="DFD",
            quantity=1,
            avg_cost=10,
            current_price=10,
            weight=0.001,
            market_value=10,
        )

        result = self._result("DFD", final_decision="BUY")
        with patch.object(
            self.pipeline.position_manager,
            "decide",
            return_value=SimpleNamespace(target_weight=0.002, reason="small target adjustment"),
        ):
            self.pipeline._apply_position_management(
                result=result,
                query_id="q_default_small_delta",
                current_price=10,
                persist=False,
            )

        self.assertEqual(self.pipeline._get_min_position_delta_amount(), 20.0)
        self.assertEqual(self.pipeline._get_min_order_notional(), 20.0)
        self.assertEqual(self.pipeline._get_min_buy_order_notional(), 1000.0)
        self.assertEqual(result.position_action, "HOLD")
        self.assertEqual(result.target_quantity, 1)
        self.assertAlmostEqual(result.delta_amount, 0.0, places=2)
        self.assertIn("execution_blocked=min_delta_amount", result.action_reason)

    @patch.dict(os.environ, {}, clear=True)
    def test_config_defaults_suppress_sub_1000_buy_side_notional(self):
        Config.reset_instance()
        self.pipeline.config = get_config()
        self.db.save_account_snapshot(snapshot_date=date.today(), cash=9978.22, equity_value=21.78, total_value=10000)

        result = self._result("MBN", final_decision="BUY")
        with patch.object(
            self.pipeline.position_manager,
            "decide",
            return_value=SimpleNamespace(target_weight=0.002178, reason="small open adjustment"),
        ):
            self.pipeline._apply_position_management(
                result=result,
                query_id="q_default_min_buy_notional",
                current_price=21.78,
                persist=False,
            )

        self.assertEqual(result.position_action, "HOLD")
        self.assertEqual(result.target_quantity, 0.0)
        self.assertAlmostEqual(result.delta_amount, 0.0, places=2)
        self.assertIn("execution_blocked=min_buy_order_notional", result.action_reason)

    def test_config_defaults_single_buy_cash_cap(self):
        env_path = os.path.join(self.tmp.name, "default_single_buy_cap.env")
        with open(env_path, "w", encoding="utf-8") as handle:
            handle.write("")

        with patch.dict(os.environ, {"ENV_FILE": env_path}, clear=True):
            Config.reset_instance()
            config = get_config()

        self.assertEqual(config.max_single_buy_cash_fraction, 0.34)
        self.assertIsNone(config.max_single_buy_cash_amount)

    def test_env_parses_single_buy_cash_caps(self):
        env_path = os.path.join(self.tmp.name, "configured_single_buy_cap.env")
        with open(env_path, "w", encoding="utf-8") as handle:
            handle.write(
                "STOCK_LIST=BHP.AX\n"
                "MAX_SINGLE_BUY_CASH_FRACTION=0.25\n"
                "MAX_SINGLE_BUY_CASH_AMOUNT=500\n"
            )

        with patch.dict(os.environ, {"ENV_FILE": env_path}, clear=True):
            Config.reset_instance()
            config = get_config()

        self.assertEqual(config.max_single_buy_cash_fraction, 0.25)
        self.assertEqual(config.max_single_buy_cash_amount, 500.0)

    @patch.dict(
        os.environ,
        {"MIN_POSITION_DELTA_AMOUNT": "0", "MIN_ORDER_NOTIONAL": "0", "MIN_BUY_ORDER_NOTIONAL": "0"},
        clear=True,
    )
    def test_env_can_restore_zero_threshold_behavior(self):
        Config.reset_instance()
        self.pipeline.config = get_config()
        self.db.save_account_snapshot(snapshot_date=date.today(), cash=9990, equity_value=10, total_value=10000)
        self.db.upsert_portfolio_position(
            code="ZTH",
            name="ZTH",
            quantity=1,
            avg_cost=10,
            current_price=10,
            weight=0.001,
            market_value=10,
        )

        result = self._result("ZTH", final_decision="BUY")
        with patch.object(
            self.pipeline.position_manager,
            "decide",
            return_value=SimpleNamespace(target_weight=0.002, reason="small target adjustment"),
        ):
            self.pipeline._apply_position_management(
                result=result,
                query_id="q_zero_threshold_small_delta",
                current_price=10,
                persist=False,
            )

        self.assertEqual(self.pipeline._get_min_position_delta_amount(), 0.0)
        self.assertEqual(self.pipeline._get_min_order_notional(), 0.0)
        self.assertEqual(self.pipeline._get_min_buy_order_notional(), 0.0)
        self.assertEqual(result.position_action, "ADD")
        self.assertAlmostEqual(result.delta_amount, 10.0, places=2)

    def test_suppressed_hold_preserves_exact_fractional_legacy_quantity(self):
        calc = StockAnalysisPipeline._calculate_position_transition(
            existing=None,
            quantity=12.75,
            current_weight=0.1275,
            decision=SimpleNamespace(target_weight=0.13),
            cash=9000.0,
            total_value=10000.0,
            current_price=100.0,
            current_value=1275.0,
            min_order_notional=500.0,
        )
        self.assertIsNotNone(calc)
        self.assertEqual(calc["action"], "HOLD")
        self.assertEqual(calc["target_quantity"], 12.75)

    def test_suppressed_hold_keeps_accounting_fields_unchanged(self):
        calc = StockAnalysisPipeline._calculate_position_transition(
            existing=None,
            quantity=12.75,
            current_weight=0.1275,
            decision=SimpleNamespace(target_weight=0.13),
            cash=9000.0,
            total_value=10000.0,
            current_price=100.0,
            current_value=1275.0,
            min_order_notional=500.0,
        )
        self.assertIsNotNone(calc)
        self.assertEqual(calc["target_value"], 1275.0)
        self.assertEqual(calc["delta_amount"], 0.0)
        self.assertEqual(calc["cash_after"], 9000.0)


    def test_analyze_stock_defaults_to_read_only_position_management(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.db = self.db
        pipeline.config = SimpleNamespace(analysis_read_only=True, save_context_snapshot=False)
        pipeline.fetcher_manager = SimpleNamespace(
            get_realtime_quote=lambda code: None,
        )
        pipeline.trend_analyzer = MagicMock()
        pipeline.search_service = SimpleNamespace(is_available=False)
        pipeline.analyzer = MagicMock(return_value=None)
        pipeline.analyzer.analyze.return_value = self._result("RO1", final_decision="BUY")
        pipeline.save_context_snapshot = False

        with patch.object(pipeline, "_apply_position_management") as mock_apply, patch.object(
            pipeline, "_apply_validation_gate"
        ) as mock_validation:
            mock_validation.side_effect = lambda *, result, enhanced_context: setattr(result, "validation_status", "PASS")
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
        pipeline.config = SimpleNamespace(
            analysis_read_only=False,
            save_context_snapshot=False,
            execution_price_policy="realtime_if_available",
        )
        pipeline.fetcher_manager = SimpleNamespace(
            get_realtime_quote=lambda code: SimpleNamespace(name=f"股票{code}", price=100.0, change_pct=1.2),
        )
        pipeline.trend_analyzer = MagicMock()
        pipeline.search_service = SimpleNamespace(is_available=False)
        pipeline.analyzer = MagicMock()
        pipeline.analyzer.analyze.return_value = self._result("RW1", final_decision="BUY")
        pipeline.position_manager = PositionManager()
        pipeline.save_context_snapshot = False
        pipeline._now_for_testing = datetime(2026, 4, 29, 2, 0, 0)

        self.db.save_account_snapshot(snapshot_date=date.today(), cash=10000, equity_value=0, total_value=10000)

        with patch.object(pipeline, "_apply_decision_structure") as mock_decision, patch.object(
            pipeline, "_apply_validation_gate"
        ) as mock_validation:
            mock_decision.return_value = None
            mock_validation.side_effect = lambda *, result, enhanced_context: setattr(result, "validation_status", "PASS")
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

    def test_blocked_validation_preserves_existing_holding_weights(self):
        self.db.save_account_snapshot(snapshot_date=date.today(), cash=5000, equity_value=10000, total_value=15000)
        self.db.upsert_portfolio_position(
            code="BHP.AX",
            name="BHP",
            quantity=100,
            avg_cost=95,
            current_price=100,
            weight=10000 / 15000,
            market_value=10000,
        )

        result = AnalysisResult(
            code="BHP.AX",
            name="BHP",
            sentiment_score=68,
            trend_prediction="震荡",
            operation_advice="加仓",
            final_decision="BUY",
            position_action="ADD",
        )
        result.current_price = 100

        self.pipeline._apply_validation_gate(
            result=result,
            enhanced_context={
                "date": date.today().isoformat(),
                "today": {},
                "data_missing": True,
            },
        )

        self.assertEqual(result.validation_status, "BLOCK")
        self.assertAlmostEqual(result.current_weight, 10000 / 15000, places=4)
        self.assertAlmostEqual(result.target_weight, 10000 / 15000, places=4)
        self.assertEqual(result.target_quantity, 100.0)
        self.assertEqual(result.position_action, "HOLD")


if __name__ == "__main__":
    unittest.main()
