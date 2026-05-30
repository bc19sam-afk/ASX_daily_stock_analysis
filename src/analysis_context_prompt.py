# -*- coding: utf-8 -*-
"""Low-sensitivity prompt rendering for AnalysisContextPack."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Iterable, List


SENSITIVE_FIELD_RE = re.compile(
    r"(?i)(?:['\"]?\b(?:api[_-]?key|access[_-]?token|authorization|webhook|password|cookie|secret|token)\b['\"]?"
    r"\s*[:=]\s*['\"]?[^,\s;}\]\n|]+['\"]?)"
)
SENSITIVE_WORD_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|authorization|webhook|password|cookie|secret|token)\b"
)


def format_analysis_context_pack_prompt_section(
    pack: Any,
    report_language: str = "zh",
) -> str:
    """Render an AnalysisContextPack summary safe enough for LLM prompts."""
    payload = _pack_payload(pack)
    identity = _mapping(payload.get("stock_identity"))
    price_basis = _mapping(payload.get("price_basis"))
    market_snapshot = _mapping(payload.get("market_snapshot"))
    evidence_context = _mapping(payload.get("evidence_context"))
    portfolio_context = _mapping(payload.get("portfolio_context"))
    risk_context = _mapping(payload.get("risk_context"))
    prompt_contract = _mapping(payload.get("prompt_contract"))
    missing_policy = _mapping(payload.get("missing_policy"))

    code = _clean(identity.get("code") or identity.get("input_code") or "UNKNOWN")
    name = _clean(identity.get("name") or "missing")
    market = _clean(identity.get("market") or "unknown")
    timezone = _clean(identity.get("timezone") or "unknown")
    currency = _clean(identity.get("currency") or price_basis.get("currency") or "unknown")

    lines = [
        "## AnalysisContextPack v1 low-sensitivity summary",
        f"- Subject: {code} ({name})",
        f"- Market/time/currency: market={market}; timezone={timezone}; currency={currency}",
        f"- Price basis: policy={_clean(price_basis.get('price_policy') or 'unknown')}; "
        f"technical_basis_date={_status_or_text(price_basis.get('technical_basis_date'))}; "
        f"report_date={_status_or_text(price_basis.get('report_date'))}; "
        f"execution_price_source={_status_or_text(price_basis.get('execution_price_source'))}",
        "- Market snapshot:",
    ]

    for label in ["daily", "previous_daily", "realtime", "market_overview", "trend_analysis"]:
        lines.append(f"  - {_status_line(label, market_snapshot.get(label), missing_policy)}")

    lines.append("- Evidence context:")
    for label in ["price_history", "fundamentals", "backtest", "news"]:
        lines.append(f"  - {_status_line(label, evidence_context.get(label), missing_policy)}")
    lines.append(f"  - data_missing={str(bool(evidence_context.get('data_missing'))).lower()}")

    lines.extend(
        [
            "- Portfolio context:",
            f"  - {_status_line('portfolio_context', portfolio_context, missing_policy)}",
            "- Risk/actionability:",
            "  - "
            f"validation_status={_clean(risk_context.get('validation_status') or 'UNAVAILABLE')}; "
            f"actionability={_clean(risk_context.get('actionability') or 'pending_validation')}; "
            f"blocked={str(bool(risk_context.get('blocked'))).lower()}; "
            f"data_quality_flag={_clean(risk_context.get('data_quality_flag') or 'UNKNOWN')}",
        ]
    )

    issues = _clean_list(risk_context.get("validation_issues"), limit=3)
    if issues:
        lines.append(f"  - validation_issues={'; '.join(issues)}")

    deterministic_fields = _clean_list(prompt_contract.get("deterministic_fields"), limit=12)
    lines.extend(
        [
            "- Prompt contract:",
            f"  - deterministic_fields={', '.join(deterministic_fields)}",
            "  - llm_boundary=explain context and conditional risks only; "
            "do not override deterministic action fields",
            "  - block_policy=missing/unavailable evidence is observation-only; "
            "human-in-the-loop review remains required",
            f"  - market_boundary={_clean(prompt_contract.get('market_boundary') or 'ASX-first, AUD, Australia/Sydney, human-in-the-loop.')}",
        ]
    )

    return redact_sensitive_text_for_prompt("\n".join(lines) + "\n")


def redact_sensitive_text_for_prompt(value: Any) -> str:
    """Remove sensitive field names and adjacent values from prompt-bound text."""
    text = "" if value is None else str(value)
    text = SENSITIVE_FIELD_RE.sub("[redacted-sensitive]", text)
    return SENSITIVE_WORD_RE.sub("[redacted-sensitive]", text)


def _pack_payload(pack: Any) -> Mapping[str, Any]:
    if hasattr(pack, "to_dict"):
        value = pack.to_dict()
        return value if isinstance(value, Mapping) else {}
    return pack if isinstance(pack, Mapping) else {}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _status_line(label: str, value: Any, missing_policy: Mapping[str, Any]) -> str:
    data = _mapping(value)
    status = _clean(data.get("status") or ("available" if data else "missing"))
    source = _clean(data.get("source") or label)
    parts = [f"{label}: status={status}; source={source}"]
    if status in {"missing", "unavailable"}:
        reason = _status_reason(status, missing_policy)
        if reason:
            parts.append(f"reason={reason}")
    count = data.get("row_count")
    if count is None:
        count = data.get("characters")
    if count is not None:
        parts.append(f"count={_clean(count)}")
    warnings = _warning_values(data)
    if warnings:
        parts.append(f"warnings={'; '.join(warnings)}")
    return "; ".join(parts)


def _warning_values(data: Mapping[str, Any]) -> List[str]:
    values: List[str] = []
    for key in ["warning", "warnings", "missing_reason", "reason", "issue", "issues"]:
        if key in data:
            values.extend(_clean_list(data.get(key), limit=2))
    return values[:2]


def _clean_list(value: Any, *, limit: int) -> List[str]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        iterable: Iterable[Any] = value.values()
    elif isinstance(value, (list, tuple, set)):
        iterable = value
    else:
        iterable = [value]
    cleaned = [_clean(item) for item in iterable]
    return [item for item in cleaned if item][:limit]


def _status_or_text(value: Any) -> str:
    if isinstance(value, Mapping):
        return _clean(value.get("status") or "unknown")
    return _clean(value or "unknown")


def _status_reason(status: str, missing_policy: Mapping[str, Any]) -> str:
    reason = missing_policy.get(status)
    return _clean(reason) if reason else ""


def _clean(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        return ""
    text = text.replace("\r", " ").replace("\n", " ")
    text = redact_sensitive_text_for_prompt(text)
    return text[:180]
