# -*- coding: utf-8 -*-
"""Canonical helpers for verified per-stock backtest summaries."""

from __future__ import annotations

import math
import re
from typing import Any, Dict, Mapping, Optional, Tuple


MIN_VERIFIED_BACKTEST_SAMPLE_SIZE = 3
MISSING_TEXT_VALUES = {"", "n/a", "none", "null", "unknown", "nan"}


def normalize_verified_backtest_summary(
    summary: Any,
    *,
    min_sample_size: int = MIN_VERIFIED_BACKTEST_SAMPLE_SIZE,
) -> Optional[Dict[str, Any]]:
    """Return the canonical verified backtest summary contract, or None."""
    if not isinstance(summary, Mapping):
        return None

    sample_size = _coerce_int(_first_present(summary, "completed_count", "total", "sample_size"))
    if sample_size is None or sample_size < min_sample_size:
        return None

    win_rate = _coerce_float(_first_present(summary, "win_rate_pct", "win_rate", "decision_win_rate_pct"))
    direction_accuracy = _coerce_float(
        _first_present(summary, "direction_accuracy_pct", "direction_accuracy", "decision_accuracy_pct")
    )
    avg_return = _coerce_float(
        _first_present(summary, "avg_stock_return_pct", "avg_return", "avg_simulated_return_pct")
    )
    stop_loss_rate = _coerce_float(_first_present(summary, "stop_loss_trigger_rate", "stop_loss_rate"))

    if all(value is None for value in (win_rate, direction_accuracy, avg_return, stop_loss_rate)):
        return None

    eval_window_days = _coerce_int(_first_present(summary, "eval_window_days", "window_days"))
    as_of = _coerce_text(_first_present(summary, "as_of", "computed_at", "checked_at", "updated_at"))
    engine_version = _coerce_text(summary.get("engine_version")) or "unknown"
    source = _coerce_text(summary.get("source")) or "backtest_service"

    return {
        "source": source,
        "sample_size": sample_size,
        "total": sample_size,
        "completed_count": sample_size,
        "eval_window_days": eval_window_days,
        "engine_version": engine_version,
        "as_of": as_of,
        "computed_at": as_of,
        "win_rate_pct": win_rate,
        "win_rate": win_rate,
        "direction_accuracy_pct": direction_accuracy,
        "direction_accuracy": direction_accuracy,
        "avg_stock_return_pct": avg_return,
        "avg_return": avg_return,
        "stop_loss_trigger_rate": stop_loss_rate,
        "stop_loss_rate": stop_loss_rate,
        "verified": True,
    }


def format_verified_backtest_summary(summary: Any) -> str:
    normalized = normalize_verified_backtest_summary(summary)
    if not normalized:
        return ""

    parts = [f"样本数：{normalized['sample_size']}"]
    if normalized.get("win_rate_pct") is not None:
        parts.append(f"胜率：{format_backtest_decimal(normalized['win_rate_pct'])}%")
    if normalized.get("direction_accuracy_pct") is not None:
        parts.append(f"方向准确率：{format_backtest_decimal(normalized['direction_accuracy_pct'])}%")
    if normalized.get("avg_stock_return_pct") is not None:
        parts.append(f"平均收益：{format_backtest_decimal(normalized['avg_stock_return_pct'])}%")
    if normalized.get("stop_loss_trigger_rate") is not None:
        parts.append(f"止损触发率：{format_backtest_decimal(normalized['stop_loss_trigger_rate'])}%")
    if normalized.get("eval_window_days") is not None:
        parts.append(f"窗口：{normalized['eval_window_days']}日")
    if normalized.get("as_of"):
        parts.append(f"截至：{normalized['as_of']}")
    return "；".join(parts)


def format_backtest_decimal(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:.2f}".rstrip("0").rstrip(".")


def looks_like_backtest_claim(text: str) -> bool:
    """Return True when text contains a user-facing historical backtest claim."""
    if not text:
        return False
    return any(_segment_looks_like_backtest_claim(segment) for segment in _iter_claim_segments(text))


