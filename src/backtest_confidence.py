# -*- coding: utf-8 -*-
"""Display-only backtest confidence helpers for daily reports."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


ACTION_BUCKETS = ("OPEN", "ADD", "REDUCE", "CLOSE")
SCORE_BUCKETS = ("60_70", "70_80", "80_100")
SCORE_BUCKET_RANGES = {
    "60_70": (60.0, 70.0),
    "70_80": (70.0, 80.0),
    "80_100": (80.0, 100.0),
}
MIN_CONFIDENCE_SAMPLE_SIZE = 20


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any) -> Optional[float]:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _confidence_level(sample_size: int) -> str:
    return "usable_sample" if sample_size >= MIN_CONFIDENCE_SAMPLE_SIZE else "low_sample"


def _empty_action_entry() -> Dict[str, Any]:
    return {
        "sample_size": 0,
        "win_rate_pct": None,
        "avg_simulated_return_pct": None,
        "confidence_level": "low_sample",
    }


def _empty_score_bucket_entry(window_days: int) -> Dict[str, Any]:
    entry = _empty_action_entry()
    entry["window_days"] = window_days
    return entry


def _average(values: Iterable[Optional[float]]) -> Optional[float]:
    items = [float(value) for value in values if value is not None]
    if not items:
        return None
    return round(sum(items) / len(items), 4)


def _read_attr(row: Any, key: str) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    return getattr(row, key, None)


def score_bucket_for_score(value: Any) -> Optional[str]:
    """Return the configured score bucket label for a 0-100 score."""
    score = _safe_float(value)
    if score is None:
        return None
    for bucket, (lower, upper) in SCORE_BUCKET_RANGES.items():
        if bucket == "80_100":
            if lower <= score <= upper:
                return bucket
        elif lower <= score < upper:
            return bucket
    return None


def _build_action_entry(rows: List[Any]) -> Dict[str, Any]:
    sample_size = len(rows)
    wins = sum(1 for row in rows if str(_read_attr(row, "outcome") or "").strip() == "win")
    losses = sum(1 for row in rows if str(_read_attr(row, "outcome") or "").strip() == "loss")
    denominator = wins + losses
    win_rate_pct = round(wins / denominator * 100, 2) if denominator else None
    return {
        "sample_size": sample_size,
        "win_rate_pct": win_rate_pct,
        "avg_simulated_return_pct": _average(_safe_float(_read_attr(row, "simulated_return_pct")) for row in rows),
        "confidence_level": _confidence_level(sample_size),
    }


def _build_score_bucket_entry(rows: List[Any], *, window_days: int) -> Dict[str, Any]:
    entry = _build_action_entry(rows)
    entry["window_days"] = window_days
    return entry


def _format_score(value: Any) -> str:
    score = _safe_float(value)
    if score is None:
        return "N/A"
    if score.is_integer():
        return str(int(score))
    return f"{score:.1f}"


def _build_current_score_items(
    current_results: Iterable[Any],
    *,
    format_stock_display_name: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    current_items: List[Dict[str, Any]] = []
    for result in current_results or []:
        score = _safe_float(_read_attr(result, "sentiment_score"))
        bucket = score_bucket_for_score(score)
        if bucket is None:
            continue
        code = str(_read_attr(result, "code") or "")
        name = _read_attr(result, "name") or code
        if format_stock_display_name is not None:
            display_name = format_stock_display_name(name, code)
        else:
            display_name = f"{name} ({code})" if code else str(name)
        current_items.append(
            {
                "code": code,
                "name": display_name,
                "sentiment_score": int(score) if score.is_integer() else round(score, 1),
                "bucket": bucket,
            }
        )
    return current_items


def build_backtest_confidence_panel(
    *,
    summary: Optional[Dict[str, Any]],
    action_results: Iterable[Any],
    window_days: Optional[int],
) -> Dict[str, Any]:
    """Build a report-only confidence panel from existing backtest data."""
    resolved_window = _safe_int((summary or {}).get("eval_window_days"), _safe_int(window_days, 0))
    sample_size = _safe_int((summary or {}).get("completed_count"))
    overall = {
        "sample_size": sample_size,
        "window_days": resolved_window,
        "win_rate_pct": _safe_float((summary or {}).get("win_rate_pct")),
        "avg_simulated_return_pct": _safe_float((summary or {}).get("avg_simulated_return_pct")),
        "confidence_level": _confidence_level(sample_size),
    }

    grouped: Dict[str, List[Any]] = {action: [] for action in ACTION_BUCKETS}
    for row in action_results or []:
        if str(_read_attr(row, "eval_status") or "").strip() != "completed":
            continue
        action = str(_read_attr(row, "position_action") or "").strip().upper()
        if action in grouped:
            grouped[action].append(row)

    by_action = {
        action: _build_action_entry(rows) if rows else _empty_action_entry()
        for action, rows in grouped.items()
    }

    return {
        "overall": overall,
        "by_action": by_action,
    }


def build_score_bucket_calibration(
    *,
    score_results: Iterable[Any],
    window_days: Optional[int],
    current_results: Optional[Iterable[Any]] = None,
    format_stock_display_name: Optional[Any] = None,
) -> Dict[str, Any]:
    """Build display-only historical calibration grouped by score bucket."""
    resolved_window = _safe_int(window_days)
    grouped: Dict[str, List[Any]] = {bucket: [] for bucket in SCORE_BUCKETS}
    for row in score_results or []:
        status = str(_read_attr(row, "eval_status") or "").strip()
        if status and status != "completed":
            continue
        bucket = score_bucket_for_score(_read_attr(row, "sentiment_score"))
        if bucket in grouped:
            grouped[bucket].append(row)

    calibration: Dict[str, Any] = {
        bucket: _build_score_bucket_entry(rows, window_days=resolved_window)
        if rows
        else _empty_score_bucket_entry(resolved_window)
        for bucket, rows in grouped.items()
    }
    calibration["current_items"] = _build_current_score_items(
        current_results or [],
        format_stock_display_name=format_stock_display_name,
    )
    return calibration


def with_current_score_bucket_items(
    calibration: Dict[str, Any],
    *,
    current_results: Iterable[Any],
    format_stock_display_name: Optional[Any] = None,
) -> Dict[str, Any]:
    """Attach current non-blocked report scores without changing bucket statistics."""
    calibration = calibration if isinstance(calibration, dict) else {}
    first_window = 0
    for bucket in SCORE_BUCKETS:
        entry = calibration.get(bucket)
        if isinstance(entry, dict):
            first_window = _safe_int(entry.get("window_days"))
            break

    result: Dict[str, Any] = {
        bucket: dict(calibration.get(bucket) or _empty_score_bucket_entry(first_window))
        for bucket in SCORE_BUCKETS
    }
    result["current_items"] = _build_current_score_items(
        current_results,
        format_stock_display_name=format_stock_display_name,
    )
    return result


def _format_pct(value: Any, *, signed: bool = False) -> str:
    number = _safe_float(value)
    if number is None:
        return "N/A"
    if signed and number > 0:
        return f"+{number:.2f}%"
    return f"{number:.2f}%"


def _action_count_for_bucket(action: str, action_counts: Dict[str, Any]) -> int:
    key = {
        "OPEN": "buy",
        "ADD": "add",
        "REDUCE": "reduce",
        "CLOSE": "close",
    }[action]
    return _safe_int(action_counts.get(key))


def render_backtest_confidence_lines(
    panel: Dict[str, Any],
    *,
    action_counts: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Render historical calibration lines without creating trade signals."""
    overall = panel.get("overall") if isinstance(panel, dict) else {}
    overall = overall or {}
    sample_size = _safe_int(overall.get("sample_size"))
    window_days = _safe_int(overall.get("window_days"))
    window_text = f"{window_days} 日窗口" if window_days else "窗口未知"

    lines = [
        "## 历史校准",
        "",
    ]
    if sample_size <= 0:
        lines.append(f"- 历史校准：{window_text}，无可用回测摘要，历史样本不足，不作为置信增强。")
    elif overall.get("confidence_level") == "low_sample":
        lines.append(f"- 历史校准：{window_text}，样本 {sample_size} 次，历史样本不足，不作为置信增强。")
    else:
        lines.append(
            f"- 历史校准：{window_text}，样本 {sample_size} 次，"
            f"胜率 {_format_pct(overall.get('win_rate_pct'))}，"
            f"平均模拟收益 {_format_pct(overall.get('avg_simulated_return_pct'), signed=True)}；"
            "仅作历史校准，个股回测状态以证据矩阵为准。"
        )

    active_counts = action_counts or {}
    by_action = panel.get("by_action") if isinstance(panel, dict) else {}
    by_action = by_action or {}
    for action in ACTION_BUCKETS:
        if _action_count_for_bucket(action, active_counts) <= 0:
            continue
        entry = by_action.get(action) or _empty_action_entry()
        action_sample = _safe_int(entry.get("sample_size"))
        if action_sample < MIN_CONFIDENCE_SAMPLE_SIZE:
            lines.append(f"- {action} 历史样本：样本 {action_sample} 次，样本不足，不作为置信增强。")
        else:
            lines.append(
                f"- {action} 历史样本：样本 {action_sample} 次，"
                f"胜率 {_format_pct(entry.get('win_rate_pct'))}，"
                f"平均模拟收益 {_format_pct(entry.get('avg_simulated_return_pct'), signed=True)}；"
                "仅作历史校准，个股回测状态以证据矩阵为准。"
            )

    lines.extend(["", ""])
    return lines


