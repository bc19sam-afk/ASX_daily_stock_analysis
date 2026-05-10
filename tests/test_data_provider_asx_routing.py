import pandas as pd
import pytest
from types import SimpleNamespace
from unittest.mock import patch

from data_provider.base import BaseFetcher, DataFetchError, DataFetcherManager
from data_provider.realtime_types import RealtimeSource, UnifiedRealtimeQuote
from data_provider.yfinance_fetcher import YfinanceFetcher


class DummyFetcher(BaseFetcher):
    def __init__(self, name: str, priority: int = 1):
        self.name = name
        self.priority = priority
        self.calls = 0
        self.last_stock_code = None

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        raise NotImplementedError

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        raise NotImplementedError

    def get_daily_data(self, stock_code: str, start_date=None, end_date=None, days: int = 30) -> pd.DataFrame:
        self.calls += 1
        self.last_stock_code = stock_code
        return pd.DataFrame(
            {
                "date": [pd.Timestamp("2026-03-20")],
                "open": [1.0],
                "high": [1.1],
                "low": [0.9],
                "close": [1.05],
                "volume": [1000],
                "amount": [1050],
                "pct_chg": [0.5],
            }
        )


class DummyRealtimeFetcher(DummyFetcher):
    def __init__(self, name: str, priority: int = 1, quote: UnifiedRealtimeQuote | None = None):
        super().__init__(name=name, priority=priority)
        self.quote = quote
        self.realtime_calls = 0

    def get_realtime_quote(self, stock_code: str, source=None):
        self.realtime_calls += 1
        return self.quote


def test_asx_stock_routes_to_yfinance_only():
    cn_fetcher = DummyFetcher("TushareFetcher", priority=1)
    yf_fetcher = DummyFetcher("YfinanceFetcher", priority=2)
    manager = DataFetcherManager(fetchers=[cn_fetcher, yf_fetcher])

    df, source = manager.get_daily_data("CBA.AX", days=5)

    assert not df.empty
    assert source == "YfinanceFetcher"
    assert cn_fetcher.calls == 0
    assert yf_fetcher.calls == 1


def test_us_stock_routes_to_yfinance_only():
    cn_fetcher = DummyFetcher("AkshareFetcher", priority=1)
    yf_fetcher = DummyFetcher("YfinanceFetcher", priority=2)
    manager = DataFetcherManager(fetchers=[cn_fetcher, yf_fetcher])

    _, source = manager.get_daily_data("AAPL", days=5)

    assert source == "YfinanceFetcher"
    assert cn_fetcher.calls == 0
    assert yf_fetcher.calls == 1


def test_a_share_uses_non_yfinance_by_priority():
    cn_fetcher = DummyFetcher("TushareFetcher", priority=1)
    yf_fetcher = DummyFetcher("YfinanceFetcher", priority=2)
    manager = DataFetcherManager(
        fetchers=[cn_fetcher, yf_fetcher],
        config=SimpleNamespace(market_calendar="CN"),
    )

    _, source = manager.get_daily_data("600519", days=5)

    assert source == "TushareFetcher"
    assert cn_fetcher.calls == 1
    assert yf_fetcher.calls == 0


def test_bare_configured_asx_ticker_is_normalized_to_ax_before_fetch():
    yf_fetcher = DummyFetcher("YfinanceFetcher", priority=1)
    manager = DataFetcherManager(
        fetchers=[yf_fetcher],
        config=SimpleNamespace(market_calendar="ASX", stock_list=["BHP.AX", "CBA.AX"]),
    )

    _, source = manager.get_daily_data("BHP", days=5)

    assert source == "YfinanceFetcher"
    assert yf_fetcher.last_stock_code == "BHP.AX"


def test_asx_default_rejects_numeric_ticker_without_explicit_cn_mode():
    cn_fetcher = DummyFetcher("TushareFetcher", priority=1)
    yf_fetcher = DummyFetcher("YfinanceFetcher", priority=2)
    manager = DataFetcherManager(
        fetchers=[cn_fetcher, yf_fetcher],
        config=SimpleNamespace(market_calendar="ASX", stock_list=["BHP.AX"]),
    )

    with pytest.raises(DataFetchError, match="ASX-first"):
        manager.get_daily_data("600519", days=5)

    assert cn_fetcher.calls == 0
    assert yf_fetcher.calls == 0


def test_yfinance_asx_first_conversion_preserves_ax_and_rejects_numeric_default():
    fetcher = YfinanceFetcher()

    assert fetcher._convert_stock_code("BHP.AX") == "BHP.AX"
    assert fetcher._convert_stock_code("BHP") == "BHP.AX"
    with pytest.raises(DataFetchError, match="ASX-first"):
        fetcher._convert_stock_code("600519")


def test_yfinance_explicit_cn_mode_preserves_legacy_numeric_conversion():
    fetcher = YfinanceFetcher(market_calendar="CN")

    assert fetcher._convert_stock_code("600519") == "600519.SS"
    assert fetcher._convert_stock_code("000001") == "000001.SZ"


def test_market_symbol_classifier():
    assert DataFetcherManager._is_au_us_symbol("CBA.AX") is True
    assert DataFetcherManager._is_au_us_symbol("AAPL") is True
    assert DataFetcherManager._is_au_us_symbol("MSFT.US") is True
    assert DataFetcherManager._is_au_us_symbol("600519") is False
    assert DataFetcherManager._is_au_us_symbol("HK00700") is False


