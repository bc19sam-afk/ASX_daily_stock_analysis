# -*- coding: utf-8 -*-
"""Offline-only intraday review evaluator.

The evaluator consumes a P2-1 intraday review contract plus externally supplied
market inputs. It does not fetch data, call AI, connect brokers, write accounts,
or mutate the morning summary.
"""

from __future__ import annotations

from typing import Dict, Iterable, Mapping, Optional

from src.intraday_review_contract import (
    IntradayReviewEvaluation,
    IntradayReviewInput,
    IntradayReviewMarketInput,
    validate_intraday_review_decision,
    IntradayReviewDecision,
)


DEFAULT_MAX_PRICE_DEVIATION_PCT = 2.0
DEFAULT_CANCEL_DEVIATION_PCT = 5.0

_MANUAL_CHECKS = [
    "人工复核当前价格、盘口流动性和重大公告；本输出不是交易指令。",
    "确认 morning daily_decision_summary 的 close_only / 昨收计划口径仍适用。",
    "执行前由人工确认 final_decision、position_action 和 validation gate 未被覆盖。",
]


def evaluate_intraday_review_offline(
    review_input: IntradayReviewInput,
    *,
    market_inputs: Mapping[str, IntradayReviewMarketInput] | Iterable[IntradayReviewMarketInput],
    max_price_deviation_pct: float = DEFAULT_MAX_PRICE_DEVIATION_PCT,
    cancel_deviation_pct: float = DEFAULT_CANCEL_DEVIATION_PCT,
) -> Dict[str, IntradayReviewEvaluation]:
    """Evaluate morning items against externally supplied market inputs only."""
    markets = _normalize_market_inputs(market_inputs)
    evaluations: Dict[str, IntradayReviewEvaluation] = {}

    for item in review_input.actionable_items:
        code = _code(item)
        evaluations[code] = _evaluate_item(
            item,
            market=markets.get(code),
            is_blocked_morning_item=False,
            is_actionable_morning_item=True,
            max_price_deviation_pct=max_price_deviation_pct,
            cancel_deviation_pct=cancel_deviation_pct,
        )

    for item in review_input.watch_items:
        code = _code(item)
        evaluations[code] = _evaluate_item(
            item,
            market=markets.get(code),
            is_blocked_morning_item=False,
            is_actionable_morning_item=False,
            max_price_deviation_pct=max_price_deviation_pct,
            cancel_deviation_pct=cancel_deviation_pct,
        )

    for item in review_input.blocked_items:
        code = _code(item)
        evaluations[code] = _evaluate_item(
            item,
            market=markets.get(code),
            is_blocked_morning_item=True,
            is_actionable_morning_item=False,
            max_price_deviation_pct=max_price_deviation_pct,
            cancel_deviation_pct=cancel_deviation_pct,
        )

    return evaluations


def _evaluate_item(
    item: Mapping[str, object],
    *,
    market: Optional[IntradayReviewMarketInput],
    is_blocked_morning_item: bool,
    is_actionable_morning_item: bool,
    max_price_deviation_pct: float,
    cancel_deviation_pct: float,
) -> IntradayReviewEvaluation:
    code = _code(item)
    morning_action = _morning_action(item, is_blocked_morning_item=is_blocked_morning_item)
    deviation = _price_deviation_pct(market)

    if is_blocked_morning_item:
        status = "block" if bool(getattr(market, "has_price_sensitive_risk", False)) else "observe_only"
        reason = "Morning validation BLOCK remains hard-stopped; intraday evaluator keeps it observe-only."
        return _evaluation(code, morning_action, status, reason, deviation, is_blocked_morning_item=True)

    if market is None:
        return _evaluation(
            code,
            morning_action,
            "observe_only",
            "No offline market input was supplied; evaluator cannot assess validity without guessing.",
            deviation,
        )

    if market.has_price_sensitive_risk is True:
        return _evaluation(
            code,
            morning_action,
            "block",
            "Offline input flags price-sensitive risk; manual review must stop before any action.",
            deviation,
        )

    if deviation is None:
        return _evaluation(
            code,
            morning_action,
            "observe_only",
            "Offline input is missing last_price or previous_close; no price deviation was guessed.",
            deviation,
        )

    absolute_deviation = abs(deviation)
    if absolute_deviation > max(cancel_deviation_pct, 0.0):
        return _evaluation(
            code,
            morning_action,
            "cancel",
            f"Price moved {deviation:+.2f}% from previous close, beyond cancel threshold.",
            deviation,
        )

    if absolute_deviation > max(max_price_deviation_pct, 0.0):
        return _evaluation(
            code,
            morning_action,
            "wait",
            f"Price moved {deviation:+.2f}% from previous close, beyond wait threshold.",
            deviation,
        )

    if market.liquidity_warning is True:
        return _evaluation(
            code,
            morning_action,
            "wait" if is_actionable_morning_item else "observe_only",
            "Offline input flags liquidity warning; keep this for manual review only.",
            deviation,
        )

    if not is_actionable_morning_item:
        return _evaluation(
            code,
            morning_action,
            "observe_only",
            "Morning item is not actionable; offline review keeps it observe-only.",
            deviation,
        )

    return _evaluation(
        code,
        morning_action,
        "still_valid",
        "Morning plan remains still_valid for manual review only; 不是交易指令。",
        deviation,
    )


def _evaluation(
    code: str,
    morning_action: str,
    review_status: str,
    reason: str,
    price_deviation_pct: Optional[float],
    *,
    is_blocked_morning_item: bool = False,
) -> IntradayReviewEvaluation:
    decision = IntradayReviewDecision(
        code=code,
        morning_action=morning_action,
        review_status=review_status,
        reason=reason,
        required_manual_checks=list(_MANUAL_CHECKS),
    )
    validate_intraday_review_decision(decision, is_blocked_morning_item=is_blocked_morning_item)
    return IntradayReviewEvaluation(
        code=code,
        morning_action=morning_action,
        review_status=decision.review_status,
        reason=reason,
        price_deviation_pct=price_deviation_pct,
        required_manual_checks=list(_MANUAL_CHECKS),
        source="offline_input",
        is_trade_instruction=False,
    )


def _normalize_market_inputs(
    market_inputs: Mapping[str, IntradayReviewMarketInput] | Iterable[IntradayReviewMarketInput],
) -> Dict[str, IntradayReviewMarketInput]:
    if isinstance(market_inputs, Mapping):
        return {_normalize_code(code): value for code, value in market_inputs.items()}
    return {_normalize_code(item.code): item for item in market_inputs}


def _code(item: Mapping[str, object]) -> str:
    return _normalize_code(item.get("code"))


def _normalize_code(value: object) -> str:
    return str(value or "").strip().upper()


def _morning_action(item: Mapping[str, object], *, is_blocked_morning_item: bool) -> str:
    if is_blocked_morning_item:
        return "BLOCK"
    return str(item.get("position_action") or "HOLD").strip().upper() or "HOLD"


def _price_deviation_pct(market: Optional[IntradayReviewMarketInput]) -> Optional[float]:
    if market is None or market.last_price is None or market.previous_close is None:
        return None
    if market.previous_close <= 0:
        return None
    return round((market.last_price - market.previous_close) / market.previous_close * 100.0, 2)
