# -*- coding: utf-8 -*-
"""Integration tests for backtest service and repository.

These tests run against a temporary SQLite DB (same approach as other tests)
and validate idempotency/force semantics, result field correctness,
summary creation, and query methods.
"""

import os
import json
import tempfile
import unittest
from datetime import date, datetime
from unittest.mock import patch

from src.config import Config
from src.core.backtest_engine import OVERALL_SENTINEL_CODE
from src.services.backtest_service import BacktestService
from src.storage import AnalysisHistory, BacktestResult, BacktestSummary, DatabaseManager, StockDaily
from src.analyzer import AnalysisResult, GeminiAnalyzer


class BacktestServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self._db_path = os.path.join(self._temp_dir.name, "test_backtest_service.db")
        os.environ["DATABASE_PATH"] = self._db_path
        os.environ["BACKTEST_EVAL_WINDOW_DAYS"] = "3"

        Config._instance = None
        DatabaseManager.reset_instance()
        self.db = DatabaseManager.get_instance()

        # Ensure analysis is old enough for default min_age_days=14
        old_created_at = datetime(2024, 1, 1, 0, 0, 0)

        with self.db.get_session() as session:
            session.add(
                AnalysisHistory(
                    query_id="q1",
                    code="600519",
                    name="贵州茅台",
                    report_type="simple",
                    sentiment_score=80,
                    operation_advice="买入",
                    trend_prediction="看多",
                    analysis_summary="test",
                    alpha_decision="BUY",
                    final_decision="BUY",
                    position_action="OPEN",
                    target_weight=0.2,
                    current_weight=0.0,
                    delta_amount=2000.0,
                    stop_loss=95.0,
                    take_profit=110.0,
                    raw_result=json.dumps({"stop_loss": 95.0, "take_profit": 110.0}),
                    created_at=old_created_at,
                    context_snapshot='{"enhanced_context": {"date": "2024-01-01"}}',
                )
            )

            # Analysis day close
            session.add(
                StockDaily(
                    code="600519",
                    date=date(2024, 1, 1),
                    open=100.0,
                    high=101.0,
                    low=99.0,
                    close=100.0,
                )
            )

            # Forward bars (3 days) that hit take-profit on day1.
            # Jan 2 open is intentionally different from Jan 1 close to prove
            # backtests do not default to the analysis-day close as entry.
            session.add_all(
                [
                    StockDaily(code="600519", date=date(2024, 1, 2), open=103.0, high=111.0, low=100.0, close=105.0),
                    StockDaily(code="600519", date=date(2024, 1, 3), open=105.5, high=108.0, low=103.0, close=106.0),
                    StockDaily(code="600519", date=date(2024, 1, 4), open=106.5, high=109.0, low=104.0, close=107.0),
                ]
            )
            session.commit()

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        self._temp_dir.cleanup()

    def _count_results(self) -> int:
        with self.db.get_session() as session:
            return session.query(BacktestResult).count()

    def _add_backtest_bars(self, *, code: str, start_price: float = 100.0) -> None:
        with self.db.get_session() as session:
            session.add(StockDaily(code=code, date=date(2024, 1, 1), open=start_price, high=start_price + 1, low=start_price - 1, close=start_price))
            session.add_all([
                StockDaily(code=code, date=date(2024, 1, 2), open=start_price + 3, high=111.0, low=94.0, close=105.0),
                StockDaily(code=code, date=date(2024, 1, 3), open=105.5, high=108.0, low=96.0, close=106.0),
                StockDaily(code=code, date=date(2024, 1, 4), open=106.5, high=109.0, low=97.0, close=107.0),
            ])
            session.commit()

    def test_force_semantics(self) -> None:
        service = BacktestService(self.db)

        stats1 = service.run_backtest(code="600519", force=False, eval_window_days=3, min_age_days=0, limit=10)
        self.assertEqual(stats1["saved"], 1)
        self.assertEqual(self._count_results(), 1)

        # Non-force should be idempotent
        stats2 = service.run_backtest(code="600519", force=False, eval_window_days=3, min_age_days=0, limit=10)
        self.assertEqual(stats2["saved"], 0)
        self.assertEqual(self._count_results(), 1)

        # Force should replace existing result without unique constraint errors
        stats3 = service.run_backtest(code="600519", force=True, eval_window_days=3, min_age_days=0, limit=10)
        self.assertEqual(stats3["saved"], 1)
        self.assertEqual(self._count_results(), 1)

    def _run_and_get_result(self) -> BacktestResult:
        """Helper: run backtest and return the single BacktestResult row."""
        service = BacktestService(self.db)
        service.run_backtest(code="600519", force=False, eval_window_days=3, min_age_days=0, limit=10)
        with self.db.get_session() as session:
            return session.query(BacktestResult).one()

    def test_result_fields_correct(self) -> None:
        """Verify BacktestResult row contains correct evaluation values."""
        result = self._run_and_get_result()

        self.assertEqual(result.eval_status, "completed")
        self.assertEqual(result.code, "600519")
        self.assertEqual(result.analysis_date, date(2024, 1, 1))
        self.assertEqual(result.operation_advice, "买入")
        self.assertEqual(result.final_decision, "BUY")
        self.assertEqual(result.position_action, "OPEN")
        self.assertAlmostEqual(result.target_weight, 0.2)
        self.assertEqual(result.decision_source, "final_decision")
        self.assertEqual(result.position_recommendation, "long")
        self.assertEqual(result.direction_expected, "up")

        # Prices
        self.assertAlmostEqual(result.start_price, 103.0)
        self.assertAlmostEqual(result.end_close, 107.0)
        self.assertAlmostEqual(result.stock_return_pct, (107.0 - 103.0) / 103.0 * 100)

        # Direction & outcome
        self.assertEqual(result.outcome, "win")
        self.assertTrue(result.direction_correct)

        # Target hits -- day2 high=111 >= take_profit=110
        self.assertTrue(result.hit_take_profit)
        self.assertFalse(result.hit_stop_loss)
        self.assertEqual(result.first_hit, "take_profit")
        self.assertEqual(result.first_hit_trading_days, 1)
        self.assertEqual(result.first_hit_date, date(2024, 1, 2))

        # Simulated execution
        self.assertAlmostEqual(result.simulated_entry_price, 103.0)
        self.assertAlmostEqual(result.simulated_exit_price, 110.0)
        self.assertEqual(result.simulated_exit_reason, "take_profit")
        self.assertAlmostEqual(result.simulated_return_pct, (110.0 - 103.0) / 103.0 * 100)

    def test_saved_realtime_execution_price_wins_over_next_open(self) -> None:
        with self.db.get_session() as session:
            history = session.query(AnalysisHistory).filter(AnalysisHistory.code == "600519").one()
            history.raw_result = json.dumps(
                {"current_price": 101.0, "execution_price_source": "realtime"},
                ensure_ascii=False,
            )
            session.commit()

        result = self._run_and_get_result()

        self.assertEqual(result.eval_status, "completed")
        self.assertAlmostEqual(result.start_price, 101.0)
        self.assertAlmostEqual(result.simulated_entry_price, 101.0)

    def test_missing_next_open_marks_insufficient_data(self) -> None:
        with self.db.get_session() as session:
            session.add(
                AnalysisHistory(
                    query_id="q_missing_next_open",
                    code="300007",
                    name="Missing Open",
                    report_type="simple",
                    sentiment_score=70,
                    operation_advice="买入",
                    trend_prediction="看多",
                    analysis_summary="missing next open",
                    final_decision="BUY",
                    position_action="OPEN",
                    target_weight=0.2,
                    current_weight=0.0,
                    delta_amount=2000.0,
                    created_at=datetime(2024, 1, 1, 0, 0, 0),
                    context_snapshot='{"enhanced_context": {"date": "2024-01-01"}}',
                )
            )
            session.add(StockDaily(code="300007", date=date(2024, 1, 1), open=100.0, high=101.0, low=99.0, close=100.0))
            session.add_all([
                StockDaily(code="300007", date=date(2024, 1, 2), open=None, high=105.0, low=99.0, close=104.0),
                StockDaily(code="300007", date=date(2024, 1, 3), open=104.5, high=106.0, low=103.0, close=105.0),
                StockDaily(code="300007", date=date(2024, 1, 4), open=105.5, high=107.0, low=104.0, close=106.0),
            ])
            session.commit()

        service = BacktestService(self.db)
        with patch.object(service, "_try_fill_daily_data", return_value=None):
            stats = service.run_backtest(code="300007", force=False, eval_window_days=3, min_age_days=0, limit=10)

        self.assertEqual(stats["saved"], 1)
        self.assertEqual(stats["completed"], 0)
        self.assertEqual(stats["insufficient"], 1)
        with self.db.get_session() as session:
            row = session.query(BacktestResult).filter(BacktestResult.code == "300007").one()
            self.assertEqual(row.eval_status, "insufficient_data")
            self.assertIsNone(row.start_price)

    def test_missing_snapshot_date_does_not_fall_back_to_created_at(self) -> None:
        with self.db.get_session() as session:
            session.add(
                AnalysisHistory(
                    query_id="q_no_snapshot_date",
                    code="300008",
                    name="No Snapshot Date",
                    report_type="simple",
                    sentiment_score=70,
                    operation_advice="买入",
                    trend_prediction="看多",
                    analysis_summary="no snapshot date",
                    final_decision="BUY",
                    position_action="OPEN",
                    target_weight=0.2,
                    current_weight=0.0,
                    delta_amount=2000.0,
                    created_at=datetime(2024, 1, 1, 0, 0, 0),
                    context_snapshot=None,
                )
            )
            session.add(StockDaily(code="300008", date=date(2024, 1, 2), open=103.0, high=105.0, low=101.0, close=104.0))
            session.add(StockDaily(code="300008", date=date(2024, 1, 3), open=104.5, high=106.0, low=103.0, close=105.0))
            session.add(StockDaily(code="300008", date=date(2024, 1, 4), open=105.5, high=107.0, low=104.0, close=106.0))
            session.commit()

        service = BacktestService(self.db)
        stats = service.run_backtest(code="300008", force=False, eval_window_days=3, min_age_days=0, limit=10)

        self.assertEqual(stats["saved"], 1)
        self.assertEqual(stats["completed"], 0)
        self.assertEqual(stats["insufficient"], 1)
        self.assertEqual(stats["errors"], 0)
        with self.db.get_session() as session:
            row = session.query(BacktestResult).filter(BacktestResult.code == "300008").one()
            self.assertEqual(row.eval_status, "insufficient_data")
            self.assertIsNone(row.analysis_date)

    def test_summaries_created_after_run(self) -> None:
        """Verify both overall and per-stock BacktestSummary rows are created."""
        service = BacktestService(self.db)
        service.run_backtest(code="600519", force=False, eval_window_days=3, min_age_days=0, limit=10)

        with self.db.get_session() as session:
            # Overall summary uses sentinel code
            overall = session.query(BacktestSummary).filter(
                BacktestSummary.scope == "overall",
                BacktestSummary.code == OVERALL_SENTINEL_CODE,
            ).first()
            self.assertIsNotNone(overall)
            self.assertEqual(overall.total_evaluations, 1)
            self.assertEqual(overall.completed_count, 1)
            self.assertEqual(overall.win_count, 1)
            self.assertEqual(overall.loss_count, 0)
            self.assertAlmostEqual(overall.win_rate_pct, 100.0)

            # Stock-level summary
            stock = session.query(BacktestSummary).filter(
                BacktestSummary.scope == "stock",
                BacktestSummary.code == "600519",
            ).first()
            self.assertIsNotNone(stock)
            self.assertEqual(stock.total_evaluations, 1)
            self.assertEqual(stock.completed_count, 1)
            self.assertEqual(stock.win_count, 1)

    def test_get_summary_overall_returns_sentinel_as_none(self) -> None:
        """Verify get_summary translates __overall__ sentinel back to None."""
        service = BacktestService(self.db)
        service.run_backtest(code="600519", force=False, eval_window_days=3, min_age_days=0, limit=10)

        summary = service.get_summary(scope="overall", code=None)
        self.assertIsNotNone(summary)
        self.assertIsNone(summary["code"])
        self.assertEqual(summary["scope"], "overall")
        self.assertEqual(summary["win_count"], 1)

    def test_get_confidence_panel_uses_existing_summary_without_changing_backtests(self) -> None:
        """Verify report confidence panel is a read-only view over existing backtest rows."""
        service = BacktestService(self.db)
        service.run_backtest(code="600519", force=False, eval_window_days=3, min_age_days=0, limit=10)
        result_count_before = self._count_results()

        panel = service.get_confidence_panel(eval_window_days=3)

        self.assertEqual(self._count_results(), result_count_before)
        self.assertEqual(panel["overall"]["sample_size"], 1)
        self.assertEqual(panel["overall"]["window_days"], 3)
        self.assertEqual(panel["overall"]["win_rate_pct"], 100.0)
        self.assertEqual(panel["overall"]["confidence_level"], "low_sample")
        self.assertEqual(panel["by_action"]["OPEN"]["sample_size"], 1)
        self.assertEqual(panel["by_action"]["OPEN"]["win_rate_pct"], 100.0)

    def test_get_score_bucket_calibration_uses_existing_results_without_changing_backtests(self) -> None:
        """Verify score bucket calibration is a read-only view over existing backtest rows."""
        service = BacktestService(self.db)
        service.run_backtest(code="600519", force=False, eval_window_days=3, min_age_days=0, limit=10)
        result_count_before = self._count_results()

        calibration = service.get_score_bucket_calibration(eval_window_days=3)

        self.assertEqual(self._count_results(), result_count_before)
        self.assertEqual(calibration["80_100"]["sample_size"], 1)
        self.assertEqual(calibration["80_100"]["window_days"], 3)
        self.assertEqual(calibration["80_100"]["win_rate_pct"], 100.0)
        self.assertEqual(calibration["80_100"]["confidence_level"], "low_sample")
        self.assertEqual(calibration["60_70"]["sample_size"], 0)
        self.assertEqual(calibration["current_items"], [])

    def test_get_recent_evaluations(self) -> None:
        """Verify get_recent_evaluations returns correct paginated results."""
        service = BacktestService(self.db)
        service.run_backtest(code="600519", force=False, eval_window_days=3, min_age_days=0, limit=10)

        data = service.get_recent_evaluations(code="600519", limit=10, page=1)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["limit"], 10)
        self.assertEqual(len(data["items"]), 1)

        item = data["items"][0]
        self.assertEqual(item["code"], "600519")
        self.assertEqual(item["outcome"], "win")
        self.assertEqual(item["direction_expected"], "up")
        self.assertTrue(item["direction_correct"])
        self.assertEqual(item["decision_source"], "final_decision")

    def test_structured_fields_win_over_conflicting_legacy_operation_advice(self) -> None:
        old_created_at = datetime(2024, 1, 1, 0, 0, 0)
        with self.db.get_session() as session:
            session.add(
                AnalysisHistory(
                    query_id="q3",
                    code="300001",
                    name="特锐德",
                    report_type="simple",
                    sentiment_score=75,
                    operation_advice="买入",  # conflicts with structured SELL
                    trend_prediction="震荡",
                    analysis_summary="conflict",
                    alpha_decision="BUY",
                    final_decision="SELL",
                    position_action="CLOSE",
                    target_weight=0.0,
                    current_weight=0.3,
                    delta_amount=-3000.0,
                    stop_loss=None,
                    take_profit=None,
                    created_at=old_created_at,
                    context_snapshot='{"enhanced_context": {"date": "2024-01-01"}}',
                )
            )
            session.add(StockDaily(code="300001", date=date(2024, 1, 1), open=20.0, high=20.5, low=19.8, close=20.0))
            session.add_all([
                StockDaily(code="300001", date=date(2024, 1, 2), open=19.9, high=20.2, low=19.0, close=19.4),
                StockDaily(code="300001", date=date(2024, 1, 3), open=19.3, high=19.8, low=18.7, close=19.0),
                StockDaily(code="300001", date=date(2024, 1, 4), open=18.9, high=19.4, low=18.5, close=18.8),
            ])
            session.commit()

        service = BacktestService(self.db)
        stats = service.run_backtest(code="300001", force=False, eval_window_days=3, min_age_days=0, limit=10)
        self.assertEqual(stats["saved"], 1)
        with self.db.get_session() as session:
            row = session.query(BacktestResult).filter(BacktestResult.code == "300001").one()
            self.assertEqual(row.operation_advice, "买入")
            self.assertEqual(row.final_decision, "SELL")
            self.assertEqual(row.position_action, "CLOSE")
            self.assertEqual(row.decision_source, "final_decision")
            self.assertEqual(row.direction_expected, "down")
            self.assertEqual(row.position_recommendation, "cash")
            self.assertEqual(row.outcome, "win")

    def test_position_action_source_not_overridden_by_alpha_decision(self) -> None:
        old_created_at = datetime(2024, 1, 1, 0, 0, 0)
        with self.db.get_session() as session:
            session.add(
                AnalysisHistory(
                    query_id="q4",
                    code="300002",
                    name="神州泰岳",
                    report_type="simple",
                    sentiment_score=65,
                    operation_advice="买入",
                    trend_prediction="震荡",
                    analysis_summary="action_source",
                    alpha_decision="BUY",
                    final_decision=None,
                    position_action="CLOSE",
                    target_weight=0.0,
                    current_weight=0.25,
                    delta_amount=-2500.0,
                    stop_loss=None,
                    take_profit=None,
                    created_at=old_created_at,
                    context_snapshot='{"enhanced_context": {"date": "2024-01-01"}}',
                )
            )
            session.add(StockDaily(code="300002", date=date(2024, 1, 1), open=15.0, high=15.3, low=14.9, close=15.0))
            session.add_all([
                StockDaily(code="300002", date=date(2024, 1, 2), open=15.1, high=15.2, low=14.7, close=14.9),
                StockDaily(code="300002", date=date(2024, 1, 3), open=14.9, high=15.0, low=14.5, close=14.8),
                StockDaily(code="300002", date=date(2024, 1, 4), open=14.8, high=14.9, low=14.3, close=14.6),
            ])
            session.commit()

        service = BacktestService(self.db)
        stats = service.run_backtest(code="300002", force=False, eval_window_days=3, min_age_days=0, limit=10)
        self.assertEqual(stats["saved"], 1)
        with self.db.get_session() as session:
            row = session.query(BacktestResult).filter(BacktestResult.code == "300002").one()
            self.assertEqual(row.decision_source, "position_action")
            self.assertEqual(row.position_recommendation, "cash")

    def test_ai_sniper_text_is_not_saved_as_backtest_parameters(self) -> None:
        result = AnalysisResult(
            code="300003",
            name="东方财富",
            sentiment_score=70,
            trend_prediction="看多",
            operation_advice="持有",
            analysis_summary="sniper text only",
        )
        result.dashboard = {
            "battle_plan": {
                "sniper_points": {
                    "ideal_buy": "MA5 10.1，MA10 9.8，理想买点 12.3 元",
                    "stop_loss": "若跌破 MA10 或 11.1 元止损",
                    "take_profit": "第一目标 13.5 元，第二目标 14.2 元",
                }
            }
        }

        saved = self.db.save_analysis_history(
            result=result,
            query_id="q_ai_sniper_text",
            report_type="simple",
            news_content=None,
            context_snapshot={"enhanced_context": {"date": "2024-01-01"}},
        )

        self.assertEqual(saved, 1)
        with self.db.get_session() as session:
            row = session.query(AnalysisHistory).filter(AnalysisHistory.query_id == "q_ai_sniper_text").one()
            self.assertIsNone(row.ideal_buy)
            self.assertIsNone(row.stop_loss)
            self.assertIsNone(row.take_profit)

    def test_legacy_prose_derived_levels_are_ignored_without_raw_result_provenance(self) -> None:
        with self.db.get_session() as session:
            session.add(
                AnalysisHistory(
                    query_id="q_legacy_levels",
                    code="300004",
                    name="Legacy",
                    report_type="simple",
                    sentiment_score=75,
                    operation_advice="买入",
                    trend_prediction="看多",
                    analysis_summary="legacy levels",
                    final_decision="BUY",
                    position_action="OPEN",
                    target_weight=0.2,
                    current_weight=0.0,
                    delta_amount=2000.0,
                    stop_loss=95.0,
                    take_profit=110.0,
                    raw_result=json.dumps(
                        {
                            "dashboard": {
                                "battle_plan": {
                                    "sniper_points": {
                                        "stop_loss": "止损位：95元",
                                        "take_profit": "目标位：110元",
                                    }
                                }
                            }
                        },
                        ensure_ascii=False,
                    ),
                    created_at=datetime(2024, 1, 1, 0, 0, 0),
                    context_snapshot='{"enhanced_context": {"date": "2024-01-01"}}',
                )
            )
            session.commit()
        self._add_backtest_bars(code="300004")

        service = BacktestService(self.db)
        stats = service.run_backtest(code="300004", force=False, eval_window_days=3, min_age_days=0, limit=10)

        self.assertEqual(stats["saved"], 1)
        with self.db.get_session() as session:
            row = session.query(BacktestResult).filter(BacktestResult.code == "300004").one()
            self.assertIsNone(row.stop_loss)
            self.assertIsNone(row.take_profit)
            self.assertIsNone(row.hit_stop_loss)
            self.assertIsNone(row.hit_take_profit)
            self.assertEqual(row.first_hit, "neither")
            self.assertEqual(row.simulated_exit_reason, "window_end")

    def test_structured_raw_result_numeric_levels_are_used_for_backtest(self) -> None:
        with self.db.get_session() as session:
            session.add(
                AnalysisHistory(
                    query_id="q_structured_levels",
                    code="300005",
                    name="Structured",
                    report_type="simple",
                    sentiment_score=75,
                    operation_advice="买入",
                    trend_prediction="看多",
                    analysis_summary="structured levels",
                    final_decision="BUY",
                    position_action="OPEN",
                    target_weight=0.2,
                    current_weight=0.0,
                    delta_amount=2000.0,
                    stop_loss=91.0,
                    take_profit=115.0,
                    raw_result=json.dumps({"ideal_buy": 99.0, "stop_loss": 95.0, "take_profit": 110.0}),
                    created_at=datetime(2024, 1, 1, 0, 0, 0),
                    context_snapshot='{"enhanced_context": {"date": "2024-01-01"}}',
                )
            )
            session.commit()
        self._add_backtest_bars(code="300005")

        service = BacktestService(self.db)
        stats = service.run_backtest(code="300005", force=False, eval_window_days=3, min_age_days=0, limit=10)

        self.assertEqual(stats["saved"], 1)
        with self.db.get_session() as session:
            row = session.query(BacktestResult).filter(BacktestResult.code == "300005").one()
            self.assertEqual(row.stop_loss, 95.0)
            self.assertEqual(row.take_profit, 110.0)
            self.assertTrue(row.hit_take_profit)
            self.assertEqual(row.first_hit, "ambiguous")
            self.assertEqual(row.simulated_exit_reason, "ambiguous_stop_loss")

    def test_parse_save_backtest_uses_numeric_top_level_levels(self) -> None:
        payload = {
            "stock_name": "Structured Parse",
            "sentiment_score": 75,
            "operation_advice": "观望",
            "trend_prediction": "看多",
            "confidence_level": "中",
            "analysis_summary": "structured parse levels",
            "risk_warning": "控制风险",
            "ideal_buy": 99.0,
            "stop_loss": 95.0,
            "take_profit": 110.0,
        }
        result = GeminiAnalyzer(api_key=None)._parse_response(
            json.dumps(payload, ensure_ascii=False),
            "300006",
            "Structured Parse",
        )
        result.final_decision = "BUY"
        result.position_action = "OPEN"
        result.target_weight = 0.2
        result.current_weight = 0.0
        result.delta_amount = 2000.0

        self.assertEqual(result.ideal_buy, 99.0)
        self.assertEqual(result.stop_loss, 95.0)
        self.assertEqual(result.take_profit, 110.0)

        saved = self.db.save_analysis_history(
            result=result,
            query_id="q_parse_structured_levels",
            report_type="simple",
            news_content=None,
            context_snapshot={"enhanced_context": {"date": "2024-01-01"}},
        )
        self.assertEqual(saved, 1)
        self._add_backtest_bars(code="300006")

        service = BacktestService(self.db)
        stats = service.run_backtest(code="300006", force=False, eval_window_days=3, min_age_days=0, limit=10)

        self.assertEqual(stats["saved"], 1)
        with self.db.get_session() as session:
            history = session.query(AnalysisHistory).filter(AnalysisHistory.query_id == "q_parse_structured_levels").one()
            raw_result = json.loads(history.raw_result)
            self.assertEqual(history.ideal_buy, 99.0)
            self.assertEqual(history.stop_loss, 95.0)
            self.assertEqual(history.take_profit, 110.0)
            self.assertEqual(raw_result["ideal_buy"], 99.0)
            self.assertEqual(raw_result["stop_loss"], 95.0)
            self.assertEqual(raw_result["take_profit"], 110.0)

            row = session.query(BacktestResult).filter(BacktestResult.code == "300006").one()
            self.assertEqual(row.stop_loss, 95.0)
            self.assertEqual(row.take_profit, 110.0)
            self.assertTrue(row.hit_take_profit)

    def test_structured_backtest_levels_reject_non_numeric_values(self) -> None:
        levels = BacktestService._extract_structured_backtest_levels(
            type(
                "Analysis",
                (),
                {
                    "raw_result": json.dumps(
                        {
                            "ideal_buy": "99.0",
                            "secondary_buy": True,
                            "stop_loss": float("nan"),
                            "take_profit": float("inf"),
                            "dashboard": {
                                "battle_plan": {
                                    "sniper_points": {
                                        "stop_loss": "止损位：95元",
                                        "take_profit": "目标位：110元",
                                    }
                                }
                            },
                        }
                    )
                },
            )()
        )

        self.assertIsNone(levels["ideal_buy"])
        self.assertIsNone(levels["stop_loss"])
        self.assertIsNone(levels["take_profit"])

    def test_multi_stock_summaries(self) -> None:
        """Verify separate summaries for multiple stocks + correct overall aggregate."""
        old_created_at = datetime(2024, 1, 1, 0, 0, 0)

        with self.db.get_session() as session:
            # Second stock with sell advice -- price drops (win for cash/down)
            session.add(
                AnalysisHistory(
                    query_id="q2",
                    code="000001",
                    name="平安银行",
                    report_type="simple",
                    sentiment_score=30,
                    operation_advice="卖出",
                    trend_prediction="看空",
                    analysis_summary="test2",
                    stop_loss=None,
                    take_profit=None,
                    created_at=old_created_at,
                    context_snapshot='{"enhanced_context": {"date": "2024-01-01"}}',
                )
            )
            session.add(
                StockDaily(code="000001", date=date(2024, 1, 1), open=10.0, high=10.2, low=9.8, close=10.0)
            )
            session.add_all([
                StockDaily(code="000001", date=date(2024, 1, 2), open=9.9, high=10.0, low=9.5, close=9.6),
                StockDaily(code="000001", date=date(2024, 1, 3), open=9.5, high=9.7, low=9.3, close=9.4),
                StockDaily(code="000001", date=date(2024, 1, 4), open=9.4, high=9.5, low=9.0, close=9.1),
            ])
            session.commit()

        service = BacktestService(self.db)
        stats = service.run_backtest(code=None, force=False, eval_window_days=3, min_age_days=0, limit=10)
        self.assertEqual(stats["saved"], 2)
        self.assertEqual(stats["completed"], 2)

        with self.db.get_session() as session:
            # Each stock has its own summary
            s1 = session.query(BacktestSummary).filter(
                BacktestSummary.scope == "stock", BacktestSummary.code == "600519"
            ).first()
            s2 = session.query(BacktestSummary).filter(
                BacktestSummary.scope == "stock", BacktestSummary.code == "000001"
            ).first()
            self.assertIsNotNone(s1)
            self.assertIsNotNone(s2)
            self.assertEqual(s1.win_count, 1)
            self.assertEqual(s2.win_count, 1)

            # Overall aggregates both
            overall = session.query(BacktestSummary).filter(
                BacktestSummary.scope == "overall",
                BacktestSummary.code == OVERALL_SENTINEL_CODE,
            ).first()
            self.assertIsNotNone(overall)
            self.assertEqual(overall.total_evaluations, 2)
            self.assertEqual(overall.completed_count, 2)
            self.assertEqual(overall.win_count, 2)


if __name__ == "__main__":
    unittest.main()
