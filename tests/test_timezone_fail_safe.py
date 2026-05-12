# -*- coding: utf-8 -*-

from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import src.core.market_review as market_review_module
import src.core.pipeline as pipeline_module


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        fixed = datetime(2026, 4, 5, 15, 30, 0, tzinfo=ZoneInfo("UTC"))
        if tz is None:
            return fixed.replace(tzinfo=None)
        return fixed.astimezone(tz)


def test_pipeline_invalid_timezone_falls_back_to_sydney_not_naive_local(monkeypatch):
    monkeypatch.setattr(pipeline_module, "datetime", FixedDateTime)

    market_now = pipeline_module._now_in_timezone_safe("Invalid/Timezone")

    assert market_now.date() == date(2026, 4, 6)
    assert getattr(market_now.tzinfo, "key", None) == "Australia/Sydney"


def test_pipeline_report_run_date_uses_sydney_when_config_timezone_invalid(monkeypatch):
    monkeypatch.setattr(pipeline_module, "datetime", FixedDateTime)
    config = SimpleNamespace(market_timezone="Invalid/Timezone")

    assert pipeline_module._report_run_date_safe(config) == date(2026, 4, 6)


def test_pipeline_market_report_date_uses_sydney_when_config_timezone_invalid(monkeypatch):
    monkeypatch.setattr(pipeline_module, "datetime", FixedDateTime)
    config = SimpleNamespace(market_calendar="ASX", market_timezone="Invalid/Timezone")

    assert pipeline_module._market_report_date_safe(config) == date(2026, 4, 2)


def test_market_review_invalid_timezone_falls_back_to_sydney_not_naive_local(monkeypatch):
    monkeypatch.setattr(market_review_module, "datetime", FixedDateTime)

    market_now = market_review_module._now_in_market_tz("Invalid/Timezone")

    assert market_now.date() == date(2026, 4, 6)
    assert getattr(market_now.tzinfo, "key", None) == "Australia/Sydney"


def test_market_review_archive_filename_uses_sydney_when_config_timezone_invalid(monkeypatch):
    class DummyNotifier:
        def __init__(self):
            self.filename = None

        def save_report_to_file(self, _content, filename):
            self.filename = filename
            return "/tmp/report.md"

        def is_available(self):
            return False

    notifier = DummyNotifier()
    monkeypatch.setattr(market_review_module, "datetime", FixedDateTime)
    monkeypatch.setattr(
        market_review_module,
        "get_config",
        lambda: SimpleNamespace(
            market_timezone="Invalid/Timezone",
            market_review_push_enabled=False,
        ),
    )
    monkeypatch.setattr(
        market_review_module,
        "MarketAnalyzer",
        lambda **_kwargs: SimpleNamespace(run_daily_review=lambda: "review body"),
    )

    market_review_module.run_market_review(notifier, send_notification=False)

    assert notifier.filename == "market_review_20260406.md"
