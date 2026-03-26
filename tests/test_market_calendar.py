from datetime import datetime

import pandas as pd

from src.market_calendar import (
    get_last_closed_trading_date,
    is_market_closed,
    is_trading_day,
)
from data_provider.base import BaseFetcher


class CaptureFetcher(BaseFetcher):
    name = "CaptureFetcher"
    priority = 1

    def __init__(self):
        self.last_start = None
        self.last_end = None

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        self.last_start = start_date
        self.last_end = end_date
        return pd.DataFrame(
            {
                "date": ["2026-03-20"],
                "open": [1.0],
                "high": [1.0],
                "low": [1.0],
                "close": [1.0],
                "volume": [100],
                "amount": [100],
                "pct_chg": [0.0],
            }
        )

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        return df


class DummyConfig:
    market_calendar = "ASX"
    market_timezone = "Australia/Sydney"


def test_asx_non_trading_day_weekend():
    assert is_trading_day(datetime(2026, 3, 28).date(), "ASX") is False  # Saturday


def test_asx_closed_vs_not_closed_with_timezone_boundary():
    # 2026-03-26 04:30 UTC => 15:30 Sydney (not closed yet)
    not_closed = datetime(2026, 3, 26, 4, 30, 0)
    assert is_market_closed(not_closed, calendar="ASX", market_timezone="Australia/Sydney") is False

    # 2026-03-26 06:30 UTC => 17:30 Sydney (closed)
    closed = datetime(2026, 3, 26, 6, 30, 0)
    assert is_market_closed(closed, calendar="ASX", market_timezone="Australia/Sydney") is True


def test_last_closed_trading_day_before_close_rolls_back():
    # Friday 2026-03-27 02:00 UTC => 13:00 Sydney (before close)
    now_utc = datetime(2026, 3, 27, 2, 0, 0)
    last_closed = get_last_closed_trading_date(
        now_utc,
        calendar="ASX",
        market_timezone="Australia/Sydney",
    )
    assert last_closed.isoformat() == "2026-03-26"


def test_last_closed_trading_day_on_monday_uses_previous_friday():
    # Monday 2026-03-30 00:30 UTC => 11:30 Sydney (before close)
    now_utc = datetime(2026, 3, 30, 0, 30, 0)
    last_closed = get_last_closed_trading_date(
        now_utc,
        calendar="ASX",
        market_timezone="Australia/Sydney",
    )
    assert last_closed.isoformat() == "2026-03-27"


def test_base_fetcher_end_date_uses_last_closed_trading_day(monkeypatch):
    import src.config as config_module

    monkeypatch.setattr(config_module, "get_config", lambda: DummyConfig())

    fetcher = CaptureFetcher()
    fetcher.get_daily_data("CBA.AX", end_date=None, days=5)

    assert fetcher.last_end is not None
    parsed = datetime.strptime(fetcher.last_end, "%Y-%m-%d")
    # Should always resolve to a weekday trading date in ASX calendar
    assert parsed.weekday() < 5
