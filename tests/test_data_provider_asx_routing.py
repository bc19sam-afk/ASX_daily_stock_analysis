import pandas as pd

from data_provider.base import BaseFetcher, DataFetcherManager


class DummyFetcher(BaseFetcher):
    def __init__(self, name: str, priority: int = 1):
        self.name = name
        self.priority = priority
        self.calls = 0

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        raise NotImplementedError

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        raise NotImplementedError

    def get_daily_data(self, stock_code: str, start_date=None, end_date=None, days: int = 30) -> pd.DataFrame:
        self.calls += 1
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
    manager = DataFetcherManager(fetchers=[cn_fetcher, yf_fetcher])

    _, source = manager.get_daily_data("600519", days=5)

    assert source == "TushareFetcher"
    assert cn_fetcher.calls == 1
    assert yf_fetcher.calls == 0


def test_market_symbol_classifier():
    assert DataFetcherManager._is_au_us_symbol("CBA.AX") is True
    assert DataFetcherManager._is_au_us_symbol("AAPL") is True
    assert DataFetcherManager._is_au_us_symbol("MSFT.US") is True
    assert DataFetcherManager._is_au_us_symbol("600519") is False
    assert DataFetcherManager._is_au_us_symbol("HK00700") is False
