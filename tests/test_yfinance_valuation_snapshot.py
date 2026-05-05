# -*- coding: utf-8 -*-
"""Structured valuation snapshot tests for yfinance quotes and reports."""

import sys
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from data_provider.yfinance_fetcher import YfinanceFetcher
from src.analyzer import AnalysisResult
from src.daily_decision_summary import build_daily_decision_summary
from src.notification import NotificationService


class _FastInfo:
    last_price = 100.0
    previous_close = 98.0
    open = 99.0
    day_high = 101.0
    day_low = 97.5
    last_volume = 123456
    market_cap = 1_000_000_000


class _Ticker:
    fast_info = _FastInfo()
    info = {
        "shortName": "CBA",
        "trailingPE": 14.2,
        "forwardPE": 13.8,
        "priceToBook": 1.7,
        "dividendYield": 0.048,
        "marketCap": 1_000_000_000,
        "returnOnEquity": 0.12,
        "debtToEquity": 85.5,
        "asOfDate": "2026-05-04",
    }


class _MissingPeTicker:
    fast_info = _FastInfo()
    info = {
        "shortName": "No PE",
        "priceToBook": 1.2,
        "dividendYield": 0.02,
        "marketCap": 500_000_000,
    }


class _UndatedValuationTicker:
    fast_info = _FastInfo()
    info = {
        "shortName": "Undated valuation",
        "trailingPE": 15.1,
        "priceToBook": 1.9,
        "dividendYield": 0.03,
        "marketCap": 600_000_000,
    }


def _install_fake_yfinance(monkeypatch, ticker_cls):
    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        SimpleNamespace(Ticker=lambda symbol: ticker_cls()),
    )


def _service() -> NotificationService:
    service = NotificationService.__new__(NotificationService)
    service._report_summary_only = False
    service._report_timezone = "Australia/Sydney"
    service._last_daily_decision_summary = None
    return service


def _result(**overrides) -> AnalysisResult:
    values = dict(
        code="CBA.AX",
        name="CBA",
        sentiment_score=75,
        trend_prediction="震荡上行",
        operation_advice="按计划观察",
        final_decision="BUY",
        position_action="OPEN",
        current_weight=0.0,
        target_weight=0.10,
        delta_amount=5000.0,
        execution_price_source="close_only",
        market_snapshot={"date": "2026-05-04", "close": "100.00", "source": "yfinance"},
        fundamental_analysis="估值稳定",
        news_summary="无重大新增风险",
    )
    values.update(overrides)
    return AnalysisResult(**values)


def _summary(results):
    return build_daily_decision_summary(
        results=results,
        report_date="2026-05-05",
        generated_at=datetime(2026, 5, 5, 7, 30, tzinfo=ZoneInfo("Australia/Sydney")),
        overview={"cash": 50000.0, "equity_value": 50000.0, "total_value": 100000.0, "holdings": []},
        get_primary_action_model=lambda result: {
            "position_action": result.position_action,
            "target_weight": result.target_weight,
            "delta_amount": result.delta_amount,
        },
        classify_price_basis=lambda result: result.execution_price_source,
        format_stock_display_name=lambda name, code: f"{name} ({code})",
        format_validation_issue_text=lambda result: "；".join(result.validation_issues or []),
    )


def test_yfinance_quote_exposes_structured_valuation_without_dividend_in_pe(monkeypatch):
    _install_fake_yfinance(monkeypatch, _Ticker)

    quote = YfinanceFetcher().get_realtime_quote("CBA.AX")

    assert quote is not None
    assert quote.pe_ratio == 14.2
    assert "股息率" not in str(quote.pe_ratio)
    assert quote.pb_ratio == 1.7
    assert quote.total_mv == 1_000_000_000
    assert quote.valuation_snapshot is not None
    assert quote.valuation_snapshot.pe_ttm == 14.2
    assert quote.valuation_snapshot.pe_forward == 13.8
    assert quote.valuation_snapshot.pb == 1.7
    assert quote.valuation_snapshot.dividend_yield == 0.048
    assert quote.valuation_snapshot.source == "yfinance"
    as_dict = quote.to_dict()
    assert as_dict["valuation_snapshot"]["dividend_yield"] == 0.048


def test_yfinance_quote_handles_missing_pe_without_error(monkeypatch):
    _install_fake_yfinance(monkeypatch, _MissingPeTicker)

    quote = YfinanceFetcher().get_realtime_quote("CBA.AX")

    assert quote is not None
    assert quote.pe_ratio is None
    assert quote.valuation_snapshot is not None
    assert quote.valuation_snapshot.pe_ttm is None
    assert quote.valuation_snapshot.pb == 1.2


def test_yfinance_quote_does_not_invent_valuation_as_of_date(monkeypatch):
    _install_fake_yfinance(monkeypatch, _UndatedValuationTicker)

    quote = YfinanceFetcher().get_realtime_quote("CBA.AX")

    assert quote is not None
    assert quote.valuation_snapshot is not None
    assert quote.valuation_snapshot.pe_ttm == 15.1
    assert quote.valuation_snapshot.as_of_date is None
    assert "as_of_date" not in quote.to_dict()["valuation_snapshot"] or quote.to_dict()["valuation_snapshot"]["as_of_date"] is None


def test_single_stock_report_renders_structured_valuation_and_missing_state():
    service = _service()
    with_snapshot = _result(
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
        }
    )
    missing_snapshot = _result(code="MIS.AX", name="MIS", fundamental_analysis="")
    undated_snapshot = _result(
        code="UND.AX",
        name="UND",
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
    empty_snapshot = _result(
        code="EMP.AX",
        name="EMP",
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

    report = service.generate_single_stock_report(with_snapshot)
    missing_report = service.generate_single_stock_report(missing_snapshot)
    undated_report = service.generate_single_stock_report(undated_snapshot)
    empty_report = service.generate_single_stock_report(empty_snapshot)

    assert "### 估值快照" in report
    assert "PE(TTM)：14.20" in report
    assert "PB：1.70" in report
    assert "股息率：4.80%" in report
    assert "来源：Yahoo Finance" in report
    assert "估值数据缺失，不参与估值增强。" in missing_report
    assert "时间：missing" in undated_report
    assert "时间：2026-05-04" not in undated_report
    assert "估值数据缺失，不参与估值增强。" in empty_report


def test_valuation_snapshot_does_not_change_actions_or_counts():
    baseline = _summary([_result()])
    with_snapshot = _summary(
        [
            _result(
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
                }
            )
        ]
    )

    assert with_snapshot["action_counts"] == baseline["action_counts"]
    assert with_snapshot["actionable_items"][0]["position_action"] == baseline["actionable_items"][0]["position_action"]
    assert with_snapshot["actionable_items"][0]["target_weight"] == baseline["actionable_items"][0]["target_weight"]
    assert with_snapshot["actionable_items"][0]["delta_amount"] == baseline["actionable_items"][0]["delta_amount"]
