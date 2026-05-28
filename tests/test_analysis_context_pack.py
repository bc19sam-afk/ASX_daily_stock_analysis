# -*- coding: utf-8 -*-

import json
from types import SimpleNamespace

from src.analysis_context import build_analysis_context_pack
from src.core.pipeline import StockAnalysisPipeline


def test_analysis_context_pack_standardizes_asx_identity_and_explicit_missing_states():
    pack = build_analysis_context_pack(
        {
            "code": "bhp.asx",
            "stock_name": "BHP",
            "date": "2026-04-15",
            "execution_price_policy": "close_only",
            "today": {"close": 118.4},
            "data_missing": True,
        },
        stock_name="BHP",
        report_date="2026-04-16",
        validation_status="BLOCK",
        validation_issues=["缺少当日收盘价快照"],
    )

    payload = pack.to_dict()

    assert payload["stock_identity"]["code"] == "BHP.AX"
    assert payload["stock_identity"]["currency"] == "AUD"
    assert payload["stock_identity"]["timezone"] == "Australia/Sydney"
    assert payload["stock_identity"]["market"] == "ASX"
    assert payload["price_basis"]["price_policy"] == "close_only"
    assert payload["price_basis"]["technical_basis_date"] == "2026-04-15"
    assert payload["price_basis"]["report_date"] == "2026-04-16"
    assert payload["market_snapshot"]["realtime"]["status"] == "missing"
    assert payload["evidence_context"]["news"]["status"] == "unavailable"
    assert payload["portfolio_context"]["status"] == "unavailable"
    assert payload["risk_context"]["validation_status"] == "BLOCK"
    assert payload["risk_context"]["actionability"] == "observation_only"
    assert "缺少当日收盘价快照" in payload["risk_context"]["validation_issues"]
    assert payload["prompt_contract"]["deterministic_fields"] == [
        "final_decision",
        "position_action",
        "target_weight",
        "delta_amount",
        "action_counts",
        "search",
        "workflow",
        "close_only",
    ]

    json.dumps(payload, ensure_ascii=False)


def test_pipeline_enhance_context_attaches_context_pack():
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.config = SimpleNamespace(
        execution_price_policy="close_only",
        market_timezone="Australia/Sydney",
        market_calendar="ASX",
    )

    enhanced = pipeline._enhance_context(
        {
            "code": "bhp.asx",
            "date": "2026-04-15",
            "today": {"close": 118.4},
        },
        realtime_quote=None,
        trend_result=None,
        stock_name="BHP",
    )

    assert enhanced["analysis_context_pack"]["stock_identity"]["code"] == "BHP.AX"
    assert enhanced["analysis_context_pack"]["price_basis"]["price_policy"] == "close_only"
