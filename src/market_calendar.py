# -*- coding: utf-8 -*-
"""Lightweight market calendar/timezone helpers for AU/US daily workflows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class MarketRules:
    timezone: str
    open_time: time
    close_time: time


_RULES = {
    "ASX": MarketRules(timezone="Australia/Sydney", open_time=time(10, 0), close_time=time(16, 0)),
    "NYSE": MarketRules(timezone="America/New_York", open_time=time(9, 30), close_time=time(16, 0)),
    "US": MarketRules(timezone="America/New_York", open_time=time(9, 30), close_time=time(16, 0)),
}


def _calendar_key(calendar: str | None) -> str:
    return (calendar or "ASX").strip().upper()


def resolve_market_timezone(calendar: str | None, configured_timezone: str | None = None) -> str:
    """Resolve market timezone from config override or calendar defaults."""
    if configured_timezone and configured_timezone.strip():
        return configured_timezone.strip()
    key = _calendar_key(calendar)
    return _RULES.get(key, _RULES["ASX"]).timezone


def _rules(calendar: str | None, configured_timezone: str | None = None) -> MarketRules:
    key = _calendar_key(calendar)
    base = _RULES.get(key, _RULES["ASX"])
    tz = resolve_market_timezone(calendar, configured_timezone)
    return MarketRules(timezone=tz, open_time=base.open_time, close_time=base.close_time)


def _to_market_now(now: datetime | None, tz_name: str) -> datetime:
    tz = ZoneInfo(tz_name)
    if now is None:
        return datetime.now(tz)
    if now.tzinfo is None:
        # Treat naive datetime as UTC to avoid machine-local-time ambiguity.
        now = now.replace(tzinfo=ZoneInfo("UTC"))
    return now.astimezone(tz)


def _easter_sunday(year: int) -> date:
    """Return Gregorian Easter Sunday for the given year."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date:
    current = date(year, month, 1)
    offset = (weekday - current.weekday()) % 7
    return current + timedelta(days=offset + (n - 1) * 7)


def _add_observed_holiday(holidays: set[date], target: date) -> None:
    observed = target
    if target.weekday() == 5:
        observed = target + timedelta(days=2)
    elif target.weekday() == 6:
        observed = target + timedelta(days=1)

    while observed in holidays or observed.weekday() >= 5:
        observed += timedelta(days=1)
    holidays.add(observed)


@lru_cache(maxsize=None)
def _asx_cash_market_closed_dates(year: int) -> frozenset[date]:
    holidays: set[date] = set()
    easter = _easter_sunday(year)

    for fixed_day in (
        date(year, 1, 1),   # New Year's Day
        date(year, 1, 26),  # Australia Day
        date(year, 12, 25), # Christmas Day
        date(year, 12, 26), # Boxing Day
    ):
        _add_observed_holiday(holidays, fixed_day)

    holidays.update(
        {
            easter - timedelta(days=2),              # Good Friday
            easter + timedelta(days=1),              # Easter Monday
            date(year, 4, 25),                       # ANZAC Day, actual date only
            _nth_weekday_of_month(year, 6, 0, 2),    # King's Birthday (NSW)
        }
    )
    return frozenset(holidays)


def is_trading_day(target_date: date, calendar: str | None = "ASX") -> bool:
    """Return whether the date is a trading day for the supported market."""
    if target_date.weekday() >= 5:
        return False
    if _calendar_key(calendar) == "ASX":
        return target_date not in _asx_cash_market_closed_dates(target_date.year)
    return True


def is_market_closed(
    now: datetime | None = None,
    *,
    calendar: str | None = "ASX",
    market_timezone: str | None = None,
) -> bool:
    rules = _rules(calendar, market_timezone)
    local_now = _to_market_now(now, rules.timezone)
    if not is_trading_day(local_now.date(), calendar):
        return False
    return local_now.time() >= rules.close_time


def is_pre_market_open(
    now: datetime | None = None,
    *,
    calendar: str | None = "ASX",
    market_timezone: str | None = None,
) -> bool:
    """Return True when the market-local time is before the open on a trading day."""
    rules = _rules(calendar, market_timezone)
    local_now = _to_market_now(now, rules.timezone)
    if not is_trading_day(local_now.date(), calendar):
        return False
    return local_now.time() < rules.open_time


def get_last_closed_trading_date(
    now: datetime | None = None,
    *,
    calendar: str | None = "ASX",
    market_timezone: str | None = None,
) -> date:
    """Return most recent trading date that is already closed in market timezone."""
    rules = _rules(calendar, market_timezone)
    local_now = _to_market_now(now, rules.timezone)

    if is_trading_day(local_now.date(), calendar) and local_now.time() >= rules.close_time:
        candidate = local_now.date()
    else:
        candidate = local_now.date() - timedelta(days=1)

    while not is_trading_day(candidate, calendar):
        candidate -= timedelta(days=1)
    return candidate


def get_market_report_date(
    now: datetime | None = None,
    *,
    calendar: str | None = "ASX",
    market_timezone: str | None = None,
) -> date:
    """Return the closed-market basis date for cache checks and daily signals."""
    return get_last_closed_trading_date(
        now,
        calendar=calendar,
        market_timezone=market_timezone,
    )
