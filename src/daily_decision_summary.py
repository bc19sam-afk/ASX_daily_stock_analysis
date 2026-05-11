# -*- coding: utf-8 -*-
"""Stable pre-open daily decision summary builders.

This module is intentionally deterministic: it summarizes already-computed
position actions, portfolio view, and validation outcomes. It does not ask AI
to reinterpret or change any action.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from src.core.validator import normalize_validation_status
from src.backtest_confidence import (
    build_backtest_confidence_panel,
    build_score_bucket_calibration,
    render_backtest_confidence_lines,
    render_score_bucket_calibration_lines,
    with_current_score_bucket_items,
)
from src.evidence_matrix import (
    build_evidence_matrix,
    render_evidence_matrix_lines,
    render_evidence_summary_lines,
    summarize_evidence_matrix,
)
from src.data_quality_snapshot import (
    build_data_quality_snapshot,
    render_data_quality_snapshot_lines,
)
from src.final_action_display import (
    EXECUTABLE_ACTIONS,
    build_final_action_display,
    is_effective_executable_action,
)
from src.report_reliability import (
    LEVEL_LABELS,
    build_report_reliability,
    normalize_reliability_reason,
    render_report_reliability_lines,
)
from src.core.risk_sizing import (
    RiskSizingSettings,
    build_risk_sizing_comparisons,
    build_risk_sizing_previews,
    render_risk_sizing_comparison_lines,
    render_risk_sizing_preview_lines,
)


ACTION_COUNT_KEYS = ("buy", "add", "reduce", "close", "hold_watch", "blocked")
DEFAULT_ACTIONABLE_DELTA_AMOUNT = 20.0
HOMEPAGE_ACTIONABLE_LIMIT = 5
HOMEPAGE_RISK_LIMIT = 5
TRIAGE_CARD_PREVIEW_LIMIT = 2
RISK_SIZING_REVIEW_DIFF_WEIGHT = 0.02
AI_CAUTION_TERMS = ("观望", "持有", "震荡", "等待", "条件化观察")
TECHNICAL_WEAK_TERMS = (
    "趋势弱",
    "趋势转弱",
    "趋势偏弱",
    "弱势",
    "均线缠绕",
    "均线粘合",
    "均线纠缠",
    "非多头",
    "量能弱",
    "成交量萎缩",
    "多头排列: 否",
    "多头排列：否",
)
EVIDENCE_GAP_STATUSES = {"missing", "stale", "not_checked", "unavailable"}
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
    format_validation_issue_text: Callable[[Any], str],
    min_delta_amount: float,
) -> Dict[str, Any]:
    item = {
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
    item["final_action_display"] = build_final_action_display(
        result,
        action_model=action_model,
        min_delta_amount=min_delta_amount,
        format_stock_display_name=format_stock_display_name,
        format_validation_issue_text=format_validation_issue_text,
    )
    return item


def _attach_action_review_reasons(
    *,
    actionable_items: List[Dict[str, Any]],
    result_by_code: Dict[str, Any],
    evidence_matrix: Dict[str, List[Dict[str, Any]]],
    risk_sizing_comparison: Dict[str, Dict[str, Any]],
) -> None:
    """Attach display-only review prompts without changing canonical actions."""
    for item in actionable_items:
        display = item.get("final_action_display")
        if not isinstance(display, dict):
            continue
        code = _normalize_stock_code(item.get("code"))
        result = result_by_code.get(code)
        reasons, confirmation_gap = _build_review_reasons(
            item=item,
            result=result,
            evidence_entries=evidence_matrix.get(code, []),
            risk_sizing_comparison=risk_sizing_comparison.get(code) if isinstance(risk_sizing_comparison, dict) else None,
        )
        display["review_reasons"] = reasons
        display["confirmation_gap"] = confirmation_gap
        display["review_label"] = "需二次确认" if confirmation_gap else ("执行前复核" if reasons else "无明显复核缺口")
        display["display_only"] = True


def _build_review_reasons(
    *,
    item: Dict[str, Any],
    result: Any,
    evidence_entries: List[Dict[str, Any]],
    risk_sizing_comparison: Optional[Dict[str, Any]],
) -> Tuple[List[str], bool]:
    """Build human-facing review reasons from existing artifacts only."""
    if str(item.get("position_action") or "").upper() not in {"OPEN", "ADD"}:
        return [], False
    if normalize_validation_status(getattr(result, "validation_status", None)) == "BLOCK":
        return [], False

    reasons: List[str] = []
    confirmation_gap = False

    if _ai_commentary_is_cautious(result):
        _append_unique(reasons, "AI 补充偏观望，需二次确认")
        confirmation_gap = True

    if _technical_context_is_weak(result):
        _append_unique(reasons, "技术确认偏弱，需条件复核")
        confirmation_gap = True

    if _risk_sizing_differs_significantly(risk_sizing_comparison):
        _append_unique(reasons, "风险仓位试算与目标仓位差异较大")
        confirmation_gap = True

    evidence_confirmation_gap = _append_evidence_review_reasons(reasons, evidence_entries)
    confirmation_gap = confirmation_gap or evidence_confirmation_gap
    return reasons, confirmation_gap


def _ai_commentary_is_cautious(result: Any) -> bool:
    text = _normalize_review_text(getattr(result, "operation_advice", "") if result is not None else "")
    return bool(text and any(term in text for term in AI_CAUTION_TERMS))


def _technical_context_is_weak(result: Any) -> bool:
    if result is None:
        return False
    technical_text = _normalize_review_text(
        " ".join(
            str(value or "")
            for value in (
                getattr(result, "trend_prediction", ""),
                getattr(result, "technical_analysis", ""),
            )
        )
    )
    if not technical_text:
        return False
    if any(term in technical_text for term in TECHNICAL_WEAK_TERMS):
        return True
    if "震荡" in technical_text and "上行" not in technical_text and "偏强" not in technical_text:
        return True
    return False


def _risk_sizing_differs_significantly(comparison: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(comparison, dict) or comparison.get("would_change_target") is not True:
        return False
    difference = comparison.get("difference_weight")
    if difference is None:
        return True
    return abs(_safe_float(difference)) >= RISK_SIZING_REVIEW_DIFF_WEIGHT


def _append_evidence_review_reasons(reasons: List[str], entries: List[Dict[str, Any]]) -> bool:
    confirmation_gap = False
    for entry in entries or []:
        category = str(entry.get("category") or "")
        status = str(entry.get("status") or "")
        if category == "announcement" and status == "not_checked":
            _append_unique(reasons, "公告未检查，执行前复核")
            continue
        if category == "backtest" and status == "not_checked":
            _append_unique(reasons, "回测证据未检查")
            confirmation_gap = True
            continue
        if category == "valuation" and status in EVIDENCE_GAP_STATUSES:
            _append_unique(reasons, "估值覆盖缺口")
            confirmation_gap = True
    return confirmation_gap


def _append_unique(items: List[str], value: str) -> None:
    if value and value not in items:
        items.append(value)


def _normalize_review_text(value: Any) -> str:
    return str(value or "").replace("\r\n", " ").replace("\n", " ").strip()


def _build_triage_card(
    *,
    actionable_items: List[Dict[str, Any]],
    watch_items: List[Dict[str, Any]],
    blocked_items: List[Dict[str, Any]],
    uncovered_holdings: List[Dict[str, Any]],
    failed_results: List[Any],
    data_quality_flags: List[Dict[str, Any]],
    evidence_matrix: Dict[str, List[Dict[str, Any]]],
    report_reliability: Dict[str, Any],
    score_bucket_calibration: Dict[str, Any],
    risk_sizing_comparison: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Build a display-only daily review triage card from existing artifacts."""
    card = {
        "today_must_review": [],
        "today_can_ignore": [],
        "high_value_low_confidence": [],
        "data_quality_attention": [],
    }

    for item in actionable_items:
        card["today_must_review"].append(
            _triage_item(
                item,
                section="today_must_review",
                reason=_must_review_reason(item),
                evidence_basis=_triage_evidence_basis(
                    item,
                    report_reliability=report_reliability,
                    source="actionable_items",
                ),
                confidence_note="已有明确动作，但仍要在开盘前确认价格、公告和新闻。",
                source_fields=["actionable_items", "final_action_display", "report_reliability"],
            )
        )
        low_confidence_reasons = _item_low_confidence_reasons(
            item,
            evidence_matrix=evidence_matrix,
            score_bucket_calibration=score_bucket_calibration,
            risk_sizing_comparison=risk_sizing_comparison,
        )
        if low_confidence_reasons:
            card["high_value_low_confidence"].append(
                _triage_item(
                    item,
                    section="high_value_low_confidence",
                    reason="数据或历史样本需要人工确认：" + "；".join(low_confidence_reasons[:3]),
                    evidence_basis=_triage_evidence_basis(
                        item,
                        report_reliability=report_reliability,
                        source="evidence_matrix",
                    ),
                    confidence_note="; ".join(low_confidence_reasons),
                    source_fields=[
                        "actionable_items",
                        "evidence_matrix",
                        "score_bucket_calibration",
                        "risk_sizing_comparison",
                    ],
                )
            )

    attention_codes = set()
    for item in blocked_items:
        code = _normalize_stock_code(item.get("code"))
        attention_codes.add(code)
        blocked_item = dict(item)
        blocked_item["position_action"] = "BLOCK"
        card["data_quality_attention"].append(
            _triage_item(
                blocked_item,
                section="data_quality_attention",
                reason=str(item.get("reason") or "触发 BLOCK，只能观察，不能当作可执行动作。"),
                evidence_basis="validation_status=BLOCK",
                confidence_note="BLOCK 仍是硬阻断。",
                source_fields=["blocked_items", "final_action_display", "data_quality_flags"],
            )
        )

    for holding in uncovered_holdings:
        code = _normalize_stock_code(holding.get("code"))
        attention_codes.add(code)
        card["data_quality_attention"].append(
            {
                "code": str(holding.get("code") or ""),
                "name": str(holding.get("name") or holding.get("code") or ""),
                "section": "data_quality_attention",
                "reason": "当前持仓今天没有生成个股分析；执行前先补看。",
                "evidence_basis": "uncovered_holdings",
                "confidence_note": "需要人工判断这只持仓是否要单独检查。",
                "source_fields": ["uncovered_holdings"],
                "position_action": "HOLD",
                "price_basis": "unknown",
                "is_current_holding": True,
            }
        )

    for result in failed_results:
        code = _normalize_stock_code(getattr(result, "code", ""))
        attention_codes.add(code)
        name = str(getattr(result, "name", None) or code)
        error = str(getattr(result, "error_message", "") or "analysis failed").strip()
        card["data_quality_attention"].append(
            {
                "code": code,
                "name": f"{name} ({code})" if code and code not in name else name,
                "section": "data_quality_attention",
                "reason": f"分析没有成功：{error}；不要从这只股票推断动作。",
                "evidence_basis": "failed_results",
                "confidence_note": "失败分析不能生成动作。",
                "source_fields": ["failed_results"],
                "position_action": "FAILED",
                "price_basis": "unknown",
                "is_current_holding": False,
            }
        )

    for flag in data_quality_flags:
        code = str(flag.get("code") or "")
        if code in {"validation_block", "uncovered_holding", "analysis_failed"}:
            continue
        message = str(flag.get("message") or "").strip()
        if not message:
            continue
        card["data_quality_attention"].append(
            {
                "code": "REPORT",
                "name": "Report-level data quality",
                "section": "data_quality_attention",
                "reason": message,
                "evidence_basis": code or "data_quality_flags",
                "confidence_note": str(flag.get("severity") or "warning"),
                "source_fields": ["data_quality_flags"],
                "position_action": "REVIEW",
                "price_basis": "mixed" if "price" in code else "unknown",
                "is_current_holding": False,
            }
        )

    for item in watch_items:
        low_confidence_reasons = _item_low_confidence_reasons(
            item,
            evidence_matrix=evidence_matrix,
            score_bucket_calibration=score_bucket_calibration,
            risk_sizing_comparison=risk_sizing_comparison,
        )
        if item.get("is_current_holding") and low_confidence_reasons and _normalize_stock_code(item.get("code")) not in attention_codes:
            card["data_quality_attention"].append(
                _triage_item(
                    item,
                    section="data_quality_attention",
                    reason="当前持仓虽无动作，但数据或历史样本需要人工确认：" + "；".join(low_confidence_reasons[:2]),
                    evidence_basis="evidence_matrix",
                    confidence_note="；".join(low_confidence_reasons),
                    source_fields=["watch_items", "evidence_matrix", "score_bucket_calibration"],
                )
            )
            attention_codes.add(_normalize_stock_code(item.get("code")))
            continue
        card["today_can_ignore"].append(
            _triage_item(
                item,
                section="today_can_ignore",
                reason="今天没有明确动作；除非新闻、公告或价格触发条件变化，否则低优先级。",
                evidence_basis="watch_items",
                confidence_note=str(item.get("trigger") or WATCH_TRIGGER_RULE),
                source_fields=["watch_items", "watch_trigger_rule"],
            )
        )

    card["counts"] = {
        key: len(value)
        for key, value in card.items()
        if isinstance(value, list)
    }
    return card


