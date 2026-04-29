import sys
from datetime import datetime as real_datetime, timezone
from types import SimpleNamespace

import pandas as pd

import src.market_analyzer as market_analyzer_module
from src.market_analyzer import MarketAnalyzer, MarketOverview, MarketIndex


class _FixedSydneyBoundaryDateTime(real_datetime):
    @classmethod
    def now(cls, tz=None):
        fixed = real_datetime(2026, 4, 2, 15, 30, 0, tzinfo=timezone.utc)
        if tz is None:
            return fixed.replace(tzinfo=None)
        return fixed.astimezone(tz)


class _DummyAnalyzer:
    def is_available(self):
        return True

    def _call_api_with_retry(self, prompt, generation_config):
        return """## 📊 2026-04-03 澳股及全球宏观复盘

### 一、宏观与大盘总结
测试内容

### 二、指数与商品点评
测试内容

### 三、热点与风险解读
测试内容

### 四、后市展望
测试内容
"""


def test_market_overview_date_uses_configured_market_timezone(monkeypatch):
    monkeypatch.setattr(market_analyzer_module, "datetime", _FixedSydneyBoundaryDateTime)

    analyzer = MarketAnalyzer()
    analyzer.config = SimpleNamespace(market_timezone="Australia/Sydney")
    analyzer._get_main_indices = lambda: []

    overview = analyzer.get_market_overview()

    assert overview.date == "2026-04-03"


def test_market_overview_invalid_timezone_falls_back_to_sydney(monkeypatch):
    monkeypatch.setattr(market_analyzer_module, "datetime", _FixedSydneyBoundaryDateTime)

    analyzer = MarketAnalyzer()
    analyzer.config = SimpleNamespace(market_timezone="Invalid/Timezone")
    analyzer._get_main_indices = lambda: []

    overview = analyzer.get_market_overview()

    assert overview.date == "2026-04-03"


def test_template_review_time_uses_configured_market_timezone(monkeypatch):
    monkeypatch.setattr(market_analyzer_module, "datetime", _FixedSydneyBoundaryDateTime)

    analyzer = MarketAnalyzer()
    analyzer.config = SimpleNamespace(market_timezone="Australia/Sydney")
    overview = MarketOverview(date="2026-04-03")

    report = analyzer._generate_template_review(overview, news=[])

    assert "*复盘时间: 02:30*" in report


def test_template_review_none_timezone_falls_back_to_sydney(monkeypatch):
    monkeypatch.setattr(market_analyzer_module, "datetime", _FixedSydneyBoundaryDateTime)

    analyzer = MarketAnalyzer()
    analyzer.config = SimpleNamespace(market_timezone=None)
    overview = MarketOverview(date="2026-04-03")

    report = analyzer._generate_template_review(overview, news=[])

    assert "*复盘时间: 02:30*" in report


def test_template_review_hides_zero_like_placeholder_when_stats_missing():
    analyzer = MarketAnalyzer()
    overview = MarketOverview(
        date="2026-04-03",
        indices=[MarketIndex(code="^AXJO", name="ASX 200", current=7700, change_pct=0.1)],
    )

    report = analyzer._generate_template_review(overview, news=[])

    assert "上涨家数 | 0" not in report
    assert "下跌家数 | 0" not in report
    assert "关键统计（涨跌家数/涨跌停/成交额）暂不可用" in report
    assert "板块涨跌榜暂不可用" in report


def test_template_review_keeps_validated_zero_values():
    analyzer = MarketAnalyzer()
    overview = MarketOverview(
        date="2026-04-03",
        market_stats_available=True,
        sector_rankings_available=True,
        up_count=0,
        down_count=0,
        flat_count=100,
        limit_up_count=0,
        limit_down_count=0,
        total_amount=0.0,
    )

    report = analyzer._generate_template_review(overview, news=[])

    assert "上涨家数 | 0" in report
    assert "下跌家数 | 0" in report
    assert "ASX 成交额 | 0亿" in report


