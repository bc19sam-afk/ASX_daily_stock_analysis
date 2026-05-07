# -*- coding: utf-8 -*-
"""Display-only free data quality snapshot for daily decision summaries."""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, List, Mapping, Optional


VALUATION_FIELDS = ("pe_ttm", "pe_forward", "pb", "dividend_yield", "market_cap")
SNAPSHOT_ATTENTION_LIMIT = 3


def build_data_quality_snapshot(
    *,
    successful_results: List[Any],
    failed_results: List[Any],
    evidence_matrix: Dict[str, List[Dict[str, Any]]],
    evidence_summary: Dict[str, Any],
    report_reliability: Dict[str, Any],
    data_quality_flags: List[Dict[str, Any]],
    price_basis_counts: Dict[str, int],
    technical_basis_dates: List[str],
    uncovered_holdings: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Summarize free/existing data quality signals without changing actions."""
    rows = [
        _row_from_result(result, evidence_matrix.get(_normalize_code(getattr(result, "code", ""))) or [])
        for result in successful_results
        if _normalize_code(getattr(result, "code", ""))
    ]
    field_coverage = {
        field: sum(1 for row in rows if row["valuation_fields"].get(field))
        for field in VALUATION_FIELDS
    }
    source_counts = Counter(
        str(row.get("market_source") or "unknown")
        for row in rows
    )
    market_attention = [
        _attention_item(row, "market_data")
        for row in rows
        if row["market_status"] != "available"
    ]
    valuation_attention = [
        _attention_item(row, "valuation")
        for row in rows
        if row["valuation_status"] != "available"
    ]
    news_attention = [
        _attention_item(row, "news")
        for row in rows
        if row["news_status"] in {"missing", "not_checked", "stale", "unavailable"}
    ]
    report_attention = _report_attention(
        data_quality_flags=data_quality_flags,
        report_reliability=report_reliability,
        failed_results=failed_results,
        uncovered_holdings=uncovered_holdings,
    )
    available_market = int(evidence_summary.get("market_data_available") or 0)
    stock_count = len(rows)
    valuation_available = sum(1 for row in rows if row["valuation_status"] == "available")
    news_available = sum(1 for row in rows if row["news_status"] == "available")

    return {
        "schema_version": "data_quality_snapshot.v1",
        "display_only": True,
        "free_sources": [
            "market_snapshot",
            "valuation_snapshot",
            "evidence_matrix",
            "report_reliability",
        ],
        "counts": {
            "stock_count": stock_count,
            "successful_count": len(successful_results),
            "failed_count": len(failed_results),
            "uncovered_holding_count": len(uncovered_holdings),
        },
        "market_data": {
            "available_count": available_market,
            "missing_or_stale_count": max(0, stock_count - available_market),
            "source_counts": dict(sorted(source_counts.items())),
            "price_basis_counts": dict(price_basis_counts),
            "technical_basis_dates": list(technical_basis_dates),
            "attention": market_attention[:SNAPSHOT_ATTENTION_LIMIT],
        },
        "valuation": {
            "available_count": valuation_available,
            "missing_count": max(0, stock_count - valuation_available),
            "field_coverage": field_coverage,
            "attention": valuation_attention[:SNAPSHOT_ATTENTION_LIMIT],
        },
        "news": {
            "available_count": news_available,
            "missing_or_stale_count": max(0, stock_count - news_available),
            "attention": news_attention[:SNAPSHOT_ATTENTION_LIMIT],
        },
        "report_reliability": {
            "score": report_reliability.get("score"),
            "level": report_reliability.get("level"),
            "top_flags": [
                {
                    "code": str(flag.get("code") or ""),
                    "severity": str(flag.get("severity") or "warning"),
                    "message": str(flag.get("message") or ""),
                }
                for flag in (report_reliability.get("flags") or [])[:3]
            ],
        },
        "attention": report_attention[:SNAPSHOT_ATTENTION_LIMIT],
    }


def render_data_quality_snapshot_lines(snapshot: Dict[str, Any]) -> List[str]:
    """Render a compact first-screen data quality card."""
    if not snapshot:
        return []
    counts = snapshot.get("counts") or {}
    stock_count = int(counts.get("stock_count") or 0)
    market = snapshot.get("market_data") or {}
    valuation = snapshot.get("valuation") or {}
    news = snapshot.get("news") or {}
    reliability = snapshot.get("report_reliability") or {}
    dates = market.get("technical_basis_dates") or []
    date_text = _date_range_text(dates)
    valuation_fields = valuation.get("field_coverage") or {}
    valuation_text = _format_field_coverage(valuation_fields, stock_count)
    attention = snapshot.get("attention") or []
    if not attention:
        attention_text = "无报告级数据注意项。"
    else:
        attention_text = "；".join(_compact(item.get("reason")) for item in attention if item.get("reason"))

    return [
        "",
        "**免费数据质量快照**",
        (
            f"- 行情：{int(market.get('available_count') or 0)}/{stock_count} 可用；"
            f"基准日 {date_text}。"
        ),
        (
            f"- 估值：{int(valuation.get('available_count') or 0)}/{stock_count} 有快照；"
            f"{valuation_text}。"
        ),
        f"- 新闻：{int(news.get('available_count') or 0)}/{stock_count} 有证据。",
        (
            f"- 可信度：{_score_text(reliability.get('score'))} "
            f"（{_reliability_label(reliability.get('level'))}）；{attention_text}"
        ),
    ]


def _row_from_result(result: Any, entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    code = _normalize_code(getattr(result, "code", ""))
    snapshot = getattr(result, "market_snapshot", None) or {}
    by_category = {str(entry.get("category") or ""): entry for entry in entries}
    valuation = _valuation_snapshot_dict(snapshot.get("valuation_snapshot"))
    valuation_fields = {
        field: _has_value(valuation.get(field)) if valuation else False
        for field in VALUATION_FIELDS
    }
    return {
        "code": code,
        "name": _display_name(result),
        "market_source": snapshot.get("source") or (by_category.get("market_data") or {}).get("source"),
        "market_status": str((by_category.get("market_data") or {}).get("status") or "missing"),
        "market_reason": str((by_category.get("market_data") or {}).get("details") or ""),
        "valuation_status": str((by_category.get("valuation") or {}).get("status") or "missing"),
        "valuation_reason": str((by_category.get("valuation") or {}).get("details") or ""),
        "valuation_fields": valuation_fields,
        "news_status": str((by_category.get("news") or {}).get("status") or "missing"),
        "news_reason": str((by_category.get("news") or {}).get("details") or ""),
    }


def _report_attention(
    *,
    data_quality_flags: List[Dict[str, Any]],
    report_reliability: Dict[str, Any],
    failed_results: List[Any],
    uncovered_holdings: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    attention: List[Dict[str, str]] = []
    for flag in data_quality_flags:
        message = str(flag.get("message") or "").strip()
        if message:
            attention.append(
                {
                    "code": str(flag.get("code") or "data_quality"),
                    "severity": str(flag.get("severity") or "warning"),
                    "reason": message,
                }
            )
    for flag in report_reliability.get("flags") or []:
        message = str(flag.get("message") or "").strip()
        if message and not any(item["reason"] == message for item in attention):
            attention.append(
                {
                    "code": str(flag.get("code") or "report_reliability"),
                    "severity": str(flag.get("severity") or "warning"),
                    "reason": message,
                }
            )
    for result in failed_results:
        code = _normalize_code(getattr(result, "code", ""))
        error = str(getattr(result, "error_message", "") or "analysis failed").strip()
        attention.append({"code": code, "severity": "warning", "reason": f"{code} 分析失败：{error}"})
    for holding in uncovered_holdings:
        code = str(holding.get("code") or "").strip()
        attention.append({"code": code, "severity": "warning", "reason": f"{code} 当前持仓未覆盖今日分析。"})
    return attention


def _attention_item(row: Mapping[str, Any], category: str) -> Dict[str, str]:
    prefix = "market" if category == "market_data" else category
    return {
        "code": str(row.get("code") or ""),
        "name": str(row.get("name") or row.get("code") or ""),
        "category": category,
        "status": str(row.get(f"{prefix}_status") or "missing"),
        "reason": str(row.get(f"{prefix}_reason") or ""),
    }


def _valuation_snapshot_dict(value: Any) -> Optional[Dict[str, Any]]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        converted = value.to_dict()
        return converted if isinstance(converted, dict) else None
    return None


def _format_field_coverage(field_coverage: Dict[str, Any], stock_count: int) -> str:
    if stock_count <= 0:
        return "字段覆盖 0/0"
    labels = {
        "pe_ttm": "PE",
        "pb": "PB",
        "dividend_yield": "股息率",
    }
    parts = [
        f"{label} {int(field_coverage.get(field) or 0)}/{stock_count}"
        for field, label in labels.items()
    ]
    return "字段覆盖 " + "，".join(parts)


def _date_range_text(dates: Iterable[Any]) -> str:
    values = sorted(str(value) for value in dates if str(value or "").strip())
    if not values:
        return "暂无"
    if len(values) == 1:
        return values[0]
    return f"{values[0]}~{values[-1]}"


def _score_text(score: Any) -> str:
    if score in {None, ""}:
        return "暂无评分"
    return f"{score}/100"


def _reliability_label(level: Any) -> str:
    return {
        "high": "较高",
        "usable_with_manual_review": "可用但要复核",
        "low_observe_only": "偏低，只适合观察",
    }.get(str(level or ""), "未评级")


def _display_name(result: Any) -> str:
    name = str(getattr(result, "name", "") or "").strip()
    code = _normalize_code(getattr(result, "code", ""))
    if name and code and code not in name:
        return f"{name} ({code})"
    return name or code


def _compact(value: Any, limit: int = 64) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value == value
    return str(value).strip().lower() not in {"", "none", "null", "n/a", "nan", "未知"}


def _normalize_code(code: Any) -> str:
    return str(code or "").strip().upper()
