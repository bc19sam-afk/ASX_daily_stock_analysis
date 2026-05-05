# -*- coding: utf-8 -*-
"""Contract-only types for a future independent intraday review mode.

This module deliberately avoids market-data, AI, broker, storage, and daily
report integrations. It only describes how a future intraday review may consume
an already-generated close-only morning summary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional


INTRADAY_REVIEW_STATUSES = {"still_valid", "wait", "cancel", "observe_only", "block"}
BLOCKED_ITEM_ALLOWED_STATUSES = {"observe_only", "block"}


@dataclass(frozen=True)
class IntradayReviewMarketInput:
    code: str
    last_price: Optional[float]
    previous_close: Optional[float]
    price_timestamp: str
    has_price_sensitive_risk: Optional[bool] = None
    liquidity_warning: Optional[bool] = None
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "last_price": self.last_price,
            "previous_close": self.previous_close,
            "price_timestamp": self.price_timestamp,
            "has_price_sensitive_risk": self.has_price_sensitive_risk,
            "liquidity_warning": self.liquidity_warning,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "IntradayReviewMarketInput":
        return cls(
            code=str(payload.get("code") or ""),
            last_price=_optional_float(payload.get("last_price")),
            previous_close=_optional_float(payload.get("previous_close")),
            price_timestamp=str(payload.get("price_timestamp") or ""),
            has_price_sensitive_risk=_optional_bool(payload.get("has_price_sensitive_risk")),
            liquidity_warning=_optional_bool(payload.get("liquidity_warning")),
            notes=[str(item) for item in (payload.get("notes") or [])],
        )


@dataclass(frozen=True)
class IntradayReviewEvaluation:
    code: str
    morning_action: str
    review_status: str
    reason: str
    price_deviation_pct: Optional[float]
    required_manual_checks: List[str] = field(default_factory=list)
    source: str = "offline_input"
    is_trade_instruction: bool = False

    def __post_init__(self) -> None:
        status = str(self.review_status or "").strip().lower()
        if status not in INTRADAY_REVIEW_STATUSES:
            raise ValueError(f"Unsupported intraday review status: {self.review_status}")
        object.__setattr__(self, "review_status", status)
        object.__setattr__(self, "source", "offline_input")
        object.__setattr__(self, "is_trade_instruction", False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "morning_action": self.morning_action,
            "review_status": self.review_status,
            "reason": self.reason,
            "price_deviation_pct": self.price_deviation_pct,
            "required_manual_checks": list(self.required_manual_checks),
            "source": self.source,
            "is_trade_instruction": self.is_trade_instruction,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "IntradayReviewEvaluation":
        return cls(
            code=str(payload.get("code") or ""),
            morning_action=str(payload.get("morning_action") or ""),
            review_status=str(payload.get("review_status") or ""),
            reason=str(payload.get("reason") or ""),
            price_deviation_pct=_optional_float(payload.get("price_deviation_pct")),
            required_manual_checks=[str(item) for item in (payload.get("required_manual_checks") or [])],
            source=str(payload.get("source") or "offline_input"),
            is_trade_instruction=bool(payload.get("is_trade_instruction", False)),
        )


@dataclass(frozen=True)
class IntradayReviewInput:
    report_date: str
    source_summary_path: str
    technical_basis_date: str
    price_policy: str
    actionable_items: List[Dict[str, Any]] = field(default_factory=list)
    watch_items: List[Dict[str, Any]] = field(default_factory=list)
    blocked_items: List[Dict[str, Any]] = field(default_factory=list)
    price_policy_source_note: str = ""

    def __post_init__(self) -> None:
        if not str(self.price_policy or "").strip():
            raise ValueError("IntradayReviewInput requires price_policy from the morning summary.")
        if not str(self.source_summary_path or "").strip():
            raise ValueError("IntradayReviewInput requires source_summary_path.")
        if not self.price_policy_source_note:
            object.__setattr__(self, "price_policy_source_note", _price_policy_note(self.price_policy))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_date": self.report_date,
            "source_summary_path": self.source_summary_path,
            "technical_basis_date": self.technical_basis_date,
            "price_policy": self.price_policy,
            "price_policy_source_note": self.price_policy_source_note,
            "actionable_items": [dict(item) for item in self.actionable_items],
            "watch_items": [dict(item) for item in self.watch_items],
            "blocked_items": [dict(item) for item in self.blocked_items],
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "IntradayReviewInput":
        return cls(
            report_date=str(payload.get("report_date") or ""),
            source_summary_path=str(payload.get("source_summary_path") or ""),
            technical_basis_date=str(payload.get("technical_basis_date") or ""),
            price_policy=str(payload.get("price_policy") or ""),
            price_policy_source_note=str(payload.get("price_policy_source_note") or ""),
            actionable_items=_copy_items(payload.get("actionable_items") or []),
            watch_items=_copy_items(payload.get("watch_items") or []),
            blocked_items=_copy_items(payload.get("blocked_items") or []),
        )


@dataclass(frozen=True)
class IntradayReviewDecision:
    code: str
    morning_action: str
    review_status: str
    reason: str
    required_manual_checks: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        status = str(self.review_status or "").strip().lower()
        if status not in INTRADAY_REVIEW_STATUSES:
            raise ValueError(f"Unsupported intraday review status: {self.review_status}")
        object.__setattr__(self, "review_status", status)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "morning_action": self.morning_action,
            "review_status": self.review_status,
            "reason": self.reason,
            "required_manual_checks": list(self.required_manual_checks),
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "IntradayReviewDecision":
        return cls(
            code=str(payload.get("code") or ""),
            morning_action=str(payload.get("morning_action") or ""),
            review_status=str(payload.get("review_status") or ""),
            reason=str(payload.get("reason") or ""),
            required_manual_checks=[str(item) for item in (payload.get("required_manual_checks") or [])],
        )


def build_intraday_review_input_from_summary(
    summary: Dict[str, Any],
    *,
    source_summary_path: str,
) -> IntradayReviewInput:
    """Create a contract input from a daily_decision_summary artifact."""
    return IntradayReviewInput(
        report_date=str(summary.get("report_date") or ""),
        source_summary_path=source_summary_path,
        technical_basis_date=str(summary.get("technical_basis_date") or ""),
        price_policy=str(summary.get("price_policy") or ""),
        actionable_items=_copy_items(summary.get("actionable_items") or []),
        watch_items=_copy_items(summary.get("watch_items") or []),
        blocked_items=_copy_items(summary.get("blocked_items") or []),
    )


def validate_intraday_review_decision(
    decision: IntradayReviewDecision,
    *,
    is_blocked_morning_item: bool,
) -> None:
    """Validate contract-only status rules for a future review decision."""
    if is_blocked_morning_item and decision.review_status not in BLOCKED_ITEM_ALLOWED_STATUSES:
        raise ValueError("BLOCK morning items can only remain observe_only or block in intraday review.")


def _copy_items(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [dict(item) for item in items]


def _optional_float(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return parsed


def _optional_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    lowered = str(value).strip().lower()
    if lowered in {"true", "1", "yes", "y"}:
        return True
    if lowered in {"false", "0", "no", "n"}:
        return False
    return None


def _price_policy_note(price_policy: str) -> str:
    policy = str(price_policy or "").strip().lower()
    if policy == "close_only":
        return "close_only morning summary: based on last close / pre-open plan; not realtime."
    return f"{policy or 'unknown'} morning summary price policy; review must not treat it as realtime execution data."
