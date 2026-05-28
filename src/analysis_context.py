# -*- coding: utf-8 -*-
"""Serializable ASX analysis context pack for LLM-bound inputs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from src.core.validator import normalize_validation_status
from src.stock_code import canonical_stock_code


ASX_TIMEZONE = "Australia/Sydney"
ASX_CURRENCY = "AUD"
ASX_MARKET = "ASX"

DETERMINISTIC_FIELDS = [
    "final_decision",
    "position_action",
    "target_weight",
    "delta_amount",
    "action_counts",
    "search",
    "workflow",
    "close_only",
]


@dataclass(frozen=True)
class AnalysisContextPack:
    """Stable, JSON-serializable context passed toward LLM analysis."""

    stock_identity: Dict[str, Any]
    price_basis: Dict[str, Any]
    market_snapshot: Dict[str, Any]
    evidence_context: Dict[str, Any]
    portfolio_context: Dict[str, Any]
    risk_context: Dict[str, Any]
    prompt_contract: Dict[str, Any]
    schema_version: str = "analysis_context_pack.v1"
    missing_policy: Dict[str, str] = field(
        default_factory=lambda: {
            "missing": "Field was expected but no value is available.",
            "unavailable": "Source or subsystem was not available for this run.",
        }
    )

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict without leaking non-serializable objects."""
        return _json_safe(asdict(self))


def build_analysis_context_pack(
    context: Optional[Dict[str, Any]],
    *,
    stock_name: Optional[str] = None,
    report_date: Optional[Any] = None,
    news_context: Optional[str] = None,
    portfolio_context: Optional[Dict[str, Any]] = None,
    validation_status: Optional[str] = None,
    validation_issues: Optional[List[str]] = None,
) -> AnalysisContextPack:
    """Build the v1 LLM-bound context pack from the current analysis context."""
    ctx = context if isinstance(context, dict) else {}
    identity = _build_stock_identity(ctx, stock_name=stock_name)
    price_policy = _text(ctx.get("price_policy") or ctx.get("execution_price_policy")) or "close_only"
    technical_basis_date = _first_text(
        ctx.get("technical_basis_date"),
        ctx.get("market_basis_date"),
        ctx.get("snapshot_basis_date"),
        ctx.get("date"),
    )
    resolved_report_date = _first_text(report_date, ctx.get("report_date")) or _status("missing")

    resolved_validation_status = validation_status if validation_status is not None else ctx.get("validation_status")
    if resolved_validation_status is None:
        risk_status = "UNAVAILABLE"
    else:
        risk_status = normalize_validation_status(resolved_validation_status)
    risk_issues = _list_text(validation_issues if validation_issues is not None else ctx.get("validation_issues"))

    if ctx.get("data_missing") and not any("data_missing" in issue for issue in risk_issues):
        risk_issues.append("data_missing: analysis context has missing daily market data")

    return AnalysisContextPack(
        stock_identity=identity,
        price_basis={
            "price_policy": price_policy,
            "technical_basis_date": technical_basis_date or _status("missing"),
            "report_date": resolved_report_date,
            "currency": identity["currency"],
            "execution_price_source": _text(ctx.get("execution_price_source")) or _status("unavailable"),
        },
        market_snapshot={
            "daily": _availability_mapping(ctx.get("today"), source="today"),
            "previous_daily": _availability_mapping(ctx.get("yesterday"), source="yesterday"),
            "realtime": _availability_mapping(ctx.get("realtime"), source="realtime"),
            "market_overview": _availability_mapping(ctx.get("market_overview"), source="market_overview"),
            "trend_analysis": _availability_mapping(ctx.get("trend_analysis"), source="trend_analysis"),
        },
        evidence_context={
            "price_history": _build_price_history_evidence(ctx),
            "fundamentals": _availability_mapping(ctx.get("fundamentals"), source="fundamentals"),
            "backtest": _availability_mapping(ctx.get("backtest_summary"), source="backtest_summary"),
            "news": _news_availability(news_context),
            "data_missing": bool(ctx.get("data_missing")),
        },
        portfolio_context=_build_portfolio_context(ctx, portfolio_context),
        risk_context={
            "validation_status": risk_status,
            "validation_issues": risk_issues,
            "blocked": risk_status == "BLOCK" or bool(risk_issues),
            "actionability": (
                "observation_only"
                if risk_status == "BLOCK" or risk_issues
                else "pending_validation"
                if risk_status == "UNAVAILABLE"
                else "decision_support"
            ),
            "data_quality_flag": "MISSING" if ctx.get("data_missing") else "OK",
            "trend_risk_factors": _list_text((ctx.get("trend_analysis") or {}).get("risk_factors"))
            if isinstance(ctx.get("trend_analysis"), dict)
            else [],
        },
        prompt_contract={
            "deterministic_fields": list(DETERMINISTIC_FIELDS),
            "llm_boundary": (
                "Explain context and conditional risks only; do not override deterministic action fields."
            ),
            "block_policy": "BLOCK and unavailable evidence are observation-only risks, not executable advice.",
            "missing_policy": "Missing/unavailable data must be named explicitly and never described as clear.",
            "market_boundary": "ASX-first, AUD, Australia/Sydney, human-in-the-loop.",
        },
    )