def _triage_item(
    item: Dict[str, Any],
    *,
    section: str,
    reason: str,
    evidence_basis: str,
    confidence_note: str,
    source_fields: List[str],
) -> Dict[str, Any]:
    return {
        "code": str(item.get("code") or ""),
        "name": str(item.get("name") or item.get("code") or ""),
        "section": section,
        "reason": reason,
        "evidence_basis": evidence_basis,
        "confidence_note": confidence_note,
        "source_fields": list(source_fields),
        "position_action": str(item.get("position_action") or "HOLD"),
        "price_basis": str(item.get("price_basis") or "unknown"),
        "is_current_holding": bool(item.get("is_current_holding")),
    }


def _must_review_reason(item: Dict[str, Any]) -> str:
    action = str(item.get("position_action") or "HOLD").upper()
    action_label = {
        "OPEN": "新开仓观察",
        "ADD": "加仓当前持仓" if item.get("is_current_holding") else "加仓观察",
        "REDUCE": "减仓当前持仓",
        "CLOSE": "清仓当前持仓",
    }.get(action, "人工复核")
    delta = _safe_float(item.get("delta_amount"))
    if delta > 0:
        amount_text = f"计划投入约 {abs(delta):,.2f}"
    elif delta < 0:
        amount_text = f"计划调出约 {abs(delta):,.2f}"
    else:
        amount_text = "暂无调仓金额"
    return f"{action_label}；{amount_text}。"


