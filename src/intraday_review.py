# -*- coding: utf-8 -*-
"""Offline-only intraday review evaluator.

The evaluator consumes a P2-1 intraday review contract plus externally supplied
market inputs. It does not fetch data, call AI, connect brokers, write accounts,
or mutate the morning summary.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from src.intraday_review_contract import (
    IntradayReviewEvaluation,
    IntradayReviewInput,
    IntradayReviewMarketInput,
    build_intraday_review_input_from_summary,
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


def run_intraday_review_file(
    *,
    summary_path: str | Path,
    market_input_path: str | Path,
    output_dir: str | Path,
) -> Dict[str, str]:
    """Run the offline evaluator from local JSON files and write review artifacts."""
    summary_file = Path(summary_path)
    market_file = Path(market_input_path)
    output_path = Path(output_dir)

    summary = _read_json_object(summary_file)
    market_payload = _read_json_object(market_file)
    review_input = build_intraday_review_input_from_summary(
        summary,
        source_summary_path=str(summary_file),
    )
    market_inputs = _market_inputs_from_payload(market_payload)

    evaluations = evaluate_intraday_review_offline(review_input, market_inputs=market_inputs)
    market_source = str(market_payload.get("source") or "offline_input").strip() or "offline_input"
    output = _build_file_review_payload(
        review_input,
        evaluations=evaluations,
        market_input_codes=set(market_inputs.keys()),
        generated_at=str(market_payload.get("generated_at") or ""),
        market_source=market_source,
    )

    output_path.mkdir(parents=True, exist_ok=True)
    date_slug = _date_slug(review_input.report_date)
    json_path = output_path / f"intraday_review_{date_slug}.json"
    markdown_path = output_path / f"intraday_review_{date_slug}.md"

    json_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    markdown_path.write_text(_render_file_review_markdown(output), encoding="utf-8")

    return {
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
    }


def _build_file_review_payload(
    review_input: IntradayReviewInput,
    *,
    evaluations: Mapping[str, IntradayReviewEvaluation],
    market_input_codes: set[str],
    generated_at: str,
    market_source: str,
) -> Dict[str, Any]:
    summary_codes = _summary_codes(review_input)
    extra_codes = sorted(code for code in market_input_codes if code not in summary_codes)
    warnings = []
    if extra_codes:
        warnings.append(f"Ignored market input for symbols not present in summary: {', '.join(extra_codes)}")

    return {
        "report_date": review_input.report_date,
        "source_summary_path": review_input.source_summary_path,
        "generated_at": generated_at,
        "price_policy": review_input.price_policy,
        "technical_basis_date": review_input.technical_basis_date,
        "is_trade_instruction": False,
        "warnings": warnings,
        "items": [
            _file_review_item(evaluation, market_source=market_source)
            for code, evaluation in evaluations.items()
            if code in summary_codes
        ],
    }


def _file_review_item(evaluation: IntradayReviewEvaluation, *, market_source: str) -> Dict[str, Any]:
    return {
        "code": evaluation.code,
        "morning_action": evaluation.morning_action,
        "review_status": evaluation.review_status,
        "reason": evaluation.reason,
        "price_deviation_pct": evaluation.price_deviation_pct,
        "required_checks": list(evaluation.required_manual_checks),
        "source": market_source or evaluation.source,
        "is_trade_instruction": False,
    }


def _render_file_review_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        f"# 盘中复核结果 {payload.get('report_date') or ''}".rstrip(),
        "",
        "- 这是盘中复核结果",
        "- 数据来自输入文件",
        "- 不自动下单",
        "- 执行前确认价格、公告、流动性",
        "",
        f"- 价格口径：{payload.get('price_policy') or 'unknown'}",
        f"- 技术基准日：{payload.get('technical_basis_date') or 'unknown'}",
        "",
        "| 标的 | Morning action | 复核状态 | 价格偏离 | 说明 |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for item in payload.get("items") or []:
        deviation = item.get("price_deviation_pct")
        deviation_text = "n/a" if deviation is None else f"{float(deviation):+.2f}%"
        lines.append(
            "| {code} | {morning_action} | {review_status} | {deviation} | {reason} |".format(
                code=item.get("code") or "",
                morning_action=item.get("morning_action") or "",
                review_status=item.get("review_status") or "",
                deviation=deviation_text,
                reason=_markdown_cell(str(item.get("reason") or "")),
            )
        )

    manual_check_items = [
        item
        for item in payload.get("items") or []
        if item.get("required_checks")
    ]
    if manual_check_items:
        lines.extend(
            [
                "",
                "## 人工复核清单",
                "",
                "以下检查必须由人工完成；盘中复核不自动下单，也不连接券商。",
            ]
        )
        for item in manual_check_items:
            code = _markdown_cell(str(item.get("code") or "未知标的"))
            lines.extend(["", f"### {code}"])
            for check in item.get("required_checks") or []:
                lines.append(f"- {_markdown_cell(str(check))}")

    warnings = payload.get("warnings") or []
    if warnings:
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {_markdown_cell(str(warning))}" for warning in warnings)

    return "\n".join(lines).rstrip() + "\n"


def _read_json_object(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    return payload


def _market_inputs_from_payload(payload: Mapping[str, Any]) -> Dict[str, IntradayReviewMarketInput]:
    items = payload.get("items") or []
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        raise ValueError("market input JSON requires an items array.")
    markets = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        markets.append(IntradayReviewMarketInput.from_dict(dict(item)))
    return _normalize_market_inputs(markets)


def _summary_codes(review_input: IntradayReviewInput) -> set[str]:
    codes = set()
    for bucket in (review_input.actionable_items, review_input.watch_items, review_input.blocked_items):
        for item in bucket:
            codes.add(_code(item))
    return codes


def _date_slug(report_date: str) -> str:
    slug = "".join(ch for ch in str(report_date or "") if ch.isdigit())
    return slug or "unknown"


def _markdown_cell(value: str) -> str:
    return value.replace("|", "/").replace("\n", " ")


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
            "missing_input: No offline market input was supplied; evaluator cannot assess validity without guessing.",
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
