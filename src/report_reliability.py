# -*- coding: utf-8 -*-
"""Simple report-level reliability scoring for daily decision summaries."""

from __future__ import annotations

from typing import Any, Dict, List


LEVEL_LABELS = {
    "high": "可作为开盘前人工复核计划",
    "usable_with_manual_review": "可用但需人工复核",
    "low_observe_only": "仅观察",
}
TRAILING_REASON_PUNCTUATION = "。；;,.，.!！？?"


def build_report_reliability(
    *,
    price_policy: str,
    price_basis_counts: Dict[str, Any],
    evidence_matrix: Dict[str, List[Dict[str, Any]]],
    evidence_summary: Dict[str, Any],
    data_quality_flags: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build transparent report reliability metadata without changing actions."""
    flags: List[Dict[str, str]] = []
    stock_count = _stock_count(evidence_matrix, evidence_summary)
    components = {
        "price_basis_consistency": _score_price_basis(price_policy, price_basis_counts, flags),
        "market_data_freshness": _score_market_data(stock_count, evidence_summary, flags),
        "evidence_completeness": _score_evidence_completeness(evidence_matrix, flags),
        "validation_health": _score_validation_health(stock_count, evidence_summary, data_quality_flags, flags),
        "backtest_support": _score_backtest_support(evidence_matrix, evidence_summary, flags),
    }
    score = _clamp_score(sum(components.values()))
    level = _level_for_score(score)
    if level == "low_observe_only":
        flags.append(
            {
                "code": "low_reliability",
                "severity": "warning",
                "message": "报告可信度偏低：不建议直接依据本报告执行，仅用于观察和人工复核。",
            }
        )
    return {
        "score": score,
        "level": level,
        "components": components,
        "flags": flags,
    }


def render_report_reliability_lines(reliability: Dict[str, Any]) -> List[str]:
    """Render report reliability near the cockpit top."""
    if not reliability:
        return []
    score = int(reliability.get("score") or 0)
    level = str(reliability.get("level") or "low_observe_only")
    label = LEVEL_LABELS.get(level, LEVEL_LABELS["low_observe_only"])
    flags = reliability.get("flags") or []
    warning = next((flag for flag in flags if flag.get("code") == "low_reliability"), None)
    reasons = [
        normalize_reliability_reason(flag.get("message"))
        for flag in flags
        if flag.get("code") != "low_reliability" and normalize_reliability_reason(flag.get("message"))
    ]
    lines = [
        f"**报告可信度：{score} / 100**",
        f"- 等级：{label}（{level}）",
    ]
    if reasons:
        lines.append(f"- 主要扣分项：{'；'.join(reasons[:3])}。")
    else:
        lines.append("- 主要扣分项：无重大扣分项。")
    if warning:
        lines.append(f"- {warning.get('message')}")
    lines.append("")
    return lines


def normalize_reliability_reason(message: Any) -> str:
    """Return a compact reason that can be joined with Chinese punctuation."""
    return str(message or "").strip().rstrip(TRAILING_REASON_PUNCTUATION)


def _stock_count(matrix: Dict[str, List[Dict[str, Any]]], summary: Dict[str, Any]) -> int:
    try:
        count = int(summary.get("stock_count") or 0)
    except (TypeError, ValueError):
        count = 0
    return count if count > 0 else len(matrix)


def _score_price_basis(price_policy: str, counts: Dict[str, Any], flags: List[Dict[str, str]]) -> int:
    policy = str(price_policy or "close_only").strip().lower()
    if policy == "close_only":
        return 20
    if policy == "mixed":
        score = 5
        detail = "价格来源混用，不是纯昨收计划。"
    elif policy == "latest_close":
        score = 14
        detail = "价格来源为最新收盘数据，需确认是否仍为昨收计划。"
    elif policy == "realtime":
        score = 10
        detail = "价格来源包含实时价格，不是纯开盘前昨收计划。"
    else:
        score = 8
        detail = f"价格来源为 {policy or '未知'}，需人工确认。"
    flags.append(
        {
            "code": "price_basis_mismatch",
            "severity": "warning",
            "message": f"{detail} 计数：{_format_counts(counts)}。",
        }
    )
    return score


def _score_market_data(stock_count: int, summary: Dict[str, Any], flags: List[Dict[str, str]]) -> int:
    if stock_count <= 0:
        flags.append({"code": "market_data_missing", "severity": "warning", "message": "没有可审计的行情数据。"})
        return 0
    available = _int_value(summary.get("market_data_available"))
    score = round(20 * max(0, min(available, stock_count)) / stock_count)
    missing = stock_count - available
    if missing > 0:
        flags.append(
            {
                "code": "market_data_missing",
                "severity": "warning",
                "message": f"{missing}/{stock_count} 只股票行情数据缺失或过期。",
            }
        )
    return score


def _score_evidence_completeness(matrix: Dict[str, List[Dict[str, Any]]], flags: List[Dict[str, str]]) -> int:
    categories = {"technical", "valuation", "news", "announcement"}
    total = 0
    issue_count = 0
    missing = 0
    announcement_not_checked = 0
    announcement_unavailable = 0
    announcement_risk_found = 0
    for entries in matrix.values():
        for entry in entries:
            if entry.get("category") not in categories:
                continue
            total += 1
            status = entry.get("status")
            if entry.get("category") == "announcement":
                if status == "not_checked":
                    announcement_not_checked += 1
                    issue_count += 1
                    continue
                if status == "unavailable":
                    announcement_unavailable += 1
                    issue_count += 1
                    continue
                if status == "risk_found":
                    announcement_risk_found += 1
                    issue_count += 1
                    continue
            if status in {"missing", "stale", "not_checked", "unavailable"}:
                missing += 1
                issue_count += 1
    if total <= 0:
        flags.append({"code": "evidence_missing", "severity": "warning", "message": "技术 / 估值 / 新闻 / 公告证据不可审计。"})
        return 0
    score = round(25 * (total - issue_count) / total)
    if missing > 0:
        flags.append(
            {
                "code": "evidence_missing",
                "severity": "warning",
                "message": f"{missing}/{total} 项技术 / 估值 / 新闻证据缺失、过期或未检查。",
            }
        )
    if announcement_not_checked > 0:
        flags.append(
            {
                "code": "asx_announcement_not_checked",
                "severity": "warning",
                "message": f"{announcement_not_checked} 只股票 ASX 官方公告未检查；执行前检查公告。",
            }
        )
    if announcement_unavailable > 0:
        flags.append(
            {
                "code": "asx_announcement_unavailable",
                "severity": "warning",
                "message": f"{announcement_unavailable} 只股票 ASX 公告源不可用；执行前检查公告。",
            }
        )
    if announcement_risk_found > 0:
        flags.append(
            {
                "code": "asx_announcement_risk_found",
                "severity": "block",
                "message": f"{announcement_risk_found} 只股票检测到 price-sensitive 公告风险；详见证据矩阵。",
            }
        )
    return score


def _score_validation_health(
    stock_count: int,
    summary: Dict[str, Any],
    data_quality_flags: List[Dict[str, Any]],
    flags: List[Dict[str, str]],
) -> int:
    block_count = _int_value(summary.get("validation_block"))
    if stock_count <= 0:
        return 0
    score = 0 if block_count > 0 else 25
    if block_count > 0:
        flags.append(
            {
                "code": "validation_block",
                "severity": "block",
                "message": f"{block_count}/{stock_count} 只股票触发 validation BLOCK；BLOCK 仍硬阻断可执行语义。",
            }
        )
    for flag in data_quality_flags:
        if str(flag.get("severity") or "").lower() == "block" and str(flag.get("code") or "") != "validation_block":
            flags.append(
                {
                    "code": str(flag.get("code") or "data_quality_block"),
                    "severity": "block",
                    "message": str(flag.get("message") or "存在数据质量阻断。"),
                }
            )
    return score


def _score_backtest_support(
    matrix: Dict[str, List[Dict[str, Any]]],
    summary: Dict[str, Any],
    flags: List[Dict[str, str]],
) -> int:
    total = 0
    missing = 0
    for entries in matrix.values():
        for entry in entries:
            if entry.get("category") == "backtest":
                total += 1
                if entry.get("status") in {"missing", "stale", "not_checked"}:
                    missing += 1
    if total <= 0:
        total = _stock_count(matrix, summary)
        missing = total
    if total <= 0:
        return 0
    score = round(10 - (4 * missing / total))
    if missing > 0:
        flags.append(
            {
                "code": "backtest_not_checked",
                "severity": "warning",
                "message": f"{missing}/{total} 只股票回测证据未检查；仅小幅降低报告可信度，不改变动作。",
            }
        )
    return max(0, min(10, score))


def _level_for_score(score: int) -> str:
    if score >= 80:
        return "high"
    if score >= 55:
        return "usable_with_manual_review"
    return "low_observe_only"


def _clamp_score(value: Any) -> int:
    try:
        score = int(round(float(value)))
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, score))


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _format_counts(counts: Dict[str, Any]) -> str:
    if not counts:
        return "暂无"
    labels = {
        "close_only": "昨收",
        "latest_close": "最新收盘",
        "realtime": "实时价",
    }
    return "，".join(f"{labels.get(key, key)} {counts.get(key, 0)}" for key in sorted(counts))