def _triage_evidence_basis(item: Dict[str, Any], *, report_reliability: Dict[str, Any], source: str) -> str:
    reliability = report_reliability or {}
    score = reliability.get("score")
    level = reliability.get("level") or "unknown"
    return f"{source}; price_basis={item.get('price_basis') or 'unknown'}; reliability={score}/{level}"


def _item_low_confidence_reasons(
    item: Dict[str, Any],
    *,
    evidence_matrix: Dict[str, List[Dict[str, Any]]],
    score_bucket_calibration: Dict[str, Any],
    risk_sizing_comparison: Dict[str, Dict[str, Any]],
) -> List[str]:
    code = _normalize_stock_code(item.get("code"))
    reasons: List[str] = []

    if str(item.get("price_basis") or "close_only") != "close_only":
        reasons.append("行情时间口径不是纯昨收")

    for entry in evidence_matrix.get(code, []):
        category = str(entry.get("category") or "")
        status = str(entry.get("status") or "")
        if category == "announcement" and status == "not_checked":
            continue
        if category in {"market_data", "valuation", "news", "backtest"} and status in {
            "missing",
            "stale",
            "not_checked",
            "unavailable",
        }:
            reasons.append(_human_data_gap_reason(category=category, status=status))

    bucket_reason = _score_bucket_low_sample_reason(code, score_bucket_calibration)
    if bucket_reason:
        reasons.append(bucket_reason)

    comparison = risk_sizing_comparison.get(code) if isinstance(risk_sizing_comparison, dict) else None
    if isinstance(comparison, dict) and comparison.get("would_change_target") is True:
        reasons.append("风险仓位试算和当前计划不一致")

    return reasons


