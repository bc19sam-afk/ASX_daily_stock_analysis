# -*- coding: utf-8 -*-

import os
import tempfile
import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch

from src.analyzer import AnalysisResult
from src.core.pipeline import StockAnalysisPipeline
from src.notification import NotificationService
from src.services.paper_portfolio_service import PaperPortfolioService
from src.storage import (
    AccountSnapshot,
    DatabaseManager,
    PaperPortfolioHolding,
    PaperPortfolioSnapshot,
    PaperPortfolioState,
    PaperPortfolioTrade,
)


class PaperPortfolioServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        DatabaseManager.reset_instance()
        self.db = DatabaseManager(db_url=f"sqlite:///{os.path.join(self.tmp.name, 'paper_portfolio.db')}")
        self.service = PaperPortfolioService(self.db)

        self.db.upsert_portfolio_position(
            code="AAA",
            name="AAA",
            quantity=10,
            avg_cost=10,
            current_price=10,
            weight=0.5,
            market_value=100,
        )
        self.db.save_account_snapshot(
            snapshot_date=date.today(),
            cash=100,
            equity_value=100,
            total_value=200,
            note="real_init",
        )

    def tearDown(self):
        DatabaseManager.reset_instance()
        self.tmp.cleanup()

    def _paper_table_counts(self):
        with self.db.get_session() as session:
            return {
                "state": session.query(PaperPortfolioState).count(),
                "holdings": session.query(PaperPortfolioHolding).count(),
                "snapshots": session.query(PaperPortfolioSnapshot).count(),
                "trades": session.query(PaperPortfolioTrade).count(),
            }

    def test_init_from_current_copies_real_without_mutating_real(self):
        real_before = self.db.get_portfolio_overview()
        paper = self.service.init_from_current()

        real_after = self.db.get_portfolio_overview()
        self.assertEqual(real_before["cash"], real_after["cash"])
        self.assertEqual(real_before["total_value"], real_after["total_value"])
        self.assertEqual(len(real_after["holdings"]), 1)

        self.assertTrue(paper["initialized"])
        self.assertEqual(paper["cash"], real_before["cash"])
        self.assertEqual(paper["total_value"], real_before["total_value"])

    def test_dashboard_report_reads_paper_portfolio_without_writing_state(self):
        before = self._paper_table_counts()
        service = NotificationService.__new__(NotificationService)
        service._report_summary_only = True
        service._report_timezone = "Australia/Sydney"
        service._last_daily_decision_summary = None
        result = AnalysisResult(
            code="AAA",
            name="AAA",
            sentiment_score=50,
            trend_prediction="震荡",
            operation_advice="观察",
            final_decision="HOLD",
            position_action="HOLD",
            current_weight=0.5,
            target_weight=0.5,
            delta_amount=0.0,
            market_snapshot={"date": "2026-05-15", "close": "10.00", "source": "yfinance"},
        )

        with patch("src.notification.get_db", return_value=self.db):
            report = service.generate_dashboard_report([result], report_date="2026-05-18")

        after = self._paper_table_counts()
        self.assertEqual(before, after)
        self.assertIn("## 模拟盘账本（只读）", report)
        self.assertIn("状态：未初始化/未启用", report)
        self.assertIn("不会初始化模拟盘，也不会写入任何模拟交易", report)

    def test_apply_only_affects_paper_portfolio(self):
        self.service.init_from_current()
        real_before = self.db.get_portfolio_overview()

        self.service.apply_analysis_results([
            {"code": "AAA", "position_action": "CLOSE", "analysis_status": "OK", "current_price": 10.0}
        ])

        real_after = self.db.get_portfolio_overview()
        self.assertEqual(real_before["cash"], real_after["cash"])
        self.assertEqual(real_before["total_value"], real_after["total_value"])

    def test_failed_and_degraded_are_not_executed(self):
        self.service.init_from_current()
        overview = self.service.apply_analysis_results([
            {"code": "AAA", "position_action": "CLOSE", "analysis_status": "FAILED", "current_price": 10.0},
            {"code": "AAA", "position_action": "CLOSE", "analysis_status": "DEGRADED", "current_price": 10.0},
        ])
        holding = next(x for x in overview["holdings"] if x["code"] == "AAA")
        self.assertEqual(holding["quantity"], 10.0)
        self.assertTrue(all(not t["executed"] for t in overview["latest_simulated_trades"][:2]))

    def test_hold_action_is_not_executed(self):
        self.service.init_from_current()
        overview = self.service.apply_analysis_results([
            {"code": "AAA", "position_action": "HOLD", "analysis_status": "OK", "current_price": 10.0}
        ])
        holding = next(x for x in overview["holdings"] if x["code"] == "AAA")
        self.assertEqual(holding["quantity"], 10.0)
        self.assertFalse(overview["latest_simulated_trades"][0]["executed"])

    def test_open_add_reduce_close_update_holdings_cash_and_trades(self):
        self.service.init_from_current()
        overview = self.service.apply_analysis_results([
            {"code": "BBB", "position_action": "OPEN", "analysis_status": "OK", "current_price": 5.0, "target_quantity": 4},
            {"code": "AAA", "position_action": "ADD", "analysis_status": "OK", "current_price": 10.0, "target_quantity": 12},
            {"code": "AAA", "position_action": "REDUCE", "analysis_status": "OK", "current_price": 10.0, "target_quantity": 7},
            {"code": "BBB", "position_action": "CLOSE", "analysis_status": "OK", "current_price": 5.0},
        ])
        holdings = {h["code"]: h for h in overview["holdings"]}
        self.assertEqual(holdings["AAA"]["quantity"], 7.0)
        self.assertNotIn("BBB", holdings)
        self.assertEqual(overview["cash"], 130.0)
        executed = [t for t in overview["latest_simulated_trades"] if t["executed"]]
        self.assertGreaterEqual(len(executed), 4)

    def test_overview_includes_operation_deltas_and_pnl(self):
        self.service.init_from_current()
        self.service.apply_analysis_results(
            [
                {"code": "AAA", "position_action": "HOLD", "analysis_status": "OK", "current_price": 12.0},
            ],
            simulation_time=datetime(2099, 5, 21, 8, 0, 0),
        )
        overview = self.service.apply_analysis_results(
            [
                {"code": "AAA", "position_action": "REDUCE", "analysis_status": "OK", "current_price": 12.0, "target_quantity": 5},
            ],
            simulation_time=datetime(2099, 5, 22, 8, 0, 0),
        )

        holding = next(x for x in overview["holdings"] if x["code"] == "AAA")
        self.assertEqual(overview["initial_total_value"], 200.0)
        self.assertEqual(overview["total_pnl"], 20.0)
        self.assertEqual(overview["unrealized_pnl"], 10.0)
        self.assertEqual(overview["realized_pnl"], 10.0)
        self.assertEqual(holding["unrealized_pnl"], 10.0)
        self.assertEqual(holding["unrealized_pnl_pct"], 20.0)

        latest_trade = overview["latest_simulated_trades"][0]
        self.assertTrue(latest_trade["executed"])
        self.assertEqual(latest_trade["quantity_delta"], -5.0)
        self.assertEqual(latest_trade["cash_delta"], 60.0)
        self.assertEqual(latest_trade["notional"], 60.0)

    def test_pipeline_auto_applies_paper_portfolio_once_before_report(self):
        self.service.init_from_current()
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.db = self.db
        pipeline.config = SimpleNamespace(
            paper_portfolio_auto_apply=True,
            market_timezone="Australia/Sydney",
        )
        result = AnalysisResult(
            code="AAA",
            name="AAA",
            sentiment_score=50,
            trend_prediction="震荡",
            operation_advice="减仓",
            final_decision="SELL",
            position_action="REDUCE",
            current_weight=0.5,
            target_weight=0.25,
            delta_amount=-50.0,
            current_price=12.0,
            market_snapshot={"date": "2026-05-22", "close": "12.00", "source": "fixture"},
        )

        first = pipeline._apply_paper_portfolio_simulation(
            [result],
            simulation_time=datetime(2026, 5, 22, 8, 0, 0),
        )
        second = pipeline._apply_paper_portfolio_simulation(
            [result],
            simulation_time=datetime(2026, 5, 22, 9, 0, 0),
        )

        self.assertTrue(first)
        self.assertFalse(second)
        overview = self.db.get_paper_portfolio_overview()
        self.assertEqual(len(overview["latest_simulated_trades"]), 1)
        self.assertEqual(overview["latest_simulated_trades"][0]["action"], "REDUCE")

    def test_missing_price_is_skipped_with_reason(self):
        self.service.init_from_current()
        overview = self.service.apply_analysis_results([
            {"code": "AAA", "position_action": "REDUCE", "analysis_status": "OK", "target_quantity": 8}
        ])
        self.assertIn("invalid current price", overview["latest_simulated_trades"][0]["reason"])
        holding = next(x for x in overview["holdings"] if x["code"] == "AAA")
        self.assertEqual(holding["quantity"], 10.0)

    def test_reinit_rejected_without_force_and_allowed_with_force(self):
        first = self.service.init_from_current(force=False)
        self.assertTrue(first["initialized"])

        with self.assertRaises(ValueError):
            self.service.init_from_current(force=False)

        self.db.save_account_snapshot(
            snapshot_date=date.today(),
            cash=150,
            equity_value=100,
            total_value=250,
            note="real_changed",
        )
        forced = self.service.init_from_current(force=True)
        self.assertEqual(forced["cash"], 150.0)

    def test_insufficient_cash_buy_is_skipped_and_cash_never_negative(self):
        self.service.init_from_current()
        overview = self.service.apply_analysis_results([
            {
                "code": "BBB",
                "position_action": "OPEN",
                "analysis_status": "OK",
                "current_price": 10.0,
                "target_quantity": 50,  # 500 > current cash 100
            }
        ])
        self.assertGreaterEqual(overview["cash"], 0.0)
        self.assertEqual(overview["cash"], 100.0)
        self.assertEqual(len([h for h in overview["holdings"] if h["code"] == "BBB"]), 0)
        self.assertIn("insufficient cash", overview["latest_simulated_trades"][0]["reason"])
        self.assertFalse(overview["latest_simulated_trades"][0]["executed"])

    def test_legacy_asx_alias_add_uses_existing_paper_holding_not_new_symbol(self):
        self.service.init_from_current()
        with self.db.get_session() as session:
            row = session.query(PaperPortfolioHolding).filter(PaperPortfolioHolding.code == "AAA").first()
            row.code = "NHF.ASX"
            row.name = "NHF"
            row.quantity = 308.0
            row.avg_cost = 6.59
            row.current_price = 6.58
            row.market_value = 2026.64
            row.status = "OPEN"
            latest = session.query(PaperPortfolioSnapshot).order_by(
                PaperPortfolioSnapshot.snapshot_date.desc(),
                PaperPortfolioSnapshot.created_at.desc(),
            ).first()
            latest.cash = 1565.18
            latest.equity_value = 2026.64
            latest.total_value = 3591.82
            session.commit()

        overview = self.service.apply_analysis_results([
            {
                "code": "NHF.AX",
                "position_action": "ADD",
                "analysis_status": "OK",
                "current_price": 6.85,
                "target_quantity": 313,
                "target_weight": 0.1955,
                "delta_amount": 34.25,
            }
        ])

        holdings = {item["code"]: item for item in overview["holdings"]}
        self.assertIn("NHF.AX", holdings)
        self.assertNotIn("NHF.ASX", holdings)
        self.assertEqual(float(holdings["NHF.AX"]["quantity"]), 313.0)
        self.assertEqual(float(overview["latest_simulated_trades"][0]["quantity_delta"]), 5.0)
        self.assertTrue(overview["latest_simulated_trades"][0]["executed"])

    def test_paper_trade_reason_keeps_cash_diagnostics_for_report(self):
        self.service.init_from_current()
        overview = self.service.apply_analysis_results([
            {
                "code": "BBB",
                "position_action": "OPEN",
                "analysis_status": "OK",
                "current_price": 10.0,
                "target_quantity": 50,
                "delta_amount": 25.0,
            }
        ])

        trade = overview["latest_simulated_trades"][0]
        self.assertFalse(trade["executed"])
        self.assertEqual(trade["required_cash"], 500.0)
        self.assertEqual(trade["available_cash"], 100.0)

    def test_paper_report_normalizes_alias_and_explains_cash_skip(self):
        service = NotificationService.__new__(NotificationService)
        service._report_summary_only = False
        service._report_timezone = "Australia/Sydney"
        service._last_daily_decision_summary = None
        overview = {
            "available": True,
            "initialized": True,
            "snapshot_date": "2026-05-26",
            "cash": 1565.18,
            "equity_value": 2026.64,
            "total_value": 3591.82,
            "total_pnl": -1088.16,
            "total_pnl_pct": -9.92,
            "unrealized_pnl": -724.41,
            "realized_pnl": -363.75,
            "holdings": [
                {
                    "code": "NHF.ASX",
                    "quantity": 308.0,
                    "avg_cost": 6.59,
                    "current_price": 6.58,
                    "market_value": 2026.64,
                    "unrealized_pnl": -3.0,
                    "unrealized_pnl_pct": -0.15,
                }
            ],
            "latest_simulated_trades": [
                {
                    "simulation_time": "2026-05-26T09:34:42",
                    "code": "NHF.ASX",
                    "action": "ADD",
                    "executed": False,
                    "quantity_delta": 0.0,
                    "price": 6.85,
                    "cash_delta": 0.0,
                    "reason": "Skipped: insufficient cash for target quantity (required=2109.80, available=1565.18)",
                    "required_cash": 2109.8,
                    "available_cash": 1565.18,
                }
            ],
            "last_simulation_time": "2026-05-26T09:34:42",
        }

        report = "\n".join(
            service._build_paper_portfolio_readonly_lines(
                overview,
                has_plan_actions=True,
                report_date="2026-05-26",
            )
        )

        assert "NHF.AX" in report
        assert "NHF.ASX" not in report
        assert "现金不足：目标数量需要 2,109.80，可用现金 1,565.18，跳过" in report

    def test_paper_report_keeps_tiny_existing_open_but_marks_it_as_noise(self):
        service = NotificationService.__new__(NotificationService)
        service._report_summary_only = False
        service._report_timezone = "Australia/Sydney"
        service._last_daily_decision_summary = None
        overview = {
            "available": True,
            "initialized": True,
            "snapshot_date": "2026-05-27",
            "cash": 1564.52,
            "equity_value": 8408.35,
            "total_value": 9972.87,
            "total_pnl": -993.11,
            "total_pnl_pct": -9.06,
            "unrealized_pnl": -629.36,
            "realized_pnl": -363.75,
            "holdings": [
                {
                    "code": "IPH.AX",
                    "quantity": 8.11,
                    "avg_cost": 3.81,
                    "current_price": 3.81,
                    "market_value": 30.92,
                    "unrealized_pnl": 0.0,
                    "unrealized_pnl_pct": 0.0,
                }
            ],
            "latest_simulated_trades": [
                {
                    "simulation_time": "2026-05-27T09:36:40",
                    "code": "IPH.AX",
                    "action": "OPEN",
                    "executed": True,
                    "before_quantity": 8.02,
                    "after_quantity": 8.11,
                    "quantity_delta": 0.09,
                    "price": 3.81,
                    "cash_delta": -0.34,
                    "reason": "Applied",
                }
            ],
            "last_simulation_time": "2026-05-27T09:36:40",
        }

        report = "\n".join(
            service._build_paper_portfolio_readonly_lines(
                overview,
                has_plan_actions=True,
                report_date="2026-05-27",
            )
        )

        assert "已有仓位微调/补齐目标" in report
        assert "低于有效交易阈值，仅账本微调/目标同步" in report
        assert "| IPH.AX | 新开仓 |" not in report

    def test_malformed_target_payload_is_skipped_without_crash(self):
        self.service.init_from_current()
        overview = self.service.apply_analysis_results([
            {
                "code": "AAA",
                "position_action": "ADD",
                "analysis_status": "OK",
                "current_price": 10.0,
                "target_weight": "abc",
            },
            {
                "code": "AAA",
                "position_action": "HOLD",
                "analysis_status": "OK",
                "current_price": 10.0,
            },
        ])
        self.assertEqual(overview["cash"], 100.0)
        holding = next(x for x in overview["holdings"] if x["code"] == "AAA")
        self.assertEqual(holding["quantity"], 10.0)
        reasons = [t["reason"] for t in overview["latest_simulated_trades"][:2]]
        self.assertTrue(any("missing/invalid target info" in str(r) for r in reasons))

    def test_target_weight_uses_updated_portfolio_value_after_previous_trade(self):
        self.service.init_from_current()
        overview = self.service.apply_analysis_results([
            # First trade updates total value from 200 to 300 by repricing/executing AAA at 20.
            {"code": "AAA", "position_action": "REDUCE", "analysis_status": "OK", "current_price": 20.0, "target_quantity": 5},
            # Second trade must use updated total_value=300, so target qty should be 15 shares.
            {"code": "BBB", "position_action": "OPEN", "analysis_status": "OK", "current_price": 10.0, "target_weight": 0.5},
        ])
        holdings = {h["code"]: h for h in overview["holdings"]}
        self.assertEqual(holdings["AAA"]["quantity"], 5.0)
        self.assertEqual(holdings["BBB"]["quantity"], 15.0)
        self.assertEqual(overview["cash"], 50.0)

    def test_zero_delta_after_clamp_is_logged_as_noop_not_executed(self):
        self.service.init_from_current()
        overview = self.service.apply_analysis_results([
            # REDUCE but target is above current, so it is clamped to current qty => delta=0.
            {"code": "AAA", "position_action": "REDUCE", "analysis_status": "OK", "current_price": 10.0, "target_quantity": 15},
        ])
        trade = overview["latest_simulated_trades"][0]
        self.assertFalse(trade["executed"])
        self.assertIn("no-op", str(trade["reason"]).lower())
        holding = next(x for x in overview["holdings"] if x["code"] == "AAA")
        self.assertEqual(holding["quantity"], 10.0)

    def test_snapshot_matches_holdings_after_open_trade(self):
        self.service.init_from_current()
        overview = self.service.apply_analysis_results([
            {"code": "BBB", "position_action": "OPEN", "analysis_status": "OK", "current_price": 5.0, "target_quantity": 4},
        ])

        holdings = overview["holdings"]
        equity_from_holdings = round(sum(float(h["market_value"]) for h in holdings), 2)
        total_from_holdings = round(float(overview["cash"]) + equity_from_holdings, 2)

        with self.db.get_session() as session:
            latest_snapshot = session.query(PaperPortfolioSnapshot).order_by(
                PaperPortfolioSnapshot.snapshot_date.desc(),
                PaperPortfolioSnapshot.created_at.desc(),
            ).first()

        self.assertIsNotNone(latest_snapshot)
        self.assertAlmostEqual(float(latest_snapshot.cash), float(overview["cash"]), places=2)
        self.assertAlmostEqual(float(latest_snapshot.equity_value), equity_from_holdings, places=2)
        self.assertAlmostEqual(float(latest_snapshot.total_value), total_from_holdings, places=2)

    def test_nan_and_inf_price_are_skipped_as_invalid(self):
        self.service.init_from_current()
        overview = self.service.apply_analysis_results([
            {"code": "BBB", "position_action": "OPEN", "analysis_status": "OK", "current_price": "nan", "target_quantity": 3},
            {"code": "CCC", "position_action": "OPEN", "analysis_status": "OK", "current_price": "inf", "target_quantity": 3},
        ])

        self.assertEqual(len([h for h in overview["holdings"] if h["code"] in {"BBB", "CCC"}]), 0)
        latest_two = overview["latest_simulated_trades"][:2]
        self.assertTrue(all(not t["executed"] for t in latest_two))
        self.assertTrue(all("invalid current price" in str(t["reason"]).lower() for t in latest_two))

    def test_existing_holding_target_weight_uses_repriced_current_symbol(self):
        self.service.init_from_current()
        overview = self.service.apply_analysis_results([
            # AAA is existing holding. Reprice from 10 -> 20, then target_weight 0.5 should land near 5 shares.
            {"code": "AAA", "position_action": "REDUCE", "analysis_status": "OK", "current_price": 20.0, "target_weight": 0.5},
        ])
        holding = next(x for x in overview["holdings"] if x["code"] == "AAA")
        # total value for target calc should be cash(100)+repriced AAA(200)=300; 50% => 150 => qty 7.5 at 20.
        self.assertAlmostEqual(float(holding["quantity"]), 7.5, places=6)

    def test_duplicate_symbol_in_same_batch_uses_latest_quantity(self):
        self.service.init_from_current()
        overview = self.service.apply_analysis_results([
            {"code": "BBB", "position_action": "OPEN", "analysis_status": "OK", "current_price": 10.0, "target_quantity": 2},
            {"code": "BBB", "position_action": "ADD", "analysis_status": "OK", "current_price": 10.0, "target_quantity": 5},
        ])
        holdings = {h["code"]: h for h in overview["holdings"]}
        self.assertEqual(float(holdings["BBB"]["quantity"]), 5.0)
        # cash: 100 - (2*10) - (3*10) = 50
        self.assertEqual(float(overview["cash"]), 50.0)

    def test_non_finite_target_values_are_skipped_without_crash(self):
        self.service.init_from_current()
        overview = self.service.apply_analysis_results([
            {"code": "BBB", "position_action": "OPEN", "analysis_status": "OK", "current_price": 10.0, "target_quantity": "nan"},
            {"code": "CCC", "position_action": "OPEN", "analysis_status": "OK", "current_price": 10.0, "target_weight": "inf"},
            {"code": "DDD", "position_action": "OPEN", "analysis_status": "OK", "current_price": 10.0, "target_quantity": float("nan")},
            {"code": "EEE", "position_action": "OPEN", "analysis_status": "OK", "current_price": 10.0, "target_weight": float("inf")},
        ])
        self.assertEqual(len([h for h in overview["holdings"] if h["code"] in {"BBB", "CCC", "DDD", "EEE"}]), 0)
        latest_four = overview["latest_simulated_trades"][:4]
        self.assertTrue(all(not t["executed"] for t in latest_four))
        self.assertTrue(all("missing/invalid target info" in str(t["reason"]).lower() for t in latest_four))

    def test_hold_reprices_then_target_weight_uses_updated_working_value(self):
        self.service.init_from_current()
        overview = self.service.apply_analysis_results([
            {"code": "AAA", "position_action": "HOLD", "analysis_status": "OK", "current_price": 20.0},
            {"code": "AAA", "position_action": "REDUCE", "analysis_status": "OK", "current_price": 20.0, "target_weight": 0.5},
        ])
        holding = next(x for x in overview["holdings"] if x["code"] == "AAA")
        # HOLD reprices AAA to market_value=200, so total=300 and 50% target => qty 7.5 at price 20.
        self.assertAlmostEqual(float(holding["quantity"]), 7.5, places=6)

    def test_repeated_symbol_actions_apply_on_latest_quantity_price_and_market_value(self):
        self.service.init_from_current()
        overview = self.service.apply_analysis_results([
            {"code": "BBB", "position_action": "OPEN", "analysis_status": "OK", "current_price": 10.0, "target_quantity": 2},
            {"code": "BBB", "position_action": "ADD", "analysis_status": "OK", "current_price": 12.0, "target_quantity": 5},
        ])
        holdings = {h["code"]: h for h in overview["holdings"]}
        self.assertEqual(float(holdings["BBB"]["quantity"]), 5.0)
        self.assertEqual(float(holdings["BBB"]["current_price"]), 12.0)
        self.assertEqual(float(holdings["BBB"]["market_value"]), 60.0)
        # cash: 100 - (2*10) - (3*12) = 44
        self.assertEqual(float(overview["cash"]), 44.0)

    def test_missing_holding_price_does_not_zero_existing_valuation(self):
        self.service.init_from_current()
        with self.db.get_session() as session:
            row = session.query(PaperPortfolioHolding).filter(PaperPortfolioHolding.code == "AAA").first()
            row.current_price = None
            row.market_value = 100.0
            session.commit()

        overview = self.service.apply_analysis_results([])
        holding = next(x for x in overview["holdings"] if x["code"] == "AAA")
        self.assertEqual(float(holding["market_value"]), 100.0)
        self.assertEqual(float(overview["equity_value"]), 100.0)
        self.assertEqual(float(overview["total_value"]), 200.0)

    def test_init_snapshot_date_aligns_with_real_snapshot_date(self):
        with self.db.get_session() as session:
            session.query(AccountSnapshot).delete()
            session.commit()
        real_date = date(2026, 1, 15)
        self.db.save_account_snapshot(
            snapshot_date=real_date,
            cash=100,
            equity_value=100,
            total_value=200,
            note="real_old_snapshot",
        )
        overview = self.service.init_from_current(force=True)
        self.assertEqual(overview["snapshot_date"], real_date.isoformat())

    def test_noop_with_valid_price_updates_existing_holding_valuation(self):
        self.service.init_from_current()
        overview = self.service.apply_analysis_results([
            # REDUCE with target above current => clamp to current => delta=0 (no-op), but price should revalue.
            {"code": "AAA", "position_action": "REDUCE", "analysis_status": "OK", "current_price": 20.0, "target_quantity": 12},
        ])
        holding = next(x for x in overview["holdings"] if x["code"] == "AAA")
        self.assertEqual(float(holding["quantity"]), 10.0)
        self.assertEqual(float(holding["current_price"]), 20.0)
        self.assertEqual(float(holding["market_value"]), 200.0)
        self.assertEqual(float(overview["equity_value"]), 200.0)
        self.assertEqual(float(overview["total_value"]), 300.0)
        self.assertFalse(overview["latest_simulated_trades"][0]["executed"])

    def test_skip_only_new_symbols_do_not_persist_zero_quantity_rows(self):
        self.service.init_from_current()
        self.service.apply_analysis_results([
            {"code": "ZZZ", "position_action": "HOLD", "analysis_status": "OK", "current_price": 10.0},
            {"code": "YYY", "position_action": "OPEN", "analysis_status": "FAILED", "current_price": 10.0, "target_quantity": 2},
            {"code": "XXX", "position_action": "OPEN", "analysis_status": "OK", "current_price": 10.0, "target_quantity": "nan"},
        ])
        with self.db.get_session() as session:
            zzz = session.query(PaperPortfolioHolding).filter(PaperPortfolioHolding.code == "ZZZ").first()
            yyy = session.query(PaperPortfolioHolding).filter(PaperPortfolioHolding.code == "YYY").first()
            xxx = session.query(PaperPortfolioHolding).filter(PaperPortfolioHolding.code == "XXX").first()
        self.assertIsNone(zzz)
        self.assertIsNone(yyy)
        self.assertIsNone(xxx)


if __name__ == "__main__":
    unittest.main()