def test_generate_market_review_injects_unavailable_notice_when_upstream_stats_missing():
    analyzer = MarketAnalyzer(analyzer=_DummyAnalyzer())
    overview = MarketOverview(
        date="2026-04-03",
        indices=[MarketIndex(code="^AXJO", name="ASX 200", current=7700, prev_close=7680, high=7710, low=7670)],
    )

    report = analyzer.generate_market_review(overview, news=[])

    assert "市场广度/成交额统计暂不可用" in report
    assert "领涨/领跌板块统计暂不可用" in report


def test_market_review_prompt_is_dedicated_markdown_prompt():
    analyzer = MarketAnalyzer()
    overview = MarketOverview(date="2026-04-03")

    prompt = analyzer._build_review_prompt(overview, news=[])

    assert "澳股及全球宏观复盘" in prompt
    assert "禁止输出 JSON 格式" in prompt
    assert "市场广度与成交额统计" in prompt
    assert "关键统计缺失" in prompt


class _FakeYfinanceTicker:
    def history(self, *args, **kwargs):
        df = pd.DataFrame(
            {
                "Open": [100.0, 101.0],
                "High": [102.0, 104.0],
                "Low": [99.0, 100.0],
                "Close": [101.0, 103.0],
                "Volume": [1000, 1200],
            },
            index=pd.to_datetime(["2026-04-27", "2026-04-28"]),
        )
        df.index.name = "Date"
        return df


def test_market_indices_include_data_date_and_source_basis(monkeypatch):
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=lambda _code: _FakeYfinanceTicker()))

    analyzer = MarketAnalyzer()
    indices = analyzer._get_main_indices()

    assert indices
    assert {idx.data_date for idx in indices} == {"2026-04-28"}
    assert {idx.source_basis for idx in indices} == {"latest_yfinance_bar"}
    assert indices[0].to_dict()["data_date"] == "2026-04-28"


def test_market_review_prompt_labels_mixed_macro_dates():
    analyzer = MarketAnalyzer()
    overview = MarketOverview(
        date="2026-04-29",
        indices=[
            MarketIndex(
                code="^AXJO",
                name="ASX 200",
                current=7700,
                prev_close=7680,
                high=7710,
                low=7670,
                data_date="2026-04-29",
                source_basis="latest_yfinance_bar",
            ),
            MarketIndex(
                code="^GSPC",
                name="标普 500 (美股)",
                current=5200,
                prev_close=5150,
                high=5220,
                low=5130,
                data_date="2026-04-28",
                source_basis="latest_yfinance_bar",
            ),
        ],
    )

    prompt = analyzer._build_review_prompt(overview, news=[])
    table = analyzer._build_indices_block(overview)

    assert "数据日期分别为：2026-04-28, 2026-04-29" in prompt
    assert "不要表述为同一交易日口径" in prompt
    assert "| 指数/商品 | 最新价 | 涨跌幅 | 日内振幅 | 数据日期 | 口径 |" in table
    assert "latest_yfinance_bar" in table


class _SectorRankingFetcher:
    def __init__(self, rankings):
        self.rankings = rankings

    def get_sector_rankings(self, limit):
        return self.rankings


def test_sector_rankings_empty_pair_is_unavailable():
    analyzer = MarketAnalyzer()
    analyzer.data_manager = _SectorRankingFetcher(([], []))
    overview = MarketOverview(date="2026-04-03")

    analyzer._get_sector_rankings(overview)

    assert overview.sector_rankings_available is False
    assert overview.top_sectors == []
    assert overview.bottom_sectors == []


def test_sector_rankings_none_is_unavailable():
    analyzer = MarketAnalyzer()
    analyzer.data_manager = _SectorRankingFetcher(None)
    overview = MarketOverview(date="2026-04-03")

    analyzer._get_sector_rankings(overview)

    assert overview.sector_rankings_available is False
    assert overview.top_sectors == []
    assert overview.bottom_sectors == []


def test_sector_rankings_non_empty_is_available():
    analyzer = MarketAnalyzer()
    analyzer.data_manager = _SectorRankingFetcher((
        [{"name": "Materials", "change_pct": 1.25}],
        [{"name": "Utilities", "change_pct": -0.86}],
    ))
    overview = MarketOverview(date="2026-04-03")

    analyzer._get_sector_rankings(overview)

    assert overview.sector_rankings_available is True
    assert overview.top_sectors[0]["name"] == "Materials"
    assert overview.bottom_sectors[0]["name"] == "Utilities"
