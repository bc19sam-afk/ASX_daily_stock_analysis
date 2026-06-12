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
    assert "announcement" not in evidence
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


def test_backtest_summary_marks_available_with_readable_metrics():
    result = _result(
        backtest_summary={
            "total": 39,
            "win_rate": 56.67,
            "direction_accuracy": 61.54,
            "avg_return": 0.43,
            "stop_loss_rate": 12.5,
        }
    )

    matrix = build_evidence_matrix(
        results=[result],
        overview={"holdings": []},
        classify_price_basis=lambda result: "close_only",
        format_validation_issue_text=lambda result: "",
    )

    evidence = _by_category(matrix["BHP.AX"])
    summary = summarize_evidence_matrix(matrix)

    assert evidence["backtest"]["status"] == "available"
    assert evidence["backtest"]["severity"] == "info"
    assert "样本数：39" in evidence["backtest"]["details"]
    assert "胜率：56.67%" in evidence["backtest"]["details"]
    assert "方向准确率：61.54%" in evidence["backtest"]["details"]
    assert summary["backtest_not_checked"] == 0


def test_backtest_summary_without_verifiable_metrics_stays_not_checked():
    result = _result(backtest_summary={"sample_size": 39})

    matrix = build_evidence_matrix(
        results=[result],
        overview={"holdings": []},
        classify_price_basis=lambda result: "close_only",
        format_validation_issue_text=lambda result: "",
    )

    evidence = _by_category(matrix["BHP.AX"])
    summary = summarize_evidence_matrix(matrix)

    assert evidence["backtest"]["status"] == "not_checked"
    assert evidence["backtest"]["severity"] == "warning"
    assert summary["backtest_not_checked"] == 1


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
    assert summary["announcement_not_checked"] == 0
    assert summary["validation_block"] == 1


def test_valuation_snapshot_is_preferred_for_evidence_details():
    matrix = build_evidence_matrix(
        results=[
            _result(
                code="CBA.AX",
                fundamental_analysis="legacy valuation prose",
                market_snapshot={
                    "date": "2026-05-04",
                    "close": "100.00",
                    "source": "yfinance",
                    "valuation_snapshot": {
                        "pe_ttm": 14.2,
                        "pb": 1.7,
                        "dividend_yield": 0.048,
                        "source": "yfinance",
                        "as_of_date": "2026-05-04",
                    },
                },
            )
        ],
        overview={"holdings": []},
        classify_price_basis=lambda result: "close_only",
        format_validation_issue_text=lambda result: "",
    )

    valuation = _by_category(matrix["CBA.AX"])["valuation"]

    assert valuation["status"] == "available"
    assert valuation["source"] == "yfinance"
    assert valuation["as_of_date"] == "2026-05-04"
    assert "估值快照" in valuation["details"]
    assert "PE(TTM)：14.20" in valuation["details"]
    assert "股息率：4.80%" in valuation["details"]


def test_empty_valuation_snapshot_is_marked_missing():
    matrix = build_evidence_matrix(
        results=[
            _result(
                code="CBA.AX",
                fundamental_analysis="",
                market_snapshot={
                    "date": "2026-05-04",
                    "close": "100.00",
                    "source": "yfinance",
                    "valuation_snapshot": {
                        "pe_ttm": None,
                        "pb": None,
                        "dividend_yield": None,
                        "source": "yfinance",
                        "as_of_date": "2026-05-04",
                    },
                },
            )
        ],
        overview={"holdings": []},
        classify_price_basis=lambda result: "close_only",
        format_validation_issue_text=lambda result: "",
    )

    valuation = _by_category(matrix["CBA.AX"])["valuation"]

    assert valuation["status"] == "missing"
    assert valuation["source"] == "yfinance"
    assert valuation["as_of_date"] == "2026-05-04"
    assert "缺少" in valuation["details"]


def test_auxiliary_only_valuation_snapshot_is_marked_partial():
    matrix = build_evidence_matrix(
        results=[
            _result(
                code="CBA.AX",
                fundamental_analysis="legacy valuation prose",
                market_snapshot={
                    "date": "2026-05-04",
                    "close": "100.00",
                    "source": "yfinance",
                    "valuation_snapshot": {
                        "market_cap": 123456789,
                        "source": "yfinance",
                        "as_of_date": "2026-05-04",
                    },
                },
            )
        ],
        overview={"holdings": []},
        classify_price_basis=lambda result: "close_only",
        format_validation_issue_text=lambda result: "",
    )

    valuation = _by_category(matrix["CBA.AX"])["valuation"]
    summary = summarize_evidence_matrix(matrix)

    assert valuation["status"] == "partial"
    assert valuation["severity"] == "warning"
    assert "缺少 PE/PB/股息率" in valuation["details"]
    assert summary["valuation_missing"] == 1


def test_undated_valuation_snapshot_does_not_fallback_to_market_date():
    matrix = build_evidence_matrix(
        results=[
            _result(
                code="CBA.AX",
                fundamental_analysis="legacy valuation prose",
                market_snapshot={
                    "date": "2026-05-04",
                    "close": "100.00",
                    "source": "yfinance",
                    "valuation_snapshot": {
                        "pe_ttm": 15.1,
                        "pb": 1.9,
                        "dividend_yield": 0.03,
                        "source": "yfinance",
                        "as_of_date": None,
                    },
                },
            )
        ],
        overview={"holdings": []},
        classify_price_basis=lambda result: "close_only",
        format_validation_issue_text=lambda result: "",
    )

    valuation = _by_category(matrix["CBA.AX"])["valuation"]

    assert valuation["status"] == "available"
    assert valuation["source"] == "yfinance"
    assert valuation["as_of_date"] is None
    assert "时间：2026-05-04" not in valuation["details"]
