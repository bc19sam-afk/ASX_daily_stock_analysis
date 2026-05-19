# -*- coding: utf-8 -*-
"""Final report-display action model for deterministic action outputs."""

from __future__ import annotations

from typing import Any, Callable, Dict

from src.core.utils import is_failed_analysis, safe_float
from src.core.validator import normalize_validation_status


EXECUTABLE_ACTIONS = {"OPEN", "ADD", "REDUCE", "CLOSE"}


def is_effective_executable_action(
    action_model: Dict[str, Any],
    *,
    min_delta_amount: float,
) -> bool:
    """Return True when an action is large enough to present as actionable."""
    action = str(action_model.get("position_action") or "HOLD").upper()
    if action not in EXECUTABLE_ACTIONS:
        return False
    threshold = max(safe_float(min_delta_amount), 0.0)
    if threshold <= 0:
        return True
    return abs(safe_float(action_model.get("delta_amount"))) >= threshold


def build_final_action_display(
    result: Any,
    *,
    action_model: Dict[str, Any],
    min_delta_amount: float,
    format_stock_display_name: Callable[[Any, Any], str],
    format_validation_issue_text: Callable[[Any], str],
) -> Dict[str, Any]:
    """Build a display-only action object without mutating the result."""
    code = str(getattr(result, "code", "") or "")
    name = format_stock_display_name(getattr(result, "name", ""), code)
    current_weight = safe_float(getattr(result, "current_weight", 0.0))
    validation_status = normalize_validation_status(getattr(result, "validation_status", None))

    if is_failed_analysis(result):
        return _display(
            code=code,
            name=name,
            validation_status=validation_status,
            actionability="failed",
            final_decision="HOLD",
            position_action="HOLD",
            target_weight=current_weight,
            current_weight=current_weight,
            delta_amount=0.0,
            reason=str(getattr(result, "error_message", "") or "分析失败，需重跑。"),
            display_label="分析失败 / 需重跑",
            can_show_sizing=False,
            can_show_plan_points=False,
        )

    if validation_status == "BLOCK":
        return _display(
            code=code,
            name=name,
            validation_status=validation_status,
            actionability="blocked",
            final_decision="HOLD",
            position_action="HOLD",
            target_weight=current_weight,
            current_weight=current_weight,
            delta_amount=0.0,
            reason=format_validation_issue_text(result) or "validation_status=BLOCK。",
            display_label="不可决策 / 仅观察",
            can_show_sizing=False,
            can_show_plan_points=False,
        )

    if not is_effective_executable_action(action_model, min_delta_amount=min_delta_amount):
        action = str(action_model.get("position_action") or "HOLD").upper()
        show_holding_sizing = action == "HOLD" and current_weight > 0
        return _display(
            code=code,
            name=name,
            validation_status=validation_status,
            actionability="watch_only",
            final_decision="HOLD",
            position_action="HOLD",
            target_weight=safe_float(action_model.get("target_weight"), current_weight),
            current_weight=current_weight,
            delta_amount=safe_float(action_model.get("delta_amount")) if show_holding_sizing else 0.0,
            reason=str(getattr(result, "action_reason", "") or "未达到可执行动作阈值，仅观察。"),
            display_label="持有 / 观察",
            can_show_sizing=show_holding_sizing,
            can_show_plan_points=True,
        )

    action = str(action_model.get("position_action") or "HOLD").upper()
    decision = str(action_model.get("decision") or getattr(result, "final_decision", "") or "HOLD").upper()
    return _display(
        code=code,
        name=name,
        validation_status=validation_status,
        actionability="actionable",
        final_decision=decision,
        position_action=action,
        target_weight=safe_float(action_model.get("target_weight")),
        current_weight=current_weight,
        delta_amount=safe_float(action_model.get("delta_amount")),
        reason=str(getattr(result, "action_reason", "") or ""),
        display_label=_action_label(action),
        can_show_sizing=True,
        can_show_plan_points=True,
    )


def _display(
    *,
    code: str,
    name: str,
    validation_status: str,
    actionability: str,
    final_decision: str,
    position_action: str,
    target_weight: float,
    current_weight: float,
    delta_amount: float,
    reason: str,
    display_label: str,
    can_show_sizing: bool,
    can_show_plan_points: bool,
) -> Dict[str, Any]:
    return {
        "code": code,
        "name": name,
        "validation_status": validation_status,
        "actionability": actionability,
        "final_decision": final_decision,
        "position_action": position_action,
        "target_weight": target_weight,
        "current_weight": current_weight,
        "delta_amount": delta_amount,
        "reason": reason,
        "display_label": display_label,
        "can_show_sizing": can_show_sizing,
        "can_show_plan_points": can_show_plan_points,
    }


def _action_label(action: str) -> str:
    return {
        "OPEN": "买入 / 新开仓",
        "ADD": "加仓",
        "REDUCE": "减仓",
        "CLOSE": "清仓",
    }.get(str(action or "").upper(), "持有 / 观察")
