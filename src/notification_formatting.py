# -*- coding: utf-8 -*-
"""Pure formatting helpers extracted from NotificationService."""

from __future__ import annotations

import re
from typing import Any


def format_price_basis_label(basis: str) -> str:
    return {
        "realtime": "实时价格",
        "latest_close": "最新收盘",
        "close_only": "仅收盘口径（无实时价格）",
    }.get(basis, "仅收盘口径（无实时价格）")


def format_valuation_source_label(source: str) -> str:
    return {
        "report_time_price": "报告时点价格",
        "stored_market_value_fallback": "账户快照市值回退",
    }.get(source, "账户快照市值回退")


def format_yes_no_label(flag: Any) -> str:
    return "是" if bool(flag) else "否"


def format_position_action_label(action: str) -> str:
    action_text = str(action or "").strip().upper()
    return {
        "OPEN": "建议新开仓",
        "ADD": "加仓",
        "HOLD": "持有观察",
        "TRIM": "减仓",
        "REDUCE": "减仓",
        "CLOSE": "清仓",
    }.get(action_text, action_text or "持有")


def format_stock_display_name(raw_name: Any, raw_code: Any) -> str:
    """Normalize noisy source names to a user-facing display title."""
    code = str(raw_code or "").strip().upper()
    if not code:
        code = "N/A"
    code_display = code

    name = str(raw_name or "").strip()
    if not name or name.startswith("股票"):
        name = code

    name = re.sub(r"\b(FPO|STAPLED|ORDINARY|ORD|UNITS?|UNIT)\b", " ", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+", " ", name).strip(" -_/")
    if code and name.upper().endswith(f" {code}"):
        name = name[: -(len(code) + 1)].strip()
    if not name:
        name = code
    return f"{name} ({code_display})"


def _format_percent(value: float) -> str:
    if value <= 0:
        return "0%"
    if value < 0.01:
        return f"{value * 100:.1f}%"
    return f"{value:.0%}"


def format_sizing_brief(target_weight: float, action: str = "") -> str:
    weight = float(target_weight or 0.0)
    action_text = str(action or "").strip().upper()

    if weight <= 0:
        if action_text in {"CLOSE", "REDUCE"}:
            return "目标仓位 0%（清空）"
        if action_text == "HOLD":
            return "目标仓位 0%（观察）"
        return "目标仓位 0%"
    if weight < 0.01:
        return f"试探仓位（约 {_format_percent(weight)}）"
    if weight < 0.05:
        return f"轻仓试探（约 {_format_percent(weight)}）"
    if weight < 0.15:
        return f"中低仓位（约 {_format_percent(weight)}）"
    if weight < 0.30:
        return f"中等仓位（约 {_format_percent(weight)}）"
    if weight < 0.50:
        return f"较高仓位（约 {_format_percent(weight)}，集中度偏高）"
    if weight < 0.80:
        return f"高仓位（约 {_format_percent(weight)}，集中度高）"
    return f"极高仓位（约 {_format_percent(weight)}，单一标的暴露高）"
