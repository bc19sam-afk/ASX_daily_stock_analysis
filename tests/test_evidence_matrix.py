# -*- coding: utf-8 -*-
"""Evidence matrix contract tests."""

from src.analyzer import AnalysisResult
from src.evidence_matrix import build_evidence_matrix, summarize_evidence_matrix


def _result(**overrides) -> AnalysisResult:
    base = dict(
        code="BHP.AX",
        name="BHP",
        sentiment_score=70,
        trend_prediction="震荡上行",
        operation_advice="按计划观察",
        final_decision="HOLD",
        position_action="HOLD",
        execution_price_source="close_only",
        market_snapshot={"date": "2026-04-28", "close": "50.00", "source": "yfinance"},
        technical_analysis="MA10 支撑仍在",
        fundamental_analysis="估值稳定",
        news_summary="无重大新增风险",
        validation_status="PASS",
    )
    base.update(overrides)
    return AnalysisResult(**base)


def _by_category(entries):
    return {entry["category"]: entry for entry in entries}


def test_evidence_matrix_marks_available_and_missing_categories_explicitly():
    matrix = build_evidence_matrix(
        results=[
            _result(
                code="BHP.AX",
                market_snapshot={"close": "50.00", "source": "yfinance"},
                news_summary="",
                fundamental_analysis="",
            )
        ],
        overview={"holdings": []},
        classify_price_basis=lambda result: "close_only",
        format_validation_issue_text=lambda result: "",
    )

    evidence = _by_category(matrix["BHP.AX"])

    assert evidence["market_data"]["status"] == "missing"
    assert "market_snapshot.date" in evidence["market_data"]["details"]
    assert evidence["news"]["status"] == "missing"
    assert evidence["valuation"]["status"] == "missing"
    assert evidence["announcement"]["status"] == "not_checked"
    assert evidence["backtest"]["status"] == "not_checked"
    assert evidence["technical"]["status"] == "available"
    assert evidence["validation"]["status"] == "available"


def test_validation_block_is_recorded_with_block_severity():
    matrix = build_evidence_matrix(
        results=[
            _result(
                code="NAB.AX",
                validation_status="BLOCK",
                validation_issues=["收盘价缺失，无法确认昨收计划。"],
            )
        ],
        overview={"holdings": []},
        classify_price_basis=lambda result: "close_only",
        format_validation_issue_text=lambda result: "收盘价缺失，无法确认昨收计划。",
    )

    validation = _by_category(matrix["NAB.AX"])["validation"]

    assert validation["severity"] == "block"
    assert validation["status"] == "available"
    assert "收盘价缺失" in validation["details"]


def test_evidence_summary_counts_missing_and_block_entries():
    matrix = build_evidence_matrix(
        results=[
            _result(code="BHP.AX"),
            _result(code="NAB.AX", news_summary="", validation_status="BLOCK"),
        ],
        overview={"holdings": []},
        classify_price_basis=lambda result: "close_only",
        format_validation_issue_text=lambda result: "validation blocked",
    )

    summary = summarize_evidence_matrix(matrix)

    assert summary["stock_count"] == 2
    assert summary["market_data_available"] == 2
    assert summary["news_missing"] == 1
    assert summary["validation_block"] == 1