def backtest_claim_matches_summary(summary: Any, text: str, *, tolerance: float = 0.1) -> bool:
    """Fail closed unless at least one supported claim is parsed and all parsed claims match."""
    normalized = normalize_verified_backtest_summary(summary)
    if not normalized or not text:
        return False

    for segment in _iter_claim_segments(text):
        if _contains_qualitative_backtest_claim(segment):
            return False

    matched_any = False
    for segment in _iter_backtest_claim_segments(text):
        matched_spans = []
        for pattern, key in _CLAIM_METRIC_PATTERNS:
            expected = normalized.get(key)
            for match in re.finditer(pattern, segment, re.IGNORECASE):
                matched_any = True
                matched_spans.append(match.span())
                claimed_text = match.group(1)
                if _is_missing_claim_value(claimed_text):
                    if expected is not None:
                        return False
                    continue
                if expected is None:
                    return False
                claimed = _coerce_float(claimed_text)
                if claimed is None or abs(claimed - float(expected)) > tolerance:
                    return False

        if _segment_has_unparsed_backtest_value(segment, matched_spans):
            return False

    return matched_any


_CLAIM_VALUE_PATTERN = r"\s*(?:[:：=]|约为|约|为|达到|达)?\s*([+\-]?\d+(?:\.\d+)?|N/A)\s*%?"
_OPTIONAL_LABEL_PATTERN = r"(?:\s*(?:（[^）]{0,20}）|\([^)]{0,20}\)))?"
_BACKTEST_CLAIM_CONTEXT_PATTERN = re.compile(
    r"(?:回测|历史样本).*?(?:样本|窗口|胜率|准确率|平均收益|平均回报|收益率|止损触发率|止损率)"
    r"|历史[^。！？；;!\n]{0,30}(?:胜率|准确率|平均收益|平均回报|收益率|止损触发率|止损率)"
    r"|(?:回测样本|回测窗口)"
    r"\s*(?:（[^）]{0,20}）|\([^)]{0,20}\))?\s*(?:[:：=]|约为|约|为|达到|达)?\s*(?:[+\-]?\d|N/A)",
    re.IGNORECASE,
)
_BARE_BACKTEST_METRIC_CLAIM_PATTERN = re.compile(
    r"(?:^|[，,；;\s])(?:胜率|准确率)"
    r"\s*(?:[:：=]|约为|约|为|达到|达)?\s*[+\-]?\d+(?:\.\d+)?\s*%?"
    r"(?=$|[，,。！？；;!\n])",
    re.IGNORECASE,
)
_QUALITATIVE_BACKTEST_CLAIM_PATTERN = re.compile(
    r"(?:(?:回测|历史样本)[^，,。！？；;!\n]{0,40}|"
    r"历史[^，,。！？；;!\n]{0,30}(?:胜率|准确率|平均收益|平均回报|收益率|止损触发率|止损率)[^，,。！？；;!\n]{0,20})"
    r"(?:较高|很高|偏高|较低|很低|偏低|高|低|优秀|良好|较好|较强|偏强|强劲|稳定|可靠|"
    r"可信|有效|显著|出色|不佳|偏弱|有支持|支持|有支撑|支撑|优于平均|好于平均|优于基准)",
    re.IGNORECASE,
)
_QUALITATIVE_PIGGYBACK_PATTERN = re.compile(
    r"(?:表现|结果|整体|整体表现|回测表现|历史表现|样本表现|信号|判断|结论|策略|"
    r"建仓|买入|加仓|操作|决策|胜率|准确率|命中率|收益|回报)"
    r"[^，,。！？；;!\n]{0,12}"
    r"(?:较高|很高|偏高|较低|很低|偏低|高|低|优秀|良好|较好|较强|偏强|强劲|稳定|可靠|"
    r"可信|有效|显著|出色|不佳|偏弱|有支持|支持|有支撑|支撑|优于平均|好于平均|优于基准)"
    r"|(?:^|[，,])\s*(?:较高|很高|偏高|较低|很低|偏低|优秀|良好|较好|较强|偏强|"
    r"强劲|显著|出色|不佳|偏弱)(?:[，,。！？；;!\n]|$)",
    re.IGNORECASE,
)
_UNPARSED_BACKTEST_VALUE_PATTERN = re.compile(
    rf"(?:"
    rf"(?:历史)?(?:回测)?样本(?:数|量)?|"
    rf"回测窗口|窗口|"
    rf"方向准确率|准确率|胜率|"
    rf"平均收益率|平均收益|平均回报率|平均回报|"
    rf"止损触发率|止损率|"
    rf"最大回撤|回撤|夏普比率|夏普|Sharpe|收益波动率|波动率|盈亏比|命中率|"
    rf"(?:回测|历史样本|历史)[^。！？；;!\n]{{0,20}}(?:收益率|回报率)"
    rf")"
    rf"{_OPTIONAL_LABEL_PATTERN}{_CLAIM_VALUE_PATTERN}",
    re.IGNORECASE,
)


