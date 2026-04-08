# -*- coding: utf-8 -*-

from types import SimpleNamespace

from data_provider.base import BaseFetcher
from src.core.pipeline import StockAnalysisPipeline


class DummyChipFetcher(BaseFetcher):
    name = "AkshareFetcher"
    priority = 1

    def __init__(self):
        self.calls = 0

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str):
        raise NotImplementedError

    def _normalize_data(self, df, stock_code: str):
        raise NotImplementedError

    def get_chip_distribution(self, stock_code: str):
        self.calls += 1
        return SimpleNamespace(source="dummy", code=stock_code)


def _build_pipeline(monkeypatch, enable_chip_distribution: bool):
    monkeypatch.setattr("src.core.pipeline.get_db", lambda: SimpleNamespace())
    monkeypatch.setattr("src.core.pipeline.StockTrendAnalyzer", lambda: SimpleNamespace())
    monkeypatch.setattr("src.core.pipeline.GeminiAnalyzer", lambda: SimpleNamespace())
    monkeypatch.setattr("src.core.pipeline.NotificationService", lambda source_message=None: SimpleNamespace())
    monkeypatch.setattr("src.core.pipeline.PositionManager", lambda: SimpleNamespace())
    monkeypatch.setattr("src.core.pipeline.SearchService", lambda **kwargs: SimpleNamespace(is_available=False))

    config = SimpleNamespace(
        enable_chip_distribution=enable_chip_distribution,
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
    return StockAnalysisPipeline(config=config)


def test_pipeline_global_config_injection_still_refreshes_fetcher_config(monkeypatch):
    current_config = {
        "value": SimpleNamespace(
            enable_chip_distribution=False,
            enable_realtime_quote=False,
            realtime_source_priority="yfinance",
        )
    }

    monkeypatch.setattr("src.config.get_config", lambda: current_config["value"])

    pipeline = _build_pipeline(monkeypatch, enable_chip_distribution=True)
    fetcher = DummyChipFetcher()
    pipeline.fetcher_manager._fetchers = [fetcher]

    class DummyCircuitBreaker:
        def is_available(self, source_key):
            return True

        def record_success(self, source_key):
            pass

        def record_failure(self, source_key, error):
            pass

    monkeypatch.setattr("data_provider.realtime_types.get_chip_circuit_breaker", lambda: DummyCircuitBreaker())

    current_config["value"] = SimpleNamespace(
        enable_chip_distribution=True,
        enable_realtime_quote=False,
        realtime_source_priority="yfinance",
    )

    chip = pipeline.fetcher_manager.get_chip_distribution("600519")

    assert chip is not None
    assert fetcher.calls == 1


def test_pipeline_config_true_allows_chip_distribution_even_if_global_default_false(monkeypatch):
    monkeypatch.setattr(
        "src.config.get_config",
        lambda: SimpleNamespace(enable_chip_distribution=False, enable_realtime_quote=False, realtime_source_priority="yfinance"),
    )

    pipeline = _build_pipeline(monkeypatch, enable_chip_distribution=True)
    fetcher = DummyChipFetcher()
    pipeline.fetcher_manager._fetchers = [fetcher]

    class DummyCircuitBreaker:
        def is_available(self, source_key):
            return True

        def record_success(self, source_key):
            pass

        def record_failure(self, source_key, error):
            pass

    monkeypatch.setattr("data_provider.realtime_types.get_chip_circuit_breaker", lambda: DummyCircuitBreaker())

    chip = pipeline.fetcher_manager.get_chip_distribution("600519")

    assert chip is not None
    assert fetcher.calls == 1


def test_pipeline_config_false_skips_chip_distribution_at_fetcher_layer(monkeypatch):
    pipeline = _build_pipeline(monkeypatch, enable_chip_distribution=False)
    fetcher = DummyChipFetcher()
    pipeline.fetcher_manager._fetchers = [fetcher]

    chip = pipeline.fetcher_manager.get_chip_distribution("600519")

    assert chip is None
    assert fetcher.calls == 0
