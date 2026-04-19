# -*- coding: utf-8 -*-
"""Lightweight market calendar/timezone helpers for AU/US daily workflows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date, time, timedelta
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


def is_trading_day(target_date: date, calendar: str | None = "ASX") -> bool:
    """Minimal trading-day check: weekdays only (Mon-Fri)."""
    return target_date.weekday() < 5


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