def _iter_claim_segments(text: str) -> Tuple[str, ...]:
    return tuple(segment.strip() for segment in re.split(r"[。！？；;!\n]+", text) if segment.strip())


def _iter_backtest_claim_segments(text: str) -> Tuple[str, ...]:
    return tuple(segment for segment in _iter_claim_segments(text) if _segment_looks_like_backtest_claim(segment))


def _segment_looks_like_backtest_claim(segment: str) -> bool:
    return bool(
        _BACKTEST_CLAIM_CONTEXT_PATTERN.search(segment)
        or _QUALITATIVE_BACKTEST_CLAIM_PATTERN.search(segment)
        or _BARE_BACKTEST_METRIC_CLAIM_PATTERN.search(segment)
    )


def _contains_qualitative_backtest_claim(segment: str) -> bool:
    if _QUALITATIVE_BACKTEST_CLAIM_PATTERN.search(segment):
        return True
    return bool(
        _BACKTEST_CLAIM_CONTEXT_PATTERN.search(segment)
        and _QUALITATIVE_PIGGYBACK_PATTERN.search(segment)
    )


def _segment_has_unparsed_backtest_value(segment: str, matched_spans: list[Tuple[int, int]]) -> bool:
    for value_match in _UNPARSED_BACKTEST_VALUE_PATTERN.finditer(segment):
        if not any(start <= value_match.start() and value_match.end() <= end for start, end in matched_spans):
            return True
    return False


def _is_missing_claim_value(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return value.strip().lower() in MISSING_TEXT_VALUES


def _metric_pattern(label_pattern: str) -> str:
    return rf"{label_pattern}{_OPTIONAL_LABEL_PATTERN}{_CLAIM_VALUE_PATTERN}"


def _sample_pattern() -> str:
    return rf"(?:历史)?(?:回测)?样本(?:数|量)?{_CLAIM_VALUE_PATTERN}\s*(?:次|个)?"


def _window_pattern() -> str:
    return rf"(?:回测窗口|窗口){_CLAIM_VALUE_PATTERN}\s*(?:日|天)?"


def _prefix_window_pattern() -> str:
    return (
        r"(?:过去|近|最近)?\s*([+\-]?\d+(?:\.\d+)?|N/A)\s*(?:日|天)"
        r"[^，,。！？；;!\n]{0,12}"
        r"(?:历史)?(?:回测|胜率|准确率|平均收益|平均回报|收益率|止损触发率|止损率)"
    )


def _suffix_window_pattern() -> str:
    return r"(?:过去|近|最近)?\s*([+\-]?\d+(?:\.\d+)?|N/A)\s*(?:日|天)\s*(?:回测)?窗口"


_CLAIM_METRIC_PATTERNS: Tuple[Tuple[str, str], ...] = (
    (
        _prefix_window_pattern(),
        "eval_window_days",
    ),
    (
        _suffix_window_pattern(),
        "eval_window_days",
    ),
    (
        _metric_pattern(r"(?:方向准确率|准确率)"),
        "direction_accuracy_pct",
    ),
    (
        _metric_pattern(r"胜率"),
        "win_rate_pct",
    ),
    (
        _metric_pattern(r"(?:平均收益率|平均收益|平均回报率|平均回报)"),
        "avg_stock_return_pct",
    ),
    (
        _metric_pattern(r"(?:止损触发率|止损率)"),
        "stop_loss_trigger_rate",
    ),
    (
        _sample_pattern(),
        "sample_size",
    ),
    (
        _window_pattern(),
        "eval_window_days",
    ),
)


def _first_present(summary: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = summary.get(key)
        if _has_value(value):
            return value
    return None


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and value.strip().lower() in MISSING_TEXT_VALUES:
        return False
    if isinstance(value, float) and math.isnan(value):
        return False
    return True


def _coerce_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _coerce_int(value: Any) -> Optional[int]:
    number = _coerce_float(value)
    if number is None:
        return None
    return int(number)


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
