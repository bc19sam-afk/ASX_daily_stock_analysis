# -*- coding: utf-8 -*-

import sys
from types import SimpleNamespace

import pandas as pd

from data_provider.yfinance_fetcher import YfinanceFetcher


class _FakeTicker:
    info = {}

    def history(self, *args, **kwargs):
        df = pd.DataFrame(
            {
                "Open": [10.0, 10.5, 11.0],
                "High": [10.2, 10.8, 11.4],
                "Low": [9.8, 10.1, 10.9],
                "Close": [10.1, 10.7, 11.2],
                "Volume": [1000, 1200, 1500],
            },
            index=pd.to_datetime(["2026-04-27", "2026-04-28", "2026-04-29"]),
        )
        df.index.name = "Date"
        return df


def test_default_yfinance_daily_pull_trims_after_last_closed_date(monkeypatch):
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=lambda _symbol: _FakeTicker()))
    monkeypatch.setattr(
        YfinanceFetcher,
        "_resolve_default_daily_cutoff",
        staticmethod(lambda: "2026-04-28"),
    )
    monkeypatch.setattr(YfinanceFetcher, "_get_enhanced_data", lambda self, _code, df: df)

    df = YfinanceFetcher().get_daily_data("CBA.AX", days=3)

    assert df["date"].tolist() == ["2026-04-27", "2026-04-28"]
    assert "2026-04-29" not in set(df["date"])
