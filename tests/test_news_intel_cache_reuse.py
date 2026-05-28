# -*- coding: utf-8 -*-
"""news_intel persistent search cache reuse tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.config import Config
from src.core.pipeline import StockAnalysisPipeline
from src.enums import ReportType
from src.search_service import BaseSearchProvider, SearchResponse, SearchResult, SearchService
from src.storage import DatabaseManager, NewsIntel


CODE = "CBA.AX"
NAME = "Commonwealth Bank of Australia"


class CountingProvider(BaseSearchProvider):
    def __init__(self, responses: list[SearchResponse]):
        super().__init__(api_keys=["fake-key"], name="provider")
        self._responses = list(responses)
        self.call_count = 0

    def _do_search(self, query: str, api_key: str, max_results: int, days: int = 7) -> SearchResponse:
        self.call_count += 1
        if self._responses:
            response = self._responses.pop(0)
            response.query = query
            response.provider = self.name
            return response
        return SearchResponse(query=query, results=[], provider=self.name, success=False)


@pytest.fixture
def news_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "news_intel_cache.db"))
    Config.reset_instance()
    DatabaseManager.reset_instance()
    db = DatabaseManager.get_instance()
    try:
        yield db
    finally:
        DatabaseManager.reset_instance()
        Config.reset_instance()


def _fresh_date() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")


def _cached_response(
    *,
    title: str = "ASX: CBA.AX cached headline",
    snippet: str = "Commonwealth Bank of Australia cached update",
    source: str = "Reuters",
    url: str = "https://example.com/cached-cba",
    published_date: str | None = None,
) -> SearchResponse:
    return SearchResponse(
        query="cached query",
        results=[
            SearchResult(
                title=title,
                snippet=snippet,
                url=url,
                source=source,
                published_date=published_date or _fresh_date(),
            )
        ],
        provider="provider",
        success=True,
    )


def _provider_response() -> SearchResponse:
    return SearchResponse(
        query="provider query",
        results=[
            SearchResult(
                title="ASX: CBA.AX provider headline",
                snippet="Commonwealth Bank of Australia provider update",
                url="https://example.com/provider-cba",
                source="provider.example",
                published_date=_fresh_date(),
            )
        ],
        provider="provider",
        success=True,
    )


def _pipeline(db: DatabaseManager, service: SearchService, **config_overrides) -> StockAnalysisPipeline:
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.db = db
    pipeline.search_service = service
    config_values = {
        "news_intel_cache_enabled": True,
        "news_intel_cache_days": 1,
        "news_intel_cache_min_results": 1,
        **config_overrides,
    }
    pipeline.config = SimpleNamespace(**config_values)
    return pipeline


def _save_news(db: DatabaseManager, response: SearchResponse, *, dimension: str = "latest_news") -> None:
    saved = db.save_news_intel(
        code=CODE,
        name=NAME,
        dimension=dimension,
        query=response.query,
        response=response,
    )
    assert saved == 1


def test_news_intel_cache_hit_reuses_persistent_news_without_provider(news_db):
    _save_news(news_db, _cached_response())
    service = SearchService()
    provider = CountingProvider([_provider_response()])
    service._providers = [provider]
    pipeline = _pipeline(news_db, service)

    intel = pipeline._search_comprehensive_intel_with_news_cache(
        code=CODE,
        stock_name=NAME,
        max_searches=1,
        force_refresh=False,
    )

    assert provider.call_count == 0
    assert intel["latest_news"].provider == "news_intel_cache"
    assert intel["latest_news"].results[0].title == "ASX: CBA.AX cached headline"

    report = service.format_intel_report(intel, stock_name=NAME)
    assert "ASX: CBA.AX cached headline" in report
    assert "Reuters" in report
    assert "https://example.com/cached-cba" in report
    assert _fresh_date().split(" ")[0] in report


def test_news_intel_cache_insufficient_results_calls_provider(news_db):
    _save_news(news_db, _cached_response())
    service = SearchService()
    provider = CountingProvider([_provider_response()])
    service._providers = [provider]
    pipeline = _pipeline(news_db, service, news_intel_cache_min_results=2)

    intel = pipeline._search_comprehensive_intel_with_news_cache(
        code=CODE,
        stock_name=NAME,
        max_searches=1,
        force_refresh=False,
    )

    assert provider.call_count == 1
    assert intel["latest_news"].provider == "provider"
    assert intel["latest_news"].results[0].url == "https://example.com/provider-cba"


def test_news_intel_cache_expired_records_call_provider(news_db):
    _save_news(news_db, _cached_response())
    with news_db.get_session() as session:
        row = session.query(NewsIntel).one()
        row.fetched_at = datetime.now(timezone.utc) - timedelta(days=2)
        session.commit()

    service = SearchService()
    provider = CountingProvider([_provider_response()])
    service._providers = [provider]
    pipeline = _pipeline(news_db, service)

    intel = pipeline._search_comprehensive_intel_with_news_cache(
        code=CODE,
        stock_name=NAME,
        max_searches=1,
        force_refresh=False,
    )

    assert provider.call_count == 1
    assert intel["latest_news"].provider == "provider"


def test_news_intel_cache_force_refresh_calls_provider(news_db):
    _save_news(news_db, _cached_response())
    service = SearchService()
    provider = CountingProvider([_provider_response()])
    service._providers = [provider]
    pipeline = _pipeline(news_db, service)

    intel = pipeline._search_comprehensive_intel_with_news_cache(
        code=CODE,
        stock_name=NAME,
        max_searches=1,
        force_refresh=True,
    )

    assert provider.call_count == 1
    assert intel["latest_news"].provider == "provider"


def test_news_intel_cache_entity_mismatch_calls_provider(news_db):
    _save_news(
        news_db,
        _cached_response(
            title="CBA surges on NASDAQ",
            snippet="US fintech ticker moves after Nasdaq session",
            source="wrong-market.example",
            url="https://example.com/wrong-market",
        ),
    )
    service = SearchService()
    provider = CountingProvider([_provider_response()])
    service._providers = [provider]
    pipeline = _pipeline(news_db, service)

    intel = pipeline._search_comprehensive_intel_with_news_cache(
        code=CODE,
        stock_name=NAME,
        max_searches=1,
        force_refresh=False,
    )

    assert provider.call_count == 1
    assert intel["latest_news"].provider == "provider"


def test_pipeline_daily_analysis_still_requests_five_search_dimensions(monkeypatch):
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    captured = {}

    class RecordingSearchService:
        is_available = True

        def search_comprehensive_intel(self, *, stock_code, stock_name, max_searches):
            captured["search"] = {
                "stock_code": stock_code,
                "stock_name": stock_name,
                "max_searches": max_searches,
            }
            return {}

        def format_intel_report(self, intel_results, stock_name):
            return ""

    pipeline.config = SimpleNamespace(
        news_intel_cache_enabled=False,
        news_intel_cache_days=1,
        news_intel_cache_min_results=1,
        analysis_read_only=True,
        save_context_snapshot=False,
    )
    pipeline.db = SimpleNamespace(
        get_analysis_context=lambda code: {"allows_current_only_data": False, "today": {}, "yesterday": {}},
        get_previous_signals=lambda code, days: None,
        get_signal_streak=lambda code, days: {"streak": 0, "summary": ""},
        save_news_intel=lambda **kwargs: 0,
    )
    pipeline.fetcher_manager = SimpleNamespace(get_realtime_quote=lambda code: None)
    pipeline.search_service = RecordingSearchService()
    pipeline.trend_analyzer = SimpleNamespace()
    pipeline.analyzer = SimpleNamespace(analyze=lambda enhanced_context, news_context=None: None)
    pipeline._enhance_context = lambda context, realtime_quote, trend_result, stock_name: context
    pipeline._build_query_context = lambda query_id=None: {}
    pipeline.query_id = "query_pipeline"
    pipeline.query_source = "web"
    pipeline.source_message = None
    pipeline.save_context_snapshot = False

    monkeypatch.setattr("src.core.pipeline.STOCK_NAME_MAP", {CODE: NAME})

    pipeline.analyze_stock(CODE, ReportType.FULL, query_id="query_pipeline")

    assert captured["search"]["max_searches"] == 5
