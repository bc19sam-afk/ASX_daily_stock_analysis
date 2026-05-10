# -*- coding: utf-8 -*-
"""Pipeline helpers for applying and logging validation gate outcomes."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from src.analyzer import AnalysisResult
from src.core.validator import ValidationOutcome, evaluate_analysis_gate


def append_unique_text(existing: str, additions: List[str]) -> str:
    """Append unique non-empty text fragments with stable separators."""
    parts = [str(existing or "").strip()] if str(existing or "").strip() else []
    for item in additions:
        text = str(item or "").strip()
        if not text or text in parts:
            continue
        parts.append(text)
    return "；".join(parts)


def apply_blocked_validation_state(
    *,
    result: AnalysisResult,
    portfolio_state: Optional[Dict[str, float]] = None,
) -> None:
    """Downgrade a result to observation-only when validation blocks action."""
    issues = list(result.validation_issues or [])
    current_weight = float(getattr(result, "current_weight", 0.0) or 0.0)
    if portfolio_state is not None:
        current_weight = round(float(portfolio_state.get("current_weight", current_weight) or 0.0), 4)
        result.current_weight = current_weight
        result.target_quantity = float(portfolio_state.get("quantity", 0.0) or 0.0)

    result.final_decision = "HOLD"
    result.position_action = "HOLD"
    result.watchlist_state = "OBSERVE"
    result.target_weight = current_weight
    result.delta_amount = 0.0
    result.operation_advice = "不可决策，仅观察"
    result.action_reason = append_unique_text(result.action_reason, ["validation_blocked", *issues])
    result.risk_warning = append_unique_text(result.risk_warning, issues)
    if str(getattr(result, "analysis_status", "OK") or "").upper() == "OK":
        result.analysis_status = "DEGRADED"


def build_validation_log_payload(
    *,
    result: AnalysisResult,
    outcome: ValidationOutcome,
    query_id: Optional[str],
) -> Dict[str, Any]:
    """Build the stable structured observability payload for the validation gate."""
    return {
        "event": "validator_gate",
        "stock_code": result.code,
        "query_id": query_id,
        "validation_status": outcome.validation_status,
        "blocked_reason": list(outcome.blocked_reason or []),
        "mixed_price_basis": bool(outcome.mixed_price_basis),
        "stale_daily_context": bool(outcome.stale_daily_context),
        "missing_critical_data": bool(outcome.missing_critical_data),
    }


def log_validation_gate_outcome(
    *,
    logger: logging.Logger,
    result: AnalysisResult,
    outcome: ValidationOutcome,
    query_id: Optional[str],
) -> None:
    """Emit structured validation gate observability logs."""
    payload = build_validation_log_payload(result=result, outcome=outcome, query_id=query_id)
    log_method = logger.warning if outcome.validation_status == "BLOCK" else logger.info
    log_method("[validator_gate] %s", json.dumps(payload, ensure_ascii=False, sort_keys=True))


def apply_validation_gate(
    *,
    logger: logging.Logger,
    result: AnalysisResult,
    enhanced_context: Dict[str, Any],
    market_timezone: str,
    market_calendar: str,
    query_id: Optional[str] = None,
    now: Optional[datetime] = None,
    load_portfolio_state: Optional[Callable[..., Optional[Dict[str, float]]]] = None,
) -> ValidationOutcome:
    """Evaluate the validation gate, mutate the result, and emit observability logs."""
    outcome = evaluate_analysis_gate(
        enhanced_context=enhanced_context,
        execution_price_source=result.execution_price_source,
        current_price=result.current_price,
        market_timezone=market_timezone,
        market_calendar=market_calendar,
        now=now,
    )
    analysis_status = str(getattr(result, "analysis_status", "OK") or "OK").strip().upper()
    if analysis_status != "OK":
        outcome = ValidationOutcome(
            validation_status="BLOCK",
            validation_issues=_dedupe(
                [
                    *list(outcome.validation_issues or []),
                    f"analysis_status={analysis_status}",
                ]
            ),
            blocked_reason=_dedupe(
                [
                    *list(outcome.blocked_reason or []),
                    "analysis_status_not_ok",
                ]
            ),
            mixed_price_basis=outcome.mixed_price_basis,
            stale_daily_context=outcome.stale_daily_context,
            missing_critical_data=outcome.missing_critical_data,
        )
    result.validation_status = outcome.validation_status
    result.validation_issues = list(outcome.validation_issues)

    if outcome.validation_status == "BLOCK":
        portfolio_state = load_portfolio_state(result=result) if load_portfolio_state else None
        apply_blocked_validation_state(result=result, portfolio_state=portfolio_state)

    log_validation_gate_outcome(
        logger=logger,
        result=result,
        outcome=outcome,
        query_id=query_id,
    )
    return outcome


def _dedupe(items: List[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
