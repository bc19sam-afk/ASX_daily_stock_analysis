from datetime import datetime, timezone

import main
from src.config import Config


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        fixed = datetime(2026, 3, 26, 7, 15, 0, tzinfo=timezone.utc)
        if tz is None:
            return fixed.replace(tzinfo=None)
        return fixed.astimezone(tz)


def _make_config(require_market_closed: bool) -> Config:
    return Config(
        market_calendar="ASX",
        market_timezone="Australia/Sydney",
        require_market_closed=require_market_closed,
    )


def test_should_skip_non_trading_day(monkeypatch):
    monkeypatch.setattr(main, "datetime", FixedDateTime)
    monkeypatch.setattr(main, "is_trading_day", lambda _d, _c: False)

    called = {"market_closed": 0}

    def _is_market_closed(*args, **kwargs):
        called["market_closed"] += 1
        return True

    monkeypatch.setattr(main, "is_market_closed", _is_market_closed)

    assert main._should_skip_for_market_window(_make_config(require_market_closed=False)) is True
    assert called["market_closed"] == 0


def test_should_not_require_market_closed_by_default(monkeypatch):
    monkeypatch.setattr(main, "datetime", FixedDateTime)
    monkeypatch.setattr(main, "is_trading_day", lambda _d, _c: True)

    called = {"market_closed": 0}

    def _is_market_closed(*args, **kwargs):
        called["market_closed"] += 1
        return False

    monkeypatch.setattr(main, "is_market_closed", _is_market_closed)

    assert main._should_skip_for_market_window(_make_config(require_market_closed=False)) is False
    assert called["market_closed"] == 0


def test_should_skip_when_require_market_closed_enabled(monkeypatch):
    monkeypatch.setattr(main, "datetime", FixedDateTime)
    monkeypatch.setattr(main, "is_trading_day", lambda _d, _c: True)
    monkeypatch.setattr(main, "is_market_closed", lambda *_a, **_k: False)

    assert main._should_skip_for_market_window(_make_config(require_market_closed=True)) is True


def test_logs_market_local_time_explicitly(monkeypatch, caplog):
    monkeypatch.setattr(main, "datetime", FixedDateTime)
    monkeypatch.setattr(main, "is_trading_day", lambda _d, _c: True)

    called = {"market_closed": 0}

    def _is_market_closed(*args, **kwargs):
        called["market_closed"] += 1
        return True

    monkeypatch.setattr(main, "is_market_closed", _is_market_closed)

    caplog.set_level("INFO")
    assert main._should_skip_for_market_window(_make_config(require_market_closed=True)) is False
    assert called["market_closed"] == 1
    assert "市场本地时间(Australia/Sydney)=" in caplog.text
    assert "2026-03-26T18:15:00+11:00" in caplog.text


def test_config_loads_require_market_closed_from_env(monkeypatch):
    Config.reset_instance()
    monkeypatch.setenv("REQUIRE_MARKET_CLOSED", "true")

    cfg = Config.get_instance()
    assert cfg.require_market_closed is True

    Config.reset_instance()
    monkeypatch.setenv("REQUIRE_MARKET_CLOSED", "false")

    cfg = Config.get_instance()
    assert cfg.require_market_closed is False
    Config.reset_instance()