def _build_stock_identity(context: Dict[str, Any], *, stock_name: Optional[str]) -> Dict[str, Any]:
    raw_code = _text(context.get("code")) or "UNKNOWN"
    canonical = canonical_stock_code(raw_code)
    market = ASX_MARKET if canonical.endswith(".AX") else _text(context.get("market")) or "UNKNOWN"
    currency = ASX_CURRENCY if market == ASX_MARKET else _text(context.get("currency")) or _status("unavailable")
    timezone = ASX_TIMEZONE if market == ASX_MARKET else _text(context.get("timezone")) or _status("unavailable")

    return {
        "input_code": raw_code,
        "code": canonical,
        "name": _text(stock_name) or _text(context.get("stock_name")) or _status("missing"),
        "market": market,
        "currency": currency,
        "timezone": timezone,
    }


def _build_price_history_evidence(context: Dict[str, Any]) -> Dict[str, Any]:
    table = _text(context.get("price_history_table"))
    raw_data = context.get("raw_data")
    if table:
        return {
            "status": "available",
            "source": "price_history_table",
            "row_count": _safe_len(table.splitlines()),
        }
    if raw_data:
        return {
            "status": "available",
            "source": "raw_data",
            "row_count": _safe_len(raw_data),
        }
    return {"status": "missing", "source": "price_history"}


def _build_portfolio_context(
    context: Dict[str, Any],
    portfolio_context: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    source = portfolio_context if isinstance(portfolio_context, dict) else context.get("portfolio_context")
    if isinstance(source, dict) and source:
        return {"status": "available", "source": "portfolio_context", "data": _json_safe(source)}

    portfolio_keys = {
        "current_weight": context.get("current_weight"),
        "current_position_value": context.get("current_position_value"),
        "total_value": context.get("total_value"),
    }
    available = {key: value for key, value in portfolio_keys.items() if value is not None}
    if available:
        return {"status": "available", "source": "context", "data": _json_safe(available)}
    return {"status": "unavailable", "source": "portfolio_context"}


def _news_availability(news_context: Optional[str]) -> Dict[str, Any]:
    text = _text(news_context)
    if text:
        return {"status": "available", "source": "news_context", "characters": len(text)}
    return {"status": "unavailable", "source": "news_context"}


def _availability_mapping(value: Any, *, source: str) -> Dict[str, Any]:
    if isinstance(value, dict):
        if value:
            return {"status": "available", "source": source, "data": _json_safe(value)}
        return {"status": "missing", "source": source}
    if value is None:
        return {"status": "missing", "source": source}
    return {"status": "available", "source": source, "data": _json_safe(value)}


def _status(status: str) -> Dict[str, str]:
    return {"status": status}


def _first_text(*values: Any) -> Optional[str]:
    for value in values:
        text = _text(value)
        if text:
            return text
    return None


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
    elif isinstance(value, (date, datetime)):
        text = value.isoformat()
    else:
        text = str(value).strip()
    return text or None


def _list_text(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [item for item in (_text(item) for item in value) if item]
    text = _text(value)
    return [text] if text else []


def _safe_len(value: Any) -> int:
    try:
        return len(value)
    except TypeError:
        return 0


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "value"):
        return _json_safe(value.value)
    return str(value)
