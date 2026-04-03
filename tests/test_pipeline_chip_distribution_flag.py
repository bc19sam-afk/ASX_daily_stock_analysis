# -*- coding: utf-8 -*-

from types import SimpleNamespace

from src.core.pipeline import StockAnalysisPipeline


def test_pipeline_init_respects_passed_chip_distribution_flag(monkeypatch):
    monkeypatch.setattr("src.core.pipeline.get_db", lambda: SimpleNamespace())
    monkeypatch.setattr("src.core.pipeline.DataFetcherManager", lambda config=None: SimpleNamespace())
    monkeypatch.setattr("src.core.pipeline.StockTrendAnalyzer", lambda: SimpleNamespace())
    monkeypatch.setattr("src.core.pipeline.GeminiAnalyzer", lambda: SimpleNamespace())
    monkeypatch.setattr("src.core.pipeline.NotificationService", lambda source_message=None: SimpleNamespace())
    monkeypatch.setattr("src.core.pipeline.PositionManager", lambda: SimpleNamespace())
    monkeypatch.setattr("src.core.pipeline.SearchService", lambda **kwargs: SimpleNamespace(is_available=False))

    config = SimpleNamespace(
        enable_chip_distribution=True,
        max_workers=2,
        save_context_snapshot=True,
        bocha_api_keys=[],
        tavily_api_keys=[],
        brave_api_keys=[],
        serpapi_keys=[],
        news_max_age_days=3,
        enable_realtime_quote=False,
        realtime_source_priority="yfinance",
    )

    pipeline = StockAnalysisPipeline(config=config)

    assert pipeline.config.enable_chip_distribution is True