def render_score_bucket_calibration_lines(calibration: Dict[str, Any]) -> List[str]:
    """Render score-bucket calibration without implying trade certainty."""
    calibration = calibration if isinstance(calibration, dict) else {}
    current_items = calibration.get("current_items") or []
    lines = [
        "## 评分校准",
        "",
    ]

    if not current_items:
        lines.append("- 评分校准：当前结果缺少可映射评分，跳过评分校准；不作为置信增强。")
        lines.extend(["", ""])
        return lines

    for item in current_items:
        bucket = str(item.get("bucket") or "")
        entry = calibration.get(bucket) or _empty_score_bucket_entry(0)
        sample_size = _safe_int(entry.get("sample_size"))
        window_days = _safe_int(entry.get("window_days"))
        window_text = f"{window_days} 日窗口" if window_days else "窗口未知"
        label = f"{item.get('name')} 评分 {_format_score(item.get('sentiment_score'))} -> {bucket}"
        if sample_size < MIN_CONFIDENCE_SAMPLE_SIZE:
            lines.append(f"- {label}：{window_text}，样本 {sample_size} 次，样本不足，不作为置信增强。")
        else:
            lines.append(
                f"- {label}：{window_text}，样本 {sample_size} 次，"
                f"胜率 {_format_pct(entry.get('win_rate_pct'))}，"
                f"平均模拟收益 {_format_pct(entry.get('avg_simulated_return_pct'), signed=True)}；"
                "仅作历史校准，不是交易保证；个股回测状态以证据矩阵为准。"
            )

    lines.extend(["", ""])
    return lines
