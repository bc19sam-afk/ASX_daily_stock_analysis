# -*- coding: utf-8 -*-
"""Validation gate for analysis/runtime basis consistency."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from src.market_calendar import get_last_closed_trading_date, is_trading_day


VALIDATION_STATUS_PASS = "PASS"
VALIDATION_STATUS_BLOCK = "BLOCK"


@dataclass(frozen=True)
class ValidationOutcome:
    validation_status: str = VALIDATION_STATUS_PASS
    validation_issues: List[str] = field(default_factory=list)
    blocked_reason: List[str] = field(default_factory=list)
    mixed_price_basis: bool = False
    stale_daily_context: bool = False
    missing_critical_data: bool = False


def normalize_validation_status(value: Any) -> str:
    """Normalize external validation status to the current PASS/BLOCK contract."""
    status = str(value or "").strip().upper()
    if status == VALIDATION_STATUS_BLOCK:
        return VALIDATION_STATUS_BLOCK
    return VALIDATION_STATUS_PASS


def evaluate_analysis_gate(
    *,
    enhanced_context: Optional[Dict[str, Any]],
    execution_price_source: str,
    current_price: Optional[float],
    market_timezone: str = "Australia/Sydney",
    market_calendar: str = "ASX",
    now: Optional[datetime] = None,
) -> ValidationOutcome:
    """Validate whether the result is safe to present as decisionable output."""
    context = enhanced_context or {}
    local_now = _to_market_now(now, market_timezone)
    context_date = _parse_date(context.get("date"))
    expected_daily_date = get_last_closed_trading_date(
        local_now,
        calendar=market_calendar,
        market_timezone=market_timezone,
    )
    today_close = _to_positive_float((context.get("today") or {}).get("close"))
    execution_price = _to_positive_float(current_price)
    issues: List[str] = []
    blocked_reason: List[str] = []
    mixed_price_basis = False
    stale_daily_context = False
    missing_critical_data = False

    if bool(context.get("data_missing")):
        issues.append("缺少完整日线分析上下文，当前结果不可用于决策。")
        missing_critical_data = True
    if context_date is None:
        issues.append("缺少日线基准日期，无法确认分析时间口径。")
        missing_critical_data = True
    if today_close is None:
        issues.append("缺少当日收盘价快照，无法建立稳定的日线信号基准。")
        missing_critical_data = True
    if execution_price is None:
        issues.append("缺少可用执行价格，无法形成可执行仓位动作。")
        missing_critical_data = True

    if context_date is not None and context_date < expected_daily_date:
        issues.append(
            f"日线基准已过期：当前仅有 {context_date.isoformat()}，但应至少更新到 {expected_daily_date.isoformat()}。"
        )
        stale_daily_context = True

    normalized_source = str(execution_price_source or "").strip().lower()
    if (
        normalized_source == "realtime"
        and context_date is not None
        and is_trading_day(local_now.date(), market_calendar)
        and context_date < local_now.date()
    ):
        issues.append(
            f"价格口径混用：信号基于 {context_date.isoformat()} 日线收盘，但执行价使用实时价格。"
        )
        mixed_price_basis = True

    if mixed_price_basis:
        blocked_reason.append("mixed_price_basis")
    if stale_daily_context:
        blocked_reason.append("stale_daily_context")
    if missing_critical_data:
        blocked_reason.append("missing_critical_data")

    if issues:
        return ValidationOutcome(
            validation_status=VALIDATION_STATUS_BLOCK,
            validation_issues=_dedupe(issues),
            blocked_reason=_dedupe(blocked_reason),
            mixed_price_basis=mixed_price_basis,
            stale_daily_context=stale_daily_context,
            missing_critical_data=missing_critical_data,
        )
    return ValidationOutcome(
        blocked_reason=[],
        mixed_price_basis=False,
        stale_daily_context=False,
        missing_critical_data=False,
    )


def _to_market_now(now: Optional[datetime], timezone_name: str) -> datetime:
    tz = ZoneInfo(timezone_name)
    if now is None:
        return datetime.now(tz)
    if now.tzinfo is None:
        return now.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz)
    return now.astimezone(tz)


def _parse_date(value: Any) -> Optional[date]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except Exception:
        pass
    try:
        return date.fromisoformat(text.split(" ")[0])
    except Exception:
        return None


def _to_positive_float(value: Any) -> Optional[float]:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric <= 0:
        return None
    return numeric


def _dedupe(items: List[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