def _score_bucket_low_sample_reason(code: str, calibration: Dict[str, Any]) -> str:
    if not isinstance(calibration, dict):
        return ""
    for current in calibration.get("current_items") or []:
        if _normalize_stock_code(current.get("code")) != code:
            continue
        bucket = str(current.get("bucket") or "")
        bucket_entry = calibration.get(bucket) if bucket else None
        if isinstance(bucket_entry, dict):
            sample_size = int(bucket_entry.get("sample_size") or 0)
            if sample_size < 20:
                return f"同类评分历史样本太少（{sample_size} 次）"
    return ""


def _human_data_gap_reason(*, category: str, status: str) -> str:
    category_label = {
        "market_data": "行情数据",
        "valuation": "估值数据",
        "news": "新闻证据",
        "backtest": "回测证据",
    }.get(str(category or ""), "数据")
    status_label = {
        "missing": "缺失",
        "stale": "过期",
        "not_checked": "不足",
        "unavailable": "暂不可用",
    }.get(str(status or ""), "需要确认")
    return f"{category_label}{status_label}"


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
    backtest_confidence: Optional[Dict[str, Any]] = None,
    score_bucket_calibration: Optional[Dict[str, Any]] = None,
    risk_sizing_settings: Optional[RiskSizingSettings] = None,
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
            format_validation_issue_text=format_validation_issue_text,
            min_delta_amount=min_action_delta_amount,
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
        display = build_final_action_display(
            result,
            action_model=model,
            min_delta_amount=min_action_delta_amount,
            format_stock_display_name=format_stock_display_name,
            format_validation_issue_text=format_validation_issue_text,
        )
        blocked_items.append(
            {
                "code": str(getattr(result, "code", "") or ""),
                "name": _display_name(result, format_stock_display_name),
                "reason": format_validation_issue_text(result),
                "current_weight": current_weight,
                "target_weight": _safe_float(model.get("target_weight"), current_weight),
                "price_basis": classify_price_basis(result),
                "final_action_display": display,
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
                "message": f"{_price_policy_label(price_policy)}，不是纯昨收计划。",
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
    report_reliability = build_report_reliability(
        price_policy=price_policy,
        price_basis_counts=counts,
        evidence_matrix=evidence_matrix,
        evidence_summary=evidence_summary,
        data_quality_flags=data_quality_flags,
    )
    data_quality_snapshot = build_data_quality_snapshot(
        successful_results=successful_results,
        failed_results=failed_results,
        evidence_matrix=evidence_matrix,
        evidence_summary=evidence_summary,
        report_reliability=report_reliability,
        data_quality_flags=data_quality_flags,
        price_basis_counts=counts,
        technical_basis_dates=technical_dates,
        uncovered_holdings=uncovered_holdings,
    )
    if backtest_confidence is None:
        backtest_confidence = build_backtest_confidence_panel(
            summary=None,
            action_results=[],
            window_days=None,
        )
    if score_bucket_calibration is None:
        score_bucket_calibration = build_score_bucket_calibration(
            score_results=[],
            window_days=None,
            current_results=decision_results,
            format_stock_display_name=format_stock_display_name,
        )
    else:
        score_bucket_calibration = with_current_score_bucket_items(
            score_bucket_calibration,
            current_results=decision_results,
            format_stock_display_name=format_stock_display_name,
        )
    risk_sizing_previews = build_risk_sizing_previews(
        results=successful_results,
        overview=overview,
        get_primary_action_model=get_primary_action_model,
        is_blocked=_is_blocked,
        is_actionable_context=lambda result, model: is_effective_executable_action(
            model,
            min_delta_amount=min_action_delta_amount,
        ),
        settings=risk_sizing_settings,
    )
    risk_sizing_comparison = build_risk_sizing_comparisons(
        results=successful_results,
        overview=overview,
        get_primary_action_model=get_primary_action_model,
        is_blocked=_is_blocked,
        is_actionable_context=lambda result, model: is_effective_executable_action(
            model,
            min_delta_amount=min_action_delta_amount,
        ),
        settings=risk_sizing_settings,
    )
    result_by_code = {
        _normalize_stock_code(getattr(result, "code", "")): result
        for result in decision_results
        if _normalize_stock_code(getattr(result, "code", ""))
    }
    _attach_action_review_reasons(
        actionable_items=actionable_items,
        result_by_code=result_by_code,
        evidence_matrix=evidence_matrix,
        risk_sizing_comparison=risk_sizing_comparison,
    )
    triage_card = _build_triage_card(
        actionable_items=actionable_items,
        watch_items=watch_items,
        blocked_items=blocked_items,
        uncovered_holdings=uncovered_holdings,
        failed_results=failed_results,
        data_quality_flags=data_quality_flags,
        evidence_matrix=evidence_matrix,
        report_reliability=report_reliability,
        score_bucket_calibration=score_bucket_calibration,
        risk_sizing_comparison=risk_sizing_comparison,
    )

    return {
        "schema_version": "daily_decision_summary.v1.8",
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
        "report_reliability": report_reliability,
        "data_quality_snapshot": data_quality_snapshot,
        "backtest_confidence": backtest_confidence,
        "score_bucket_calibration": score_bucket_calibration,
        "risk_sizing_previews": risk_sizing_previews,
        "risk_sizing_comparison": risk_sizing_comparison,
        "triage_card": triage_card,
        "execution_checklist": list(EXECUTION_CHECKLIST),
        "watch_trigger_rule": WATCH_TRIGGER_RULE,
    }


def _format_action_item(item: Dict[str, Any]) -> str:
    fields = _action_display_fields(item)
    return (
        f"{fields['name']}：{fields['action_label']}，"
        f"目标仓位 {fields['target_weight']}，{fields['amount_text']}"
    )


def _action_display_fields(item: Dict[str, Any]) -> Dict[str, str]:
    action = str(item.get("position_action") or "HOLD").upper()
    action_label = {
        "OPEN": "买入/新开仓",
        "ADD": "加仓",
        "REDUCE": "减仓",
        "CLOSE": "清仓",
    }.get(action, "持有观察")
    target_weight = _safe_float(item.get("target_weight"))
    delta_amount = _safe_float(item.get("delta_amount"))
    if delta_amount > 0:
        amount_text = f"计划投入约 {abs(delta_amount):,.2f}"
    elif delta_amount < 0:
        amount_text = f"计划调出约 {abs(delta_amount):,.2f}"
    else:
        amount_text = "暂无调仓金额"
    return {
        "name": str(item.get("name") or item.get("code") or "未知标的"),
        "action_label": action_label,
        "target_weight": f"{target_weight:.2%}",
        "amount_text": amount_text,
        "review_text": _action_review_text(item),
    }


def _action_review_text(item: Dict[str, Any]) -> str:
    display = item.get("final_action_display")
    if not isinstance(display, dict):
        return ""
    reasons = [str(reason).strip() for reason in (display.get("review_reasons") or []) if str(reason).strip()]
    if reasons:
        label = str(display.get("review_label") or "执行前复核").strip()
        return f"{label}：{'；'.join(reasons[:2])}"
    return str(display.get("review_label") or "").strip()


def _render_action_table_lines(items: List[Dict[str, Any]]) -> List[str]:
    if not items:
        return []
    lines = [
        "| 标的 | 今天怎么处理 | 目标仓位 | 计划金额 | 复核提示 |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for item in items[:HOMEPAGE_ACTIONABLE_LIMIT]:
        fields = _action_display_fields(item)
        lines.append(
            "| "
            f"{_table_cell(fields['name'])} | "
            f"{_table_cell(fields['action_label'])} | "
            f"{_table_cell(fields['target_weight'])} | "
            f"{_table_cell(fields['amount_text'])} | "
            f"{_table_cell(fields['review_text'])} |"
        )
    return lines


def _table_cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()


def _today_conclusion(
    *,
    actionable_items: List[Dict[str, Any]],
    current_holding_actions: List[Dict[str, Any]],
    blocked_items: List[Dict[str, Any]],
) -> str:
    if current_holding_actions:
        return f"优先处理 {len(current_holding_actions)} 只当前持仓；其余按昨收计划准备。"
    if actionable_items:
        return f"今日有 {len(actionable_items)} 个明确计划动作，开盘后确认价格再决定是否执行。"
    if blocked_items:
        return f"今日无可执行动作；{len(blocked_items)} 只标的被阻断（BLOCK），先观察。"
    return "今日没有明确计划动作，以观察为主。"


def _format_action_counts_inline(counts: Dict[str, Any]) -> str:
    return (
        f"买入 {int(counts.get('buy', 0) or 0)} / "
        f"加仓 {int(counts.get('add', 0) or 0)} / "
        f"减仓 {int(counts.get('reduce', 0) or 0)} / "
        f"清仓 {int(counts.get('close', 0) or 0)} / "
        f"观察 {int(counts.get('hold_watch', 0) or 0)} / "
        f"阻断（BLOCK）{int(counts.get('blocked', 0) or 0)}"
    )


def _report_reliability_sentence(reliability: Dict[str, Any]) -> str:
    if not reliability:
        return "未生成可信度摘要。"
    level = str(reliability.get("level") or "low_observe_only")
    label = LEVEL_LABELS.get(level, LEVEL_LABELS["low_observe_only"])
    reasons = [
        normalize_reliability_reason(flag.get("message"))
        for flag in (reliability.get("flags") or [])
        if str(flag.get("code") or "") != "low_reliability" and normalize_reliability_reason(flag.get("message"))
    ]
    reason = f"{'；'.join(reasons[:3])}。" if reasons else "无重大扣分项。"
    return f"{int(reliability.get('score') or 0)}/100，{label}；{reason}"


def _top_risk_lines(
    *,
    blocked_items: List[Dict[str, Any]],
    flags: List[Dict[str, Any]],
    report_reliability: Dict[str, Any],
    risk_sizing_comparison: Dict[str, Dict[str, Any]],
    evidence_summary: Dict[str, Any],
) -> List[str]:
    risk_lines: List[str] = []
    if blocked_items:
        risk_lines.append(f"{len(blocked_items)} 只股票被阻断（BLOCK），已从可执行动作中排除。")
        for item in blocked_items[:2]:
            reason = str(item.get("reason") or "").strip()
            if reason:
                risk_lines.append(f"{item.get('name')}：{reason}")

    seen = {line for line in risk_lines}
    significant_risk_diff_count = _significant_risk_sizing_diff_count(risk_sizing_comparison)
    if significant_risk_diff_count > 0:
        line = f"{significant_risk_diff_count} 只股票风险仓位试算与目标仓位差异较大，执行前先复核仓位。"
        risk_lines.append(line)
        seen.add(line)

    if _has_evidence_coverage_gap(evidence_summary):
        line = (
            "存在公告 / 回测 / 估值覆盖缺口，BLOCK 标的解除前仍只观察。"
            if blocked_items
            else "无 validation BLOCK；但仍可能存在公告 / 回测 / 估值覆盖缺口。"
        )
        if line not in seen:
            risk_lines.append(line)
            seen.add(line)

    reliability_flags = [
        flag
        for flag in (report_reliability.get("flags") or [])
        if str(flag.get("severity") or "").lower() in {"warning", "block"}
    ]
    for flag in list(flags) + reliability_flags:
        if blocked_items and str(flag.get("code") or "") == "validation_block":
            continue
        message = str(flag.get("message") or "").strip()
        if message and message not in seen:
            risk_lines.append(message)
            seen.add(message)
        if len(risk_lines) >= HOMEPAGE_RISK_LIMIT:
            break

    return risk_lines[:HOMEPAGE_RISK_LIMIT]


def _significant_risk_sizing_diff_count(comparisons: Dict[str, Dict[str, Any]]) -> int:
    if not isinstance(comparisons, dict):
        return 0
    return sum(1 for comparison in comparisons.values() if _risk_sizing_differs_significantly(comparison))


def _has_evidence_coverage_gap(summary: Dict[str, Any]) -> bool:
    if not isinstance(summary, dict):
        return False
    return any(
        int(summary.get(key, 0) or 0) > 0
        for key in (
            "announcement_not_checked",
            "announcement_unavailable",
            "announcement_risk_found",
            "backtest_not_checked",
            "valuation_missing",
        )
    )


def _execution_checklist_inline(checklist: List[str]) -> str:
    if not checklist:
        return "开盘后确认价格；检查公告和新闻；数据不足则观察；仅作计划。"
    return "开盘后确认价格；检查公告和新闻；数据不足则观察；仅作计划。"


def _render_triage_card_lines(card: Dict[str, Any]) -> List[str]:
    if not card:
        return []
    sections = [
        ("today_must_review", "先看这几只"),
        ("today_can_ignore", "低优先级"),
        ("high_value_low_confidence", "有机会但证据不足"),
        ("data_quality_attention", "先补数据再判断"),
    ]
    lines = ["", "**今日人工复核卡片**"]
    for key, label in sections:
        items = card.get(key) or []
        if not items:
            lines.append(f"- **{label}**：无。")
            continue
        lines.append(f"- **{label}**：{_format_triage_preview(items)}")
    return lines


def _format_triage_preview(items: List[Dict[str, Any]]) -> str:
    preview = []
    for item in items[:TRIAGE_CARD_PREVIEW_LIMIT]:
        name = str(item.get("name") or item.get("code") or "未知标的")
        reason = _compact_reason(str(item.get("reason") or ""))
        preview.append(f"{name}（{reason}）" if reason else name)
    omitted = len(items) - len(preview)
    suffix = f"；另 {omitted} 项" if omitted > 0 else ""
    return "；".join(preview) + suffix + "。"


def _compact_reason(value: str) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= 54:
        return text
    return text[:51].rstrip() + "..."


def _homepage_banner(price_policy: str) -> str:
    normalized_policy = str(price_policy or "close_only")
    if normalized_policy == "close_only":
        return "> 昨收数据计划 / 开盘前参考。开盘后先确认价格。"
    return f"> {_price_policy_label(normalized_policy)}。开盘后必须先确认价格。"


def _price_policy_label(price_policy: Any) -> str:
    normalized_policy = str(price_policy or "close_only")
    return {
        "close_only": "全部使用昨收数据",
        "latest_close": "使用最新收盘数据",
        "realtime": "包含实时价格参考",
        "mixed": "价格来源混用",
    }.get(normalized_policy, f"价格来源需人工确认（{normalized_policy}）")


def _display_date_or_placeholder(value: Any) -> str:
    text = str(value or "").strip()
    if text.lower() in {"", "unknown", "none", "null", "n/a"}:
        return "暂无"
    return text


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
        _homepage_banner(str(summary.get("price_policy") or "close_only")),
        "",
        f"**今日结论**：{_today_conclusion(actionable_items=summary.get('actionable_items') or [], current_holding_actions=current_holding_actions, blocked_items=blocked_items)}",
        f"**今日动作数量**：{_format_action_counts_inline(counts)}",
    ]
    lines.extend(_render_triage_card_lines(summary.get("triage_card") or {}))
    lines.extend([
        "",
        "**当前持仓需要处理什么**",
    ])

    if current_holding_actions:
        lines.extend(_render_action_table_lines(current_holding_actions))
    else:
        lines.append("- 当前持仓暂无必须调仓动作；继续按昨收计划观察。")
    if uncovered_holdings:
        if current_holding_actions:
            lines.append("")
        lines.append(f"- 另有 {len(uncovered_holdings)} 只当前持仓未覆盖今日分析，执行前先补齐或人工确认。")

    lines.extend(["", "**今日重点股票**"])
    actionable_items = summary.get("actionable_items") or []
    if actionable_items:
        lines.extend(_render_action_table_lines(actionable_items))
    else:
        if watch_items:
            names = "、".join(str(item.get("name")) for item in watch_items[:HOMEPAGE_ACTIONABLE_LIMIT])
            suffix = " 等" if len(watch_items) > HOMEPAGE_ACTIONABLE_LIMIT else ""
            lines.append(f"- 今日没有明确计划动作；观察名单 {len(watch_items)} 只：{names}{suffix}。")
        else:
            lines.append("- 今日没有明确计划动作；数据不足则观察。")

    lines.extend(["", "**主要风险 / 暂停动作**"])
    risk_lines = _top_risk_lines(
        blocked_items=blocked_items,
        flags=flags,
        report_reliability=summary.get("report_reliability") or {},
        risk_sizing_comparison=summary.get("risk_sizing_comparison") or {},
        evidence_summary=summary.get("evidence_summary") or {},
    )
    if risk_lines:
        for risk_line in risk_lines:
            lines.append(f"- {risk_line}")
    else:
        lines.append("- 未发现阻断（BLOCK）或数据质量风险。")
    lines.extend([
        "",
        f"**报告可信度**：{_report_reliability_sentence(summary.get('report_reliability') or {})}",
        f"**价格来源**：{_price_policy_label(summary.get('price_policy', 'close_only'))}；技术基准日 {_display_date_or_placeholder(summary.get('technical_basis_date'))}",
        f"**执行前检查**：{_execution_checklist_inline(summary.get('execution_checklist', EXECUTION_CHECKLIST))}",
    ])
    lines.extend(render_data_quality_snapshot_lines(summary.get("data_quality_snapshot") or {}))
    lines.extend(["", "---", ""])
    return lines


def render_preopen_decision_appendix(summary: Dict[str, Any], *, include_heading: bool = True) -> List[str]:
    """Render audit/detail sections below the compact homepage."""
    if not summary:
        return []

    counts = summary.get("action_counts") or {}
    lines: List[str] = []
    if include_heading:
        lines.extend([
            "## 详情 / 审计附录",
            "",
        ])
    lines.extend(render_evidence_summary_lines(summary.get("evidence_summary") or {}))
    lines.extend(render_report_reliability_lines(summary.get("report_reliability") or {}))
    lines.extend(
        render_backtest_confidence_lines(
            summary.get("backtest_confidence") or {},
            action_counts=counts,
        )
    )
    lines.extend(render_score_bucket_calibration_lines(summary.get("score_bucket_calibration") or {}))
    lines.extend(render_risk_sizing_preview_lines(summary.get("risk_sizing_previews") or []))
    lines.extend(render_risk_sizing_comparison_lines(summary.get("risk_sizing_comparison") or {}))
    lines.extend(render_evidence_matrix_lines(summary.get("evidence_matrix") or {}))
    return lines
