# -*- coding: utf-8 -*-
"""Conditional plan-point helpers for non-executable report display."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


PLAN_POINT_ORDER = ("ideal_buy", "secondary_buy", "stop_loss", "take_profit")

PLAN_POINT_DISPLAY_LABELS = {
    "ideal_buy": "理想买入观察位",
    "secondary_buy": "次优买入观察位",
    "stop_loss": "风险失效观察位",
    "take_profit": "止盈观察位",
}

DEFAULT_TRIGGER_CONDITION = "开盘后价格仍在允许偏离范围内，且无新增重大利空。"
DEFAULT_INVALIDATION = "跌破关键均线 / 出现 price-sensitive 利空 / 开盘跳空超过阈值。"
DEFAULT_MANUAL_REVIEW = "必须人工复核实时价格、公告、新闻和流动性。"
AI_UNVERIFIED_SOURCE_DETAIL = "AI 提取，未验证；仅作观察参考，不作为执行价格。"


@dataclass(frozen=True)
class ConditionalPlanPoint:
    label: str
    price: Optional[float]
    source_type: str
    source_detail: str
    condition: str
    invalidation: str
    requires_manual_review: bool
    price_basis: str
    technical_basis_date: str
    raw_value: str


def build_conditional_plan_points(
    raw_points: Dict[str, Any],
    *,
    price_basis: str,
    technical_basis_date: str,
    validation_status: str = "PASS",
    reference_price: Optional[float] = None,
) -> List[ConditionalPlanPoint]:
    """Normalize AI/dashboard price references into non-executable plan points."""
    if str(validation_status or "").upper() == "BLOCK":
        return []

    normalized_basis = _normalize_price_basis(price_basis)
    basis_date = str(technical_basis_date or "unknown")
    points: List[ConditionalPlanPoint] = []

    for label in PLAN_POINT_ORDER:
        value = (raw_points or {}).get(label)
        if _is_unavailable(value):
            continue
        point = _build_point(
            label=label,
            value=value,
            price_basis=normalized_basis,
            technical_basis_date=basis_date,
            reference_price=reference_price,
        )
        points.append(point)

    return points


def render_conditional_plan_points_markdown(points: List[ConditionalPlanPoint]) -> List[str]:
    """Render conditional plan points as a markdown table for detailed reports."""
    if not points:
        return []

    lines = [
        "**条件化计划点位（非执行，仅供人工复核）**",
        "",
        "| 点位 | 价格/参考 | 来源 | 触发条件 | 失效条件 | 执行前 | 价格口径 | 技术基准日 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for point in points:
        lines.append(
            "| "
            f"{_cell(PLAN_POINT_DISPLAY_LABELS.get(point.label, point.label))} | "
            f"{_cell(_display_value(point))} | "
            f"{_cell(point.source_detail)} | "
            f"{_cell(point.condition)} | "
            f"{_cell(point.invalidation)} | "
            f"{_cell(DEFAULT_MANUAL_REVIEW if point.requires_manual_review else '人工复核状态未声明。')} | "
            f"{_cell(point.price_basis)} | "
            f"{_cell(point.technical_basis_date)} |"
        )
    lines.append("")
    return lines


def format_conditional_plan_points_inline(points: List[ConditionalPlanPoint]) -> str:
    """Render a compact observation-line version without executable wording."""
    if not points:
        return "暂无明确条件化观察位"

    fragments = []
    for point in points[:3]:
        fragments.append(
            f"{PLAN_POINT_DISPLAY_LABELS.get(point.label, point.label)} {_display_value(point)}"
            f"（来源：{point.source_detail}；触发条件：{point.condition}；"
            f"失效条件：{point.invalidation}；执行前：{DEFAULT_MANUAL_REVIEW}）"
        )
    return " | ".join(fragments)


def _build_point(
    *,
    label: str,
    value: Any,
    price_basis: str,
    technical_basis_date: str,
    reference_price: Optional[float],
) -> ConditionalPlanPoint:
    if isinstance(value, dict):
        raw_value = _stringify(value.get("price") or value.get("value") or value.get("raw_value") or "")
        source_type = _normalize_source_type(value.get("source_type")) or _infer_source_type(value)
        source_detail = _source_detail_for(source_type, value.get("source_detail") or raw_value)
        condition = _stringify(value.get("condition")) or DEFAULT_TRIGGER_CONDITION
        invalidation = _stringify(value.get("invalidation")) or DEFAULT_INVALIDATION
        requires_manual_review = bool(value.get("requires_manual_review", True))
        price = _coerce_price(value.get("price") or value.get("value") or raw_value, reference_price=reference_price)
    else:
        raw_value = _stringify(value)
        source_type = _infer_source_type(raw_value)
        source_detail = _source_detail_for(source_type, raw_value)
        condition = DEFAULT_TRIGGER_CONDITION
        invalidation = DEFAULT_INVALIDATION
        requires_manual_review = True
        price = _coerce_price(raw_value, reference_price=reference_price)

    if price is not None and not _is_plausible_price(price, reference_price):
        source_detail = (
            "提取数值与昨收价偏离过大，已隐藏；请人工复核原文："
            f"{_short_text(raw_value)}"
        )
        raw_value = "需人工复核（原始点位疑似不是股价）"
        price = None

    return ConditionalPlanPoint(
        label=label,
        price=price,
        source_type=source_type,
        source_detail=source_detail,
        condition=condition,
        invalidation=invalidation,
        requires_manual_review=requires_manual_review,
        price_basis=price_basis,
        technical_basis_date=technical_basis_date,
        raw_value=raw_value,
    )


def _normalize_price_basis(value: str) -> str:
    return "close_only" if str(value or "").strip() == "close_only" else "non_executable_reference"


def _normalize_source_type(value: Any) -> str:
    source = str(value or "").strip()
    return source if source in {"ma", "atr", "prior_high_low", "ai_extracted", "unavailable"} else ""


def _infer_source_type(value: Any) -> str:
    text = str(value or "").lower()
    if "atr" in text:
        return "atr"
    if "ma" in text or "均线" in text:
        return "ma"
    if "前高" in text or "前低" in text or "prior" in text or "high" in text or "low" in text:
        return "prior_high_low"
    return "ai_extracted"


def _source_detail_for(source_type: str, raw_value: Any) -> str:
    detail = _stringify(raw_value)
    if source_type == "ma":
        return f"MA / 均线：{detail}" if detail else "MA / 均线"
    if source_type == "atr":
        return f"ATR：{detail}" if detail else "ATR"
    if source_type == "prior_high_low":
        return f"前高前低：{detail}" if detail else "前高前低"
    if source_type == "unavailable":
        return "来源不可用；仅作观察参考，不作为执行价格。"
    return AI_UNVERIFIED_SOURCE_DETAIL


def _display_value(point: ConditionalPlanPoint) -> str:
    if point.price is not None:
        return f"{point.price:.2f}"
    return point.raw_value or "-"


def _coerce_price(value: Any, *, reference_price: Optional[float] = None) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    text = str(value)
    matches = list(re.finditer(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?", text))
    if not matches:
        return None
    candidates = []
    for match in matches:
        parsed = float(match.group(0))
        if math.isfinite(parsed):
            candidates.append(parsed)
    if not candidates:
        return None
    plausible = [candidate for candidate in candidates if _is_plausible_price(candidate, reference_price)]
    if plausible and reference_price is not None and reference_price > 0:
        return min(plausible, key=lambda candidate: abs(candidate - reference_price))
    parsed = candidates[0]
    return parsed if math.isfinite(parsed) else None


def _is_plausible_price(price: float, reference_price: Optional[float]) -> bool:
    if reference_price is None or not math.isfinite(reference_price) or reference_price <= 0:
        return True
    ratio = price / reference_price
    return 0.4 <= ratio <= 2.5


def _short_text(value: Any, limit: int = 80) -> str:
    text = " ".join(_stringify(value).split())
    if len(text) <= limit:
        return text or "-"
    return text[: limit - 3].rstrip() + "..."


def _is_unavailable(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() in {"", "-", "N/A", "n/a", "NA", "null", "None"}
    return False


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _cell(value: Any) -> str:
    text = _stringify(value) or "-"
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("|", r"\|")
    return text.replace("\n", "<br>")
