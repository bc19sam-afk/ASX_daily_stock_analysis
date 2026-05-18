# -*- coding: utf-8 -*-
"""Evidence matrix helpers for auditable daily decision summaries."""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

from src.asx_announcements import (
    ANNOUNCEMENT_CLEAR,
    ANNOUNCEMENT_NOT_CHECKED,
    ANNOUNCEMENT_RISK_FOUND,
    ANNOUNCEMENT_UNAVAILABLE,
    coerce_asx_announcement_check,
)
from src.core.validator import normalize_validation_status
from src.stock_code import canonical_stock_code


def build_evidence_matrix(
    *,
    results: List[Any],
    overview: Dict[str, Any],
    classify_price_basis: Callable[[Any], str],
    format_validation_issue_text: Callable[[Any], str],
    announcement_checks: Optional[Mapping[str, Any]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Build per-stock evidence rows without feeding back into decisions."""
    holdings_by_code = _holdings_by_code(overview.get("holdings") or [])
    announcement_checks = announcement_checks or {}
    matrix: Dict[str, List[Dict[str, Any]]] = {}

    for result in results:
        code = _normalize_code(getattr(result, "code", ""))
        if not code:
            continue
        holding = holdings_by_code.get(code)
        entries = [
            _market_data_evidence(result, classify_price_basis),
            _technical_evidence(result),
            _valuation_evidence(result),
            _news_evidence(result),
            _backtest_evidence(result),
            _portfolio_evidence(result, holding),
            _validation_evidence(result, format_validation_issue_text),
        ]
        if code in announcement_checks:
            entries.insert(4, _announcement_evidence(code, announcement_checks.get(code)))
        matrix[code] = entries

    return matrix


def summarize_evidence_matrix(matrix: Dict[str, List[Dict[str, Any]]]) -> Dict[str, int]:
    """Return cockpit-level evidence quality counts."""
    summary = {
        "stock_count": len(matrix),
        "market_data_available": 0,
        "market_data_missing_or_stale": 0,
        "news_missing": 0,
        "valuation_missing": 0,
        "announcement_not_checked": 0,
        "announcement_unavailable": 0,
        "announcement_risk_found": 0,
        "backtest_not_checked": 0,
        "validation_block": 0,
    }

    for entries in matrix.values():
        by_category = {entry.get("category"): entry for entry in entries}
        market = by_category.get("market_data") or {}
        if market.get("status") == "available":
            summary["market_data_available"] += 1
        else:
            summary["market_data_missing_or_stale"] += 1
        if (by_category.get("news") or {}).get("status") in {"missing", "not_checked", "stale"}:
            summary["news_missing"] += 1
        if (by_category.get("valuation") or {}).get("status") in {"missing", "not_checked", "stale", "partial"}:
            summary["valuation_missing"] += 1
        announcement_status = (by_category.get("announcement") or {}).get("status")
        if announcement_status == ANNOUNCEMENT_NOT_CHECKED:
            summary["announcement_not_checked"] += 1
        elif announcement_status == ANNOUNCEMENT_UNAVAILABLE:
            summary["announcement_unavailable"] += 1
        elif announcement_status == ANNOUNCEMENT_RISK_FOUND:
            summary["announcement_risk_found"] += 1
        if (by_category.get("backtest") or {}).get("status") == "not_checked":
            summary["backtest_not_checked"] += 1
        if (by_category.get("validation") or {}).get("severity") == "block":
            summary["validation_block"] += 1

    return summary


def render_evidence_summary_lines(summary: Dict[str, Any]) -> List[str]:
    """Render compact evidence quality summary lines."""
    if not summary:
        return []
    stock_count = int(summary.get("stock_count") or 0)
    lines = [
        "## 证据质量摘要",
        "",
        f"- {summary.get('market_data_available', 0)}/{stock_count} 只股票行情数据完整。",
        f"- {summary.get('news_missing', 0)}/{stock_count} 只股票新闻证据缺失或未检查。",
        f"- {summary.get('valuation_missing', 0)}/{stock_count} 只股票估值 / 基本面证据缺失。",
    ]
    if any(
        int(summary.get(key, 0) or 0) > 0
        for key in ("announcement_not_checked", "announcement_unavailable", "announcement_risk_found")
    ):
        lines.append(
            f"- ASX 官方公告：未检查 {summary.get('announcement_not_checked', 0)}/{stock_count}，"
            f"源不可用 {summary.get('announcement_unavailable', 0)}/{stock_count}，"
            f"风险 {summary.get('announcement_risk_found', 0)}/{stock_count}。"
        )
    lines.extend([
        f"- {summary.get('backtest_not_checked', 0)}/{stock_count} 只股票回测证据未检查。",
        f"- {summary.get('validation_block', 0)} 只股票触发 validation block。",
        "",
    ])
    return lines


def render_evidence_matrix_lines(matrix: Dict[str, List[Dict[str, Any]]]) -> List[str]:
    """Render a per-stock evidence matrix table."""
    if not matrix:
        return []
    lines = [
        "## 个股证据矩阵",
        "",
        "| 标的 | 类别 | 来源 | 时间 | 状态 | 说明 |",
        "|---|---|---|---|---|---|",
    ]
    for code, entries in matrix.items():
        for entry in entries:
            lines.append(
                "| "
                f"{_cell(code)} | "
                f"{_cell(entry.get('category'))} | "
                f"{_cell(entry.get('source'))} | "
                f"{_cell(entry.get('as_of_date'))} | "
                f"{_cell(entry.get('status'))} | "
                f"{_cell(entry.get('details'))} |"
            )
    lines.append("")
    return lines


def _market_data_evidence(result: Any, classify_price_basis: Callable[[Any], str]) -> Dict[str, Any]:
    snapshot = getattr(result, "market_snapshot", None) or {}
    source = str(snapshot.get("source") or getattr(result, "data_sources", None) or "market_snapshot")
    as_of_date = _normal_text(snapshot.get("date"))
    has_price = any(_normal_text(snapshot.get(key)) for key in ("close", "price", "current_price"))
    has_price = has_price or bool(_normal_text(getattr(result, "current_price", None)))
    if not as_of_date:
        return _entry(
            "market_data",
            source,
            None,
            "missing",
            "market_snapshot.date 缺失，无法审计行情数据时间。",
            "warning",
        )
    if not has_price:
        return _entry("market_data", source, as_of_date, "missing", "行情价格缺失。", "warning")
    return _entry(
        "market_data",
        source,
        as_of_date,
        "available",
        f"价格口径：{classify_price_basis(result)}。",
        "info",
    )


def _technical_evidence(result: Any) -> Dict[str, Any]:
    snapshot = getattr(result, "market_snapshot", None) or {}
    as_of_date = _normal_text(snapshot.get("date"))
    detail = _first_non_empty(
        getattr(result, "technical_analysis", None),
        getattr(result, "trend_analysis", None),
        getattr(result, "trend_prediction", None),
    )
    if detail:
        return _entry("technical", "analysis_result", as_of_date, "available", _short(detail), "info")
    return _entry("technical", "analysis_result", as_of_date, "missing", "技术证据缺失。", "warning")


def _valuation_evidence(result: Any) -> Dict[str, Any]:
    snapshot = getattr(result, "market_snapshot", None) or {}
    valuation_snapshot = _valuation_snapshot_dict(snapshot.get("valuation_snapshot"))
    if valuation_snapshot and _has_core_valuation_values(valuation_snapshot):
        source = _normal_text(valuation_snapshot.get("source")) or "valuation_snapshot"
        as_of_date = _normal_text(valuation_snapshot.get("as_of_date"))
        return _entry("valuation", source, as_of_date, "available", _format_valuation_snapshot(valuation_snapshot), "info")
    if valuation_snapshot and _has_valuation_values(valuation_snapshot):
        source = _normal_text(valuation_snapshot.get("source")) or "valuation_snapshot"
        as_of_date = _normal_text(valuation_snapshot.get("as_of_date"))
        return _entry(
            "valuation",
            source,
            as_of_date,
            "partial",
            "估值快照仅含辅助字段，缺少 PE/PB/股息率等核心字段；按估值覆盖缺口处理。",
            "warning",
        )
    if valuation_snapshot:
        source = _normal_text(valuation_snapshot.get("source")) or "valuation_snapshot"
        as_of_date = _normal_text(valuation_snapshot.get("as_of_date"))
        return _entry("valuation", source, as_of_date, "missing", "估值快照缺少 PE/PB/股息率等可用字段。", "warning")
    as_of_date = _normal_text(snapshot.get("date"))
    detail = _first_non_empty(getattr(result, "fundamental_analysis", None), getattr(result, "company_highlights", None))
    if detail:
        return _entry("valuation", "analysis_result", as_of_date, "available", _short(detail), "info")
    return _entry("valuation", "analysis_result", as_of_date, "missing", "估值 / 基本面证据缺失。", "warning")


def _news_evidence(result: Any) -> Dict[str, Any]:
    detail = _normal_text(getattr(result, "news_summary", None))
    if detail:
        return _entry("news", "search_or_ai_summary", None, "available", _short(detail), "info")
    return _entry("news", "search_or_ai_summary", None, "missing", "新闻证据缺失。", "warning")


def _announcement_evidence(code: str, check_value: Any = None) -> Dict[str, Any]:
    check = coerce_asx_announcement_check(code, check_value)
    severity = {
        ANNOUNCEMENT_CLEAR: "info",
        ANNOUNCEMENT_RISK_FOUND: "block",
        ANNOUNCEMENT_UNAVAILABLE: "warning",
        ANNOUNCEMENT_NOT_CHECKED: "warning",
    }.get(check.status, "warning")
    return _entry(
        "announcement",
        check.source,
        check.checked_at,
        check.status,
        _format_announcement_details(check.to_dict()),
        severity,
    )


def _backtest_evidence(result: Any) -> Dict[str, Any]:
    summary = getattr(result, "backtest_summary", None)
    if isinstance(summary, dict) and summary:
        return _entry("backtest", "backtest_service", None, "available", _short(str(summary)), "info")
    return _entry("backtest", "backtest_service", None, "not_checked", "回测证据未检查或未提供。", "warning")


def _portfolio_evidence(result: Any, holding: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if holding:
        detail = f"当前持仓权重：{holding.get('weight', 'N/A')}。"
        return _entry("portfolio", "portfolio_overview", None, "available", detail, "info")
    current_weight = _to_float(getattr(result, "current_weight", 0.0))
    if current_weight > 0:
        return _entry("portfolio", "analysis_result", None, "available", f"分析结果含当前权重：{current_weight:.2%}。", "info")
    return _entry("portfolio", "portfolio_overview", None, "not_checked", "无当前持仓记录。", "info")


def _validation_evidence(result: Any, format_validation_issue_text: Callable[[Any], str]) -> Dict[str, Any]:
    status = normalize_validation_status(getattr(result, "validation_status", None))
    if status == "BLOCK":
        details = format_validation_issue_text(result) or "validation_status=BLOCK。"
        return _entry("validation", "validation_gate", None, "available", details, "block")
    return _entry("validation", "validation_gate", None, "available", "validation_status=PASS。", "info")


def _entry(
    category: str,
    source: str,
    as_of_date: Optional[str],
    status: str,
    details: str,
    severity: str,
) -> Dict[str, Any]:
    return {
        "category": category,
        "source": source,
        "as_of_date": as_of_date,
        "status": status,
        "details": details,
        "severity": severity,
    }


def _holdings_by_code(holdings: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {_normalize_code(item.get("code")): item for item in holdings if _normalize_code(item.get("code"))}


def _normalize_code(value: Any) -> str:
    return canonical_stock_code(value)


def _normal_text(value: Any) -> Optional[str]:
    raw = str(value or "").strip()
    if raw.lower() in {"", "none", "null", "n/a", "unknown", "未知", "nan"}:
        return None
    return raw


def _first_non_empty(*values: Any) -> Optional[str]:
    for value in values:
        normalized = _normal_text(value)
        if normalized:
            return normalized
    return None


def _short(value: str, limit: int = 120) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else f"{text[:limit]}..."


def _to_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _valuation_snapshot_dict(value: Any) -> Optional[Dict[str, Any]]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        try:
            return value.to_dict()
        except Exception:
            return None
    return None


def _format_valuation_snapshot(snapshot: Dict[str, Any]) -> str:
    parts = ["估值快照"]
    present_fields: List[str] = []
    if _has_value(snapshot.get("pe_ttm")):
        present_fields.append(f"PE(TTM)：{_format_number(snapshot.get('pe_ttm'))}")
    if _has_value(snapshot.get("pe_forward")):
        present_fields.append(f"PE(Forward)：{_format_number(snapshot.get('pe_forward'))}")
    if _has_value(snapshot.get("pb")):
        present_fields.append(f"PB：{_format_number(snapshot.get('pb'))}")
    if _has_value(snapshot.get("dividend_yield")):
        present_fields.append(f"股息率：{_format_percent(snapshot.get('dividend_yield'))}")
    if present_fields:
        parts.extend(present_fields)
    else:
        parts.append("核心估值字段缺口较多，已按部分可用处理。")
    parts.append(f"来源：{snapshot.get('source') or 'unknown'}")
    if snapshot.get("as_of_date"):
        parts.append(f"时间：{snapshot.get('as_of_date')}")
    return "；".join(parts)


def _format_announcement_details(check: Dict[str, Any]) -> str:
    reason = _normal_text(check.get("reason")) or "ASX 官方公告状态未提供；执行前需人工检查公告。"
    latest_items = check.get("latest_items") or []
    titles = []
    for item in latest_items[:2]:
        if isinstance(item, dict):
            title = _first_non_empty(item.get("title"), item.get("headline"), item.get("summary"))
            published_at = _normal_text(item.get("published_at") or item.get("date"))
            if title and published_at:
                titles.append(f"{title}（{published_at}）")
            elif title:
                titles.append(title)
        else:
            title = _normal_text(item)
            if title:
                titles.append(title)
    if titles:
        return f"{reason} 最新项：{'；'.join(titles)}。"
    return reason


def _has_valuation_values(snapshot: Dict[str, Any]) -> bool:
    fields = ("pe_ttm", "pe_forward", "pb", "dividend_yield", "market_cap", "roe", "debt_to_equity")
    return any(_has_value(snapshot.get(field)) for field in fields)


def _has_core_valuation_values(snapshot: Dict[str, Any]) -> bool:
    fields = ("pe_ttm", "pe_forward", "pb", "dividend_yield")
    return any(_has_value(snapshot.get(field)) for field in fields)


def _has_value(value: Any) -> bool:
    return value is not None and str(value).strip().lower() not in {"", "n/a", "none", "null", "unknown", "nan"}


def _format_number(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "missing"


def _format_percent(value: Any) -> str:
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "missing"


def _cell(value: Any) -> str:
    text = str(value if value is not None else "-").strip() or "-"
    return text.replace("|", r"\|").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")