def test_realtime_asx_routes_to_yfinance_first():
    yf_quote = UnifiedRealtimeQuote(
        code="CBA.AX",
        name="CBA",
        price=123.45,
        source=RealtimeSource.YFINANCE,
        volume_ratio=1.3,
        turnover_rate=2.1,
    )
    yf_fetcher = DummyRealtimeFetcher("YfinanceFetcher", priority=1, quote=yf_quote)
    cn_fetcher = DummyRealtimeFetcher("EfinanceFetcher", priority=2, quote=None)
    manager = DataFetcherManager(fetchers=[yf_fetcher, cn_fetcher])

    with patch("src.config.get_config", return_value=SimpleNamespace(enable_realtime_quote=True, realtime_source_priority="efinance")):
        quote = manager.get_realtime_quote("CBA.AX")

    assert quote is yf_quote
    assert yf_fetcher.realtime_calls == 1
    assert cn_fetcher.realtime_calls == 0


def test_realtime_us_routing_behavior_preserved():
    yf_quote = UnifiedRealtimeQuote(
        code="AAPL",
        name="Apple",
        price=200.0,
        source=RealtimeSource.YFINANCE,
        volume_ratio=1.1,
        turnover_rate=0.9,
    )
    yf_fetcher = DummyRealtimeFetcher("YfinanceFetcher", priority=1, quote=yf_quote)
    cn_fetcher = DummyRealtimeFetcher("EfinanceFetcher", priority=2, quote=None)
    manager = DataFetcherManager(fetchers=[yf_fetcher, cn_fetcher])

    with patch("src.config.get_config", return_value=SimpleNamespace(enable_realtime_quote=True, realtime_source_priority="efinance")):
        quote = manager.get_realtime_quote("AAPL")

    assert quote is yf_quote
    assert yf_fetcher.realtime_calls == 1
    assert cn_fetcher.realtime_calls == 0


def test_realtime_dotted_us_symbol_routes_to_yfinance():
    yf_quote = UnifiedRealtimeQuote(
        code="BRK.B",
        name="Berkshire Hathaway",
        price=500.0,
        source=RealtimeSource.YFINANCE,
        volume_ratio=1.0,
        turnover_rate=0.8,
    )
    yf_fetcher = DummyRealtimeFetcher("YfinanceFetcher", priority=1, quote=yf_quote)
    cn_fetcher = DummyRealtimeFetcher("EfinanceFetcher", priority=2, quote=None)
    manager = DataFetcherManager(fetchers=[yf_fetcher, cn_fetcher])

    with patch("src.config.get_config", return_value=SimpleNamespace(enable_realtime_quote=True, realtime_source_priority="efinance")):
        quote = manager.get_realtime_quote("BRK.B")

    assert quote is yf_quote
    assert yf_fetcher.realtime_calls == 1
    assert cn_fetcher.realtime_calls == 0


def test_realtime_yfinance_none_then_fallback_source():
    yf_fetcher = DummyRealtimeFetcher("YfinanceFetcher", priority=1, quote=None)
    fallback_quote = UnifiedRealtimeQuote(code="BRK.B", name="FallbackQuote", price=498.0)
    cn_fetcher = DummyRealtimeFetcher("EfinanceFetcher", priority=2, quote=fallback_quote)
    manager = DataFetcherManager(fetchers=[yf_fetcher, cn_fetcher])

    with patch("src.config.get_config", return_value=SimpleNamespace(enable_realtime_quote=True, realtime_source_priority="efinance")):
        quote = manager.get_realtime_quote("BRK.B")

    assert quote is fallback_quote
    assert yf_fetcher.realtime_calls == 1
    assert cn_fetcher.realtime_calls == 1


def test_realtime_yfinance_partial_quote_gets_supplemented_by_later_source():
    yf_quote = UnifiedRealtimeQuote(
        code="CBA.AX",
        name="CBA",
        price=123.45,
        source=RealtimeSource.YFINANCE,
        volume_ratio=None,
        turnover_rate=None,
    )
    supplemental_quote = UnifiedRealtimeQuote(
        code="CBA.AX",
        name="CBA",
        price=123.40,
        source=RealtimeSource.EFINANCE,
        volume_ratio=1.8,
        turnover_rate=3.2,
    )
    yf_fetcher = DummyRealtimeFetcher("YfinanceFetcher", priority=1, quote=yf_quote)
    cn_fetcher = DummyRealtimeFetcher("EfinanceFetcher", priority=2, quote=supplemental_quote)
    manager = DataFetcherManager(fetchers=[yf_fetcher, cn_fetcher])

    with patch("src.config.get_config", return_value=SimpleNamespace(enable_realtime_quote=True, realtime_source_priority="efinance")):
        quote = manager.get_realtime_quote("CBA.AX")

    assert quote is yf_quote
    assert quote.source == RealtimeSource.YFINANCE
    assert quote.volume_ratio == 1.8
    assert quote.turnover_rate == 3.2
    assert yf_fetcher.realtime_calls == 1
    assert cn_fetcher.realtime_calls == 1
