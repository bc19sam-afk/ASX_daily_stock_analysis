# -*- coding: utf-8 -*-
"""Tests for validator gate behavior."""

import json
from datetime import datetime
from types import SimpleNamespace
import unittest
from zoneinfo import ZoneInfo

from src.analyzer import AnalysisResult
from src.core.pipeline import StockAnalysisPipeline
from src.core.validator import evaluate_analysis_gate, normalize_validation_status


class ValidationGateTestCase(unittest.TestCase):
    def _build_result(self) -> AnalysisResult:
        return AnalysisResult(
            code="BHP.AX",
            name="BHP",
            sentiment_score=72,
            trend_prediction="看多",
            operation_advice="买入",
            final_decision="BUY",
            position_action="ADD",
            target_weight=0.15,
            current_weight=0.05,
            delta_amount=5000.0,
            analysis_summary="趋势保持强势",
        )

    def test_evaluate_analysis_gate_blocks_mixed_price_basis_on_trading_day(self) -> None:
        outcome = evaluate_analysis_gate(
            enhanced_context={
                "date": "2026-04-13",
                "today": {"close": 48.2},
            },
            execution_price_source="realtime",
            current_price=49.1,
            market_timezone="Australia/Sydney",
            market_calendar="ASX",
            now=datetime(2026, 4, 14, 13, 0, tzinfo=ZoneInfo("Australia/Sydney")),
        )

        self.assertEqual(outcome.validation_status, "BLOCK")
        self.assertEqual(outcome.blocked_reason, ["mixed_price_basis"])
        self.assertTrue(outcome.mixed_price_basis)
        self.assertFalse(outcome.stale_daily_context)
        self.assertFalse(outcome.missing_critical_data)
        self.assertTrue(any("价格口径混用" in item for item in outcome.validation_issues))

    def test_evaluate_analysis_gate_blocks_stale_daily_context(self) -> None:
        outcome = evaluate_analysis_gate(
            enhanced_context={
                "date": "2026-04-09",
                "today": {"close": 48.2},
            },
            execution_price_source="latest_close",
            current_price=48.2,
            market_timezone="Australia/Sydney",
            market_calendar="ASX",
            now=datetime(2026, 4, 14, 18, 0),
        )

        self.assertEqual(outcome.validation_status, "BLOCK")
        self.assertEqual(outcome.blocked_reason, ["stale_daily_context"])
        self.assertFalse(outcome.mixed_price_basis)
        self.assertTrue(outcome.stale_daily_context)
        self.assertFalse(outcome.missing_critical_data)
        self.assertTrue(any("日线基准已过期" in item for item in outcome.validation_issues))

    def test_apply_validation_gate_blocks_actions_on_missing_critical_data(self) -> None:
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.config = SimpleNamespace(
            market_timezone="Australia/Sydney",
            market_calendar="ASX",
        )
        result = self._build_result()

        pipeline._apply_validation_gate(
            result=result,
            enhanced_context={
                "date": "2026-04-14",
                "today": {},
                "data_missing": True,
            },
        )

        self.assertEqual(result.validation_status, "BLOCK")
        self.assertEqual(result.final_decision, "HOLD")
        self.assertEqual(result.position_action, "HOLD")
        self.assertEqual(result.watchlist_state, "OBSERVE")
        self.assertEqual(result.delta_amount, 0.0)
        self.assertEqual(result.operation_advice, "不可决策，仅观察")
        self.assertIn("validation_blocked", result.action_reason)
        self.assertTrue(any("缺少" in item for item in result.validation_issues))

    def test_evaluate_analysis_gate_emits_structured_reason_flags_for_missing_critical_data(self) -> None:
        outcome = evaluate_analysis_gate(
            enhanced_context={
                "date": "2026-04-14",
                "today": {},
                "data_missing": True,
            },
            execution_price_source="latest_close",
            current_price=None,
            market_timezone="Australia/Sydney",
            market_calendar="ASX",
            now=datetime(2026, 4, 14, 18, 0),
        )

        self.assertEqual(outcome.validation_status, "BLOCK")
        self.assertEqual(outcome.blocked_reason, ["missing_critical_data"])
        self.assertFalse(outcome.mixed_price_basis)
        self.assertFalse(outcome.stale_daily_context)
        self.assertTrue(outcome.missing_critical_data)

    def test_evaluate_analysis_gate_passes_latest_close_basis(self) -> None:
        outcome = evaluate_analysis_gate(
            enhanced_context={
                "date": "2026-04-14",
                "today": {"close": 48.2},
            },
            execution_price_source="latest_close",
            current_price=48.2,
            market_timezone="Australia/Sydney",
            market_calendar="ASX",
            now=datetime(2026, 4, 14, 18, 0),
        )

        self.assertEqual(outcome.validation_status, "PASS")
        self.assertEqual(outcome.validation_issues, [])
        self.assertEqual(outcome.blocked_reason, [])
        self.assertFalse(outcome.mixed_price_basis)
        self.assertFalse(outcome.stale_daily_context)
        self.assertFalse(outcome.missing_critical_data)

    def test_apply_validation_gate_logs_structured_observability_payload(self) -> None:
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.config = SimpleNamespace(
            market_timezone="Australia/Sydney",
            market_calendar="ASX",
        )
        pipeline.query_id = "query-observe"
        result = self._build_result()
        result.current_price = 48.2
        result.execution_price_source = "latest_close"

        with self.assertLogs("src.core.pipeline", level="WARNING") as captured:
            pipeline._apply_validation_gate(
                result=result,
                enhanced_context={
                    "date": "2026-04-09",
                    "today": {"close": 48.2},
                },
            )

        self.assertEqual(len(captured.records), 1)
        message = captured.records[0].getMessage()
        self.assertTrue(message.startswith("[validator_gate] "))
        payload = json.loads(message.split(" ", 1)[1])
        self.assertEqual(payload["stock_code"], "BHP.AX")
        self.assertEqual(payload["query_id"], "query-observe")
        self.assertEqual(payload["validation_status"], "BLOCK")
        self.assertEqual(payload["blocked_reason"], ["stale_daily_context"])
        self.assertFalse(payload["mixed_price_basis"])
        self.assertTrue(payload["stale_daily_context"])
        self.assertFalse(payload["missing_critical_data"])

    def test_apply_validation_gate_logs_pass_observability_payload(self) -> None:
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.config = SimpleNamespace(
            market_timezone="Australia/Sydney",
            market_calendar="ASX",
        )
        pipeline.query_id = "query-pass-observe"
        result = self._build_result()
        result.current_price = 48.2
        result.execution_price_source = "latest_close"

        with self.assertLogs("src.core.pipeline", level="INFO") as captured:
            pipeline._apply_validation_gate(
                result=result,
                enhanced_context={
                    "date": "2026-04-14",
                    "today": {"close": 48.2},
                },
            )

        self.assertEqual(len(captured.records), 1)
        message = captured.records[0].getMessage()
        self.assertTrue(message.startswith("[validator_gate] "))
        payload = json.loads(message.split(" ", 1)[1])
        self.assertEqual(payload["stock_code"], "BHP.AX")
        self.assertEqual(payload["query_id"], "query-pass-observe")
        self.assertEqual(payload["validation_status"], "PASS")
        self.assertEqual(payload["blocked_reason"], [])
        self.assertFalse(payload["mixed_price_basis"])
        self.assertFalse(payload["stale_daily_context"])
        self.assertFalse(payload["missing_critical_data"])

    def test_post_open_close_only_basis_still_passes_validation(self) -> None:
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.config = SimpleNamespace(
            execution_price_policy="close_only",
            market_timezone="Australia/Sydney",
            market_calendar="ASX",
        )
        result = self._build_result()
        enhanced_context = {
            "date": "2026-04-14",
            "today": {"close": 48.2},
            "realtime": {"price": 49.1, "change_pct": 1.7},
        }

        pipeline._apply_runtime_price_fields(result=result, enhanced_context=enhanced_context)
        outcome = evaluate_analysis_gate(
            enhanced_context=enhanced_context,
            execution_price_source=result.execution_price_source,
            current_price=result.current_price,
            market_timezone="Australia/Sydney",
            market_calendar="ASX",
            now=datetime(2026, 4, 15, 10, 30, tzinfo=ZoneInfo("Australia/Sydney")),
        )

        self.assertEqual(result.execution_price_source, "close_only")
        self.assertEqual(result.current_price, 48.2)
        self.assertEqual(outcome.validation_status, "PASS")
        self.assertEqual(outcome.blocked_reason, [])

    def test_normalize_validation_status_collapses_warn_to_pass(self) -> None:
        self.assertEqual(normalize_validation_status("WARN"), "PASS")
        self.assertEqual(normalize_validation_status("BLOCK"), "BLOCK")


if __name__ == "__main__":
    unittest.main()
