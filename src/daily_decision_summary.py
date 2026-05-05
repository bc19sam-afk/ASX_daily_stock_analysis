# -*- coding: utf-8 -*-
"""Stable pre-open daily decision summary builders.

This module is intentionally deterministic: it summarizes already-computed
position actions, portfolio view, and validation outcomes. It does not ask AI
to reinterpret or change any action.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional

from src.core.validator import normalize_validation_status
from src.evidence_matrix import build_evidence_matrix, summarize_evidence_matrix


ACTION_COUNT_KEYS = ("buy", "add", "reduce", "close", "hold_watch", "blocked")
EXECUTABLE_ACTIONS = {"OPEN", "ADD", "REDUCE", "CLOSE"}
DEFAULT_ACTIONABLE_DELTA_AMOUNT = 20.0
EXECUTION_CHECKLIST = [
    "确认报告为昨收计划 / 开盘前计划，技术信号基于已收盘日线。",
    "开盘后执行前复核实时价格、盘口流动性和重大新闻。",
    "BLOCK 或数据质量风险未解除前，不把对应标的当作可执行动作。",
]
WATCH_TRIGGER_RULE = "仅在价格突破/回撤到参考位、验证状态变化、或出现重大新闻/财报事件时再打开观察名单。"


def _normalize_stock_code(code: Any) -> str:
    return str(code or "").strip().upper()


def _is_failed_analysis(result: Any) -> bool:
    if not bool(getattr(result, "success", True)):
        return True
    return str(getattr(result, "analysis_status", "") or "").strip().upper() == "FAILED"


def _is_blocked(result: Any) -> bool:
    return normalize_validation_status(getattr(result, "validation_status", None)) == "BLOCK"


def _normal_date(value: Any) -> Optional[str]:
    raw = str(value or "").strip()
    if raw.lower() in {"", "none", "null", "n/a", "unknown", "未知"}:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
    except Exception:
        return raw[:10] if len(raw) >= 10 else raw


def _display_name(result: Any, formatter: Callable[[Any, Any], str]) -> str:
    return formatter(getattr(result, "name", ""), getattr(result, "code", ""))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def is_effective_executable_action(
    action_model: Dict[str, Any],
    *,
    min_delta_amount: float = DEFAULT_ACTIONABLE_DELTA_AMOUNT,
) -> bool:
    """Return True when an action is large enough to present as executable."""
    action = str(action_model.get("position_action") or "HOLD").upper()
    if action not in EXECUTABLE_ACTIONS:
        return False
    threshold = max(_safe_float(min_delta_amount, DEFAULT_ACTIONABLE_DELTA_AMOUNT), 0.0)
    if threshold <= 0:
        return True
    return abs(_safe_float(action_model.get("delta_amount"))) >= threshold


def _basis_counts(results: Iterable[Any], classify_price_basis: Callable[[Any], str]) -> Dict[str, int]:
    counts = {"realtime": 0, "latest_close": 0, "close_only": 0}
    for result in results:
        basis = classify_price_basis(result)
        if basis not in counts:
            basis = "close_only"
        counts[basis] += 1
    return counts


def _resolve_price_policy(counts: Dict[str, int]) -> str:
    active = [key for key, value in counts.items() if value > 0]
    if not active:
        return "close_only"
    if len(active) == 1:
        return active[0]
    return "mixed"


def _build_item(
    result: Any,
    *,
    action_model: Dict[str, Any],
    is_current_holding: bool,
    classify_price_basis: Callable[[Any], str],
    format_stock_display_name: Callable[[Any, Any], str],
) -> Dict[str, Any]:
    return {
        "code": str(getattr(result, "code", "") or ""),
        "name": _display_name(result, format_stock_display_name),
        "position_action": str(action_model.get("position_action") or "HOLD"),
        "target_weight": _safe_float(action_model.get("target_weight")),
        "current_weight": _safe_float(getattr(result, "current_weight", 0.0)),
        "delta_amount": _safe_float(action_model.get("delta_amount")),
        "is_current_holding": is_current_holding,
        "price_basis": classify_price_basis(result),
        "reason": str(getattr(result, "action_reason", "") or ""),
    }


def build_daily_decision_summary(
    *,
    results: List[Any],
    report_date: str,
    generated_at: datetime,
    overview: Dict[str, Any],
    get_primary_action_model: Callable[[Any], Dict[str, Any]],
    classify_price_basis: Callable[[Any], str],
    format_stock_display_name: Callable[[Any, Any], str],
    format_validation_issue_text: Callable[[Any], str],
    min_action_delta_amount: float = DEFAULT_ACTIONABLE_DELTA_AMOUNT,
) -> Dict[str, Any]:
    """Build a stable summary for pre-open reporting and future intraday review."""
    successful_results = [r for r in results if not _is_failed_analysis(r)]
    failed_results = [r for r in results if _is_failed_analysis(r)]
    blocked_results = [r for r in successful_results if _is_blocked(r)]
    decision_results = [r for r in successful_results if not _is_blocked(r)]

    holdings = overview.get("holdings") or []
    holding_codes = {
        _normalize_stock_code(item.get("code"))
        for item in holdings
        if _normalize_stock_code(item.get("code"))
    }
    successful_codes = {
        _normalize_stock_code(getattr(result, "code", ""))
        for result in successful_results
        if _normalize_stock_code(getattr(result, "code", ""))
    }

    action_counts = {key: 0 for key in ACTION_COUNT_KEYS}
    action_counts["total_actions"] = 0
    actionable_items: List[Dict[str, Any]] = []
    watch_items: List[Dict[str, Any]] = []

    for result in decision_results:
        model = get_primary_action_model(result)
        action = str(model.get("position_action") or "HOLD").upper()
        code = _normalize_stock_code(getattr(result, "code", ""))
        is_current_holding = code in holding_codes or _safe_float(getattr(result, "current_weight", 0.0)) > 0
        item = _build_item(
            result,
            action_model=model,
            is_current_holding=is_current_holding,
            classify_price_basis=classify_price_basis,
            format_stock_display_name=format_stock_display_name,
        )

        if not is_effective_executable_action(model, min_delta_amount=min_action_delta_amount):
            action_counts["hold_watch"] += 1
            watch_item = dict(item)
            if action in EXECUTABLE_ACTIONS:
                watch_item["suppressed_position_action"] = action
                watch_item["suppressed_delta_amount"] = item["delta_amount"]
            watch_item["position_action"] = "HOLD"
            watch_item["target_weight"] = item["current_weight"]
            watch_item["delta_amount"] = 0.0
            watch_item["trigger"] = WATCH_TRIGGER_RULE
            watch_items.append(watch_item)
        elif action == "OPEN":
            action_counts["buy"] += 1
            action_counts["total_actions"] += 1
            actionable_items.append(item)
        elif action == "ADD":
            action_counts["add"] += 1
            action_counts["total_actions"] += 1
            actionable_items.append(item)
        elif action == "REDUCE":
            action_counts["reduce"] += 1
            action_counts["total_actions"] += 1
            actionable_items.append(item)
        elif action == "CLOSE":
            action_counts["close"] += 1
            action_counts["total_actions"] += 1
            actionable_items.append(item)
        else:
            action_counts["hold_watch"] += 1
            watch_item = dict(item)
            watch_item["trigger"] = WATCH_TRIGGER_RULE
            watch_items.append(watch_item)

    blocked_items = []
    for result in blocked_results:
        current_weight = _safe_float(getattr(result, "current_weight", 0.0))
        model = get_primary_action_model(result)
        blocked_items.append(
            {
                "code": str(getattr(result, "code", "") or ""),
                "name": _display_name(result, format_stock_display_name),
                "reason": format_validation_issue_text(result),
                "current_weight": current_weight,
                "target_weight": _safe_float(model.get("target_weight"), current_weight),
                "price_basis": classify_price_basis(result),
            }
        )
    action_counts["blocked"] = len(blocked_items)

    technical_dates = sorted(
        {
            normalized
            for result in results
            for normalized in [_normal_date((getattr(result, "market_snapshot", None) or {}).get("date"))]
            if normalized
        }
    )
    if not technical_dates:
        technical_basis_date = "unknown"
    elif len(technical_dates) == 1:
        technical_basis_date = technical_dates[0]
    else:
        technical_basis_date = f"{technical_dates[0]}~{technical_dates[-1]}"

    counts = _basis_counts(successful_results, classify_price_basis)
    price_policy = _resolve_price_policy(counts)

    data_quality_flags: List[Dict[str, Any]] = []
    if len(technical_dates) > 1:
        data_quality_flags.append(
            {
                "code": "mixed_technical_basis_date",
                "severity": "warning",
                "message": f"多只股票技术基准日不一致：{', '.join(technical_dates)}",
            }
        )
    if price_policy != "close_only":
        data_quality_flags.append(
            {
                "code": "non_close_only_price_policy",
                "severity": "warning",
                "message": f"价格口径为 {price_policy}，不是纯昨收计划。",
            }
        )
    if blocked_items:
        data_quality_flags.append(
            {
                "code": "validation_block",
                "severity": "block",
                "message": f"{len(blocked_items)} 只标的触发 BLOCK，只能观察。",
            }
        )
    if failed_results:
        data_quality_flags.append(
            {
                "code": "analysis_failed",
                "severity": "warning",
                "message": f"{len(failed_results)} 只标的分析失败，建议重跑。",
            }
        )

    uncovered_holdings = []
    for item in holdings:
        code = _normalize_stock_code(item.get("code"))
        if code and code not in successful_codes:
            uncovered_holdings.append(
                {
                    "code": str(item.get("code", "") or ""),
                    "name": str(item.get("name") or item.get("code") or ""),
                    "weight": _safe_float(item.get("weight")),
                }
            )
    if uncovered_holdings:
        data_quality_flags.append(
            {
                "code": "uncovered_holding",
                "severity": "warning",
                "message": f"{len(uncovered_holdings)} 只当前持仓未被今日个股分析覆盖。",
            }
        )

    for result in successful_results:
        flag = str(getattr(result, "data_quality_flag", "") or "").upper()
        if flag and flag != "OK":
            data_quality_flags.append(
                {
                    "code": "result_data_quality",
                    "severity": "warning",
                    "message": f"{_display_name(result, format_stock_display_name)} 数据质量标记：{flag}",
                }
            )

    evidence_matrix = build_evidence_matrix(
        results=successful_results,
        overview=overview,
        classify_price_basis=classify_price_basis,
        format_validation_issue_text=format_validation_issue_text,
    )
    evidence_summary = summarize_evidence_matrix(evidence_matrix)

    return {
        "schema_version": "daily_decision_summary.v1.1",
        "report_date": report_date,
        "technical_basis_date": technical_basis_date,
        "technical_basis_dates": technical_dates,
        "price_policy": price_policy,
        "price_basis_counts": counts,
        "generated_at": generated_at.isoformat(),
        "stock_count": len(results),
        "successful_count": len(successful_results),
        "failed_count": len(failed_results),
        "action_counts": action_counts,
        "actionable_items": actionable_items,
        "watch_items": watch_items,
        "blocked_items": blocked_items,
        "uncovered_holdings": uncovered_holdings,
        "data_quality_flags": data_quality_flags,
        "evidence_matrix": evidence_matrix,
        "evidence_summary": evidence_summary,
        "execution_checklist": list(EXECUTION_CHECKLIST),
        "watch_trigger_rule": WATCH_TRIGGER_RULE,
    }


def _format_action_item(item: Dict[str, Any]) -> str:
    action = str(item.get("position_action") or "HOLD").upper()
    action_label = {
        "OPEN": "买入/新开仓",
        "ADD": "加仓",
        "REDUCE": "减仓",
        "CLOSE": "清仓",
    }.get(action, "持有观察")
    target_weight = _safe_float(item.get("target_weight"))
    delta_amount = _safe_float(item.get("delta_amount"))
    return f"{item.get('name')}：{action_label}，目标仓位 {target_weight:.2%}，模拟调仓 {delta_amount:,.2f}"


def render_preopen_decision_dashboard(summary: Dict[str, Any]) -> List[str]:
    """Render the one-screen deterministic cockpit as Markdown lines."""
    counts = summary.get("action_counts") or {}
    flags = summary.get("data_quality_flags") or []
    current_holding_actions = [
        item for item in summary.get("actionable_items", []) if item.get("is_current_holding")
    ]
    watch_items = summary.get("watch_items") or []
    blocked_items = summary.get("blocked_items") or []
    uncovered_holdings = summary.get("uncovered_holdings") or []

    lines = [
        "## 开盘前决策驾驶舱",
        "",
        "> 昨收计划 / 开盘前计划：本页只汇总确定性动作、当前组合视图和验证闸门结果；不是实时交易建议。开盘后执行前必须复核实时价格。",
        "",
        "| 项目 | 内容 |",
        "|---|---|",
        f"| 报告日 | {summary.get('report_date', 'unknown')} |",
        f"| 技术基准日 / 价格基准 | {summary.get('technical_basis_date', 'unknown')} / {summary.get('price_policy', 'close_only')}（收盘口径） |",
        f"| 今日总动作数量 | **{counts.get('total_actions', 0)}** |",
        (
            "| 买入 / 加仓 / 减仓 / 清仓 / 持有观察 / 阻塞 | "
            f"{counts.get('buy', 0)} / {counts.get('add', 0)} / {counts.get('reduce', 0)} / "
            f"{counts.get('close', 0)} / {counts.get('hold_watch', 0)} / {counts.get('blocked', 0)} |"
        ),
        "",
        "**当前持仓需要做什么**",
    ]

    if current_holding_actions:
        for item in current_holding_actions[:6]:
            lines.append(f"- {_format_action_item(item)}。")
    else:
        lines.append("- 当前持仓暂无必须调仓动作；继续按昨收计划观察。")
    if uncovered_holdings:
        lines.append(f"- 另有 {len(uncovered_holdings)} 只当前持仓未覆盖今日分析，执行前先补齐或人工确认。")

    lines.extend(["", "**观察名单触发条件**"])
    if watch_items:
        names = "、".join(str(item.get("name")) for item in watch_items[:6])
        suffix = " 等" if len(watch_items) > 6 else ""
        lines.append(f"- 今日观察 {len(watch_items)} 只：{names}{suffix}。")
        lines.append(f"- {summary.get('watch_trigger_rule', WATCH_TRIGGER_RULE)}")
    else:
        lines.append(f"- 今日无持有观察项；{summary.get('watch_trigger_rule', WATCH_TRIGGER_RULE)}")

    lines.extend(["", "**BLOCK / 数据质量风险**"])
    if blocked_items or flags:
        if blocked_items:
            lines.append(f"- 存在 BLOCK：{len(blocked_items)} 只，已从可执行动作中排除。")
        for flag in flags[:4]:
            lines.append(f"- {flag.get('message', '')}")
    else:
        lines.append("- 未发现 BLOCK 或数据质量风险。")

    lines.extend(["", "**开盘后执行前检查**"])
    for item in summary.get("execution_checklist", EXECUTION_CHECKLIST):
        lines.append(f"- {item}")
    lines.extend(["", "---", ""])
    return lines
