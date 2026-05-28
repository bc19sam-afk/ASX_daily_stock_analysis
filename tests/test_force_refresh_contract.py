# -*- coding: utf-8 -*-

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from api.v1.schemas.analysis import AnalyzeRequest
from src.core.pipeline import StockAnalysisPipeline
from src.enums import ReportType
from src.services.analysis_service import AnalysisService


def test_analyze_request_defaults_to_force_refresh():
    request = AnalyzeRequest(stock_code="BHP.AX")

    assert request.force_refresh is True


def test_force_refresh_public_schema_documents_default_refresh():
    schema = AnalyzeRequest.model_json_schema()
    static_spec = json.loads(Path("docs/architecture/api_spec.json").read_text(encoding="utf-8"))
    static_request_schema = static_spec["components"]["schemas"]["AnalyzeRequest"]

    assert schema["properties"]["force_refresh"]["default"] is True
    assert AnalyzeRequest.model_config["json_schema_extra"]["example"]["force_refresh"] is True
    assert static_request_schema["properties"]["force_refresh"]["default"] is True
    assert static_request_schema["example"]["force_refresh"] is True


def test_analysis_service_passes_force_refresh_to_pipeline(monkeypatch):
    captured = {}

    class DummyPipeline:
        def __init__(self, **kwargs):
            captured["init"] = kwargs

        def process_single_stock(self, **kwargs):
            captured["process"] = kwargs
            return object()

    monkeypatch.setattr("src.core.pipeline.StockAnalysisPipeline", DummyPipeline)
    monkeypatch.setattr(
        AnalysisService,
        "_build_analysis_response",
        lambda self, result, query_id, report_type: {"query_id": query_id, "report_type": report_type.value},
    )

    response = AnalysisService().analyze_stock(
        "BHP.AX",
        report_type="full",
        force_refresh=True,
        query_id="query_force",
        send_notification=False,
    )

    assert response == {"query_id": "query_force", "report_type": "full"}
    assert captured["process"]["force_refresh"] is True
    assert captured["process"]["code"] == "BHP.AX"


def test_process_single_stock_forwards_force_refresh_to_fetcher(monkeypatch):
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.query_id = "query_pipeline"
    pipeline.notifier = SimpleNamespace(is_available=lambda: False)
    captured = {}

    def fake_fetch(code, force_refresh=False):
        captured["fetch"] = {"code": code, "force_refresh": force_refresh}
        return True, None, {"stock_name": "BHP"}

    def fake_analyze_stock(code, report_type, query_id, df_attrs=None, market_overview=None, force_refresh=False):
        captured["analyze"] = {
            "code": code,
            "report_type": report_type,
            "query_id": query_id,
            "df_attrs": df_attrs,
            "market_overview": market_overview,
            "force_refresh": force_refresh,
        }
        return SimpleNamespace(operation_advice="HOLD", sentiment_score=70)

    monkeypatch.setattr(pipeline, "fetch_and_save_stock_data", fake_fetch)
    monkeypatch.setattr(pipeline, "analyze_stock", fake_analyze_stock)

    result = pipeline.process_single_stock(
        code="BHP.AX",
        report_type=ReportType.FULL,
        market_overview={"ASX 200": {"pct_chg": 0.2}},
        force_refresh=True,
    )

    assert result.operation_advice == "HOLD"
    assert captured["fetch"] == {"code": "BHP.AX", "force_refresh": True}
    assert captured["analyze"]["df_attrs"] == {"stock_name": "BHP"}
    assert captured["analyze"]["force_refresh"] is True


def test_fetch_and_save_stock_data_uses_market_timezone_for_cache_date(monkeypatch):
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.config = SimpleNamespace(market_calendar="ASX", market_timezone="Australia/Sydney")
    captured = {}

    def fake_now(timezone_name):
        captured["timezone_name"] = timezone_name
        return datetime(2026, 4, 29, 8, 0, 0, tzinfo=ZoneInfo("Australia/Sydney"))

    def fake_has_today_data(code, today):
        captured["cache_check"] = (code, today)
        return True

    pipeline.db = SimpleNamespace(has_today_data=fake_has_today_data)
    pipeline.fetcher_manager = SimpleNamespace()
    monkeypatch.setattr("src.core.pipeline._now_in_timezone_safe", fake_now)

    success, error, attrs = pipeline.fetch_and_save_stock_data("BHP.AX", force_refresh=False)

    assert success is True
    assert error is None
    assert attrs == {}
    assert captured["timezone_name"] == "Australia/Sydney"
    assert captured["cache_check"][0] == "BHP.AX"
    assert captured["cache_check"][1].isoformat() == "2026-04-28"


def test_fetch_and_save_stock_data_falls_back_to_sydney_when_market_timezone_invalid(monkeypatch):
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.config = SimpleNamespace(market_calendar="ASX", market_timezone="Invalid/Zone")
    captured = {}

    def fake_now(timezone_name):
        captured["timezone_name"] = timezone_name
        return datetime(2026, 4, 29, 8, 0, 0, tzinfo=ZoneInfo("Australia/Sydney"))

    def fake_has_today_data(code, today):
        captured["cache_check"] = (code, today)
        return True

    def fail_fetch(*args, **kwargs):
        raise AssertionError("fetcher should not run when safe cache date already exists")

    pipeline.db = SimpleNamespace(has_today_data=fake_has_today_data)
    pipeline.fetcher_manager = SimpleNamespace(get_daily_data=fail_fetch)
    monkeypatch.setattr("src.core.pipeline._now_in_timezone_safe", fake_now)

    success, error, attrs = pipeline.fetch_and_save_stock_data("BHP.AX", force_refresh=False)

    assert success is True
    assert error is None
    assert attrs == {}
    assert captured["timezone_name"] == "Australia/Sydney"
    assert captured["cache_check"][0] == "BHP.AX"
    assert captured["cache_check"][1].isoformat() == "2026-04-28"


def test_dry_run_success_count_uses_market_report_date(monkeypatch):
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.config = SimpleNamespace(
        market_calendar="ASX",
        market_timezone="Australia/Sydney",
        single_stock_notify=False,
        report_type=ReportType.SIMPLE.value,
        analysis_delay=0,
    )
    pipeline.max_workers = 1
    pipeline.fetcher_manager = SimpleNamespace()
    pipeline._fetch_market_overview = lambda: {}
    pipeline.process_single_stock = lambda *args, **kwargs: SimpleNamespace()
    captured = []

    def fake_now(timezone_name):
        return datetime(2026, 3, 30, 8, 30, tzinfo=ZoneInfo("Australia/Sydney"))

    def fake_has_today_data(code, target_date):
        captured.append((code, target_date.isoformat()))
        return code == "BHP.AX"

    pipeline.db = SimpleNamespace(has_today_data=fake_has_today_data)
    monkeypatch.setattr("src.core.pipeline._now_in_timezone_safe", fake_now)

    results = pipeline.run(stock_codes=["BHP.AX", "CBA.AX"], dry_run=True, send_notification=False)

    assert len(results) == 2
    assert captured == [("BHP.AX", "2026-03-27"), ("CBA.AX", "2026-03-27")]
