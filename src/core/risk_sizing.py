# -*- coding: utf-8 -*-
"""Display-only risk sizing preview helpers.

P1-3a is shadow mode only: these helpers calculate a reference risk-budget
upper bound for human review, and never write back into deterministic actions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class RiskSizingSettings:
    max_single_position_weight: float = 0.35
    max_trade_risk_pct: float = 0.005
    atr_stop_multiplier: float = 1.5
    min_order_notional: float = 20.0
    max_daily_turnover_pct: float = 0.20
    mode: str = "shadow"


DEFAULT_RISK_SIZING_SETTINGS = RiskSizingSettings()


def risk_sizing_settings_from_config(config: Any) -> RiskSizingSettings:
    return RiskSizingSettings(
        max_single_position_weight=_safe_positive_float(
            getattr(config, "max_single_position_weight", DEFAULT_RISK_SIZING_SETTINGS.max_single_position_weight),
            DEFAULT_RISK_SIZING_SETTINGS.max_single_position_weight,
        ),
        max_trade_risk_pct=_safe_positive_float(
            getattr(config, "max_trade_risk_pct", DEFAULT_RISK_SIZING_SETTINGS.max_trade_risk_pct),
            DEFAULT_RISK_SIZING_SETTINGS.max_trade_risk_pct,
        ),
        atr_stop_multiplier=_safe_positive_float(
            getattr(config, "atr_stop_multiplier", DEFAULT_RISK_SIZING_SETTINGS.atr_stop_multiplier),
            DEFAULT_RISK_SIZING_SETTINGS.atr_stop_multiplier,
        ),
        min_order_notional=_safe_positive_float(
            getattr(config, "min_order_notional", DEFAULT_RISK_SIZING_SETTINGS.min_order_notional),
            DEFAULT_RISK_SIZING_SETTINGS.min_order_notional,
        ),
        max_daily_turnover_pct=_safe_positive_float(
            getattr(config, "max_daily_turnover_pct", DEFAULT_RISK_SIZING_SETTINGS.max_daily_turnover_pct),
            DEFAULT_RISK_SIZING_SETTINGS.max_daily_turnover_pct,
        ),
        mode=str(getattr(config, "risk_sizing_mode", DEFAULT_RISK_SIZING_SETTINGS.mode) or "shadow").strip().lower(),
    )


def build_risk_sizing_preview(
    *,
    result: Any,
    action_model: Dict[str, Any],
    overview: Dict[str, Any],
    settings: Optional[RiskSizingSettings] = None,
    is_blocked: bool,
    is_actionable_context: bool,
) -> Dict[str, Any]:
    settings = settings or DEFAULT_RISK_SIZING_SETTINGS
    mode = str(settings.mode or "shadow").strip().lower() or "shadow"
    current_weight = _safe_float(getattr(result, "current_weight", 0.0), 0.0)
    current_target_weight = _safe_float(action_model.get("target_weight"), current_weight)
    current_delta_amount = _safe_float(action_model.get("delta_amount"), 0.0)
    total_value = _safe_positive_float((overview or {}).get("total_value"), 0.0)
    risk_budget_amount = round(total_value * max(settings.max_trade_risk_pct, 0.0), 2) if total_value > 0 else None

    base = {
        "code": str(getattr(result, "code", "") or ""),
        "mode": mode,
        "raw_risk_target_weight": None,
        "capped_risk_target_weight": None,
        "current_target_weight": round(current_target_weight, 4),
        "current_delta_amount": round(current_delta_amount, 2),
        "risk_budget_amount": risk_budget_amount,
        "stop_distance": None,
        "stop_distance_source": "unavailable",
        "constraints_applied": [],
        "sizing_reason": "",
        "is_actionable_context": bool(is_actionable_context) and not is_blocked,
        "warning_flags": ["shadow_no_action_change"],
    }

    if mode != "shadow":
        base["warning_flags"].append("non_shadow_config_ignored")

    if is_blocked:
        base["current_target_weight"] = round(current_weight, 4)
        base["current_delta_amount"] = 0.0
        base["warning_flags"].append("validation_block")
        base["sizing_reason"] = "validation BLOCK，仅观察；风险仓位参考不可用。"
        return base

    action = str(action_model.get("position_action") or "HOLD").strip().upper()
    if not is_actionable_context or action not in {"OPEN", "ADD"}:
        base["warning_flags"].append("non_actionable_context")
        base["sizing_reason"] = "非可执行买入/加仓上下文；风险仓位参考不可用。"
        return base

    close_price = _extract_close_price(result)
    stop_distance, stop_source, stop_warnings = _resolve_stop_distance(
        result,
        close_price=close_price,
        atr_stop_multiplier=settings.atr_stop_multiplier,
    )
    base["warning_flags"].extend(stop_warnings)
    base["stop_distance"] = round(stop_distance, 4) if stop_distance is not None else None
    base["stop_distance_source"] = stop_source

    if close_price is None:
        base["warning_flags"].append("missing_close_price")
    if total_value <= 0:
        base["warning_flags"].append("missing_portfolio_total_value")

    if close_price is None or stop_distance is None or total_value <= 0:
        if "missing_stop_distance" not in base["warning_flags"] and stop_distance is None:
            base["warning_flags"].append("missing_stop_distance")
        base["sizing_reason"] = "缺少昨收价、止损距离或组合总值；风险仓位参考不可用。"
        return base

    raw_weight = max(settings.max_trade_risk_pct, 0.0) * close_price / stop_distance
    capped_weight = raw_weight
    constraints = ["stop_distance"]

    max_single = max(settings.max_single_position_weight, 0.0)
    if max_single > 0 and capped_weight > max_single:
        capped_weight = max_single
        constraints.append("max_single_position_weight")

    daily_turnover = max(settings.max_daily_turnover_pct, 0.0)
    if daily_turnover > 0:
        turnover_cap = current_weight + daily_turnover
        if capped_weight > turnover_cap:
            capped_weight = turnover_cap
            constraints.append("max_daily_turnover_pct")

    cash = _safe_positive_float((overview or {}).get("cash"), 0.0)
    if total_value > 0 and cash > 0:
        cash_cap = current_weight + cash / total_value
        if capped_weight > cash_cap:
            capped_weight = cash_cap
            constraints.append("cash")

    reference_delta_notional = max(capped_weight - current_weight, 0.0) * total_value
    if 0 < reference_delta_notional < max(settings.min_order_notional, 0.0):
        constraints.append("min_order_notional")
        base["warning_flags"].append("below_min_order_notional")

    base["raw_risk_target_weight"] = round(raw_weight, 4)
    base["capped_risk_target_weight"] = round(max(capped_weight, 0.0), 4)
    base["constraints_applied"] = constraints
    base["sizing_reason"] = "风险预算参考上限，仅供人工复核，不改变今日 deterministic action。"
    return base


def build_risk_sizing_previews(
    *,
    results: Iterable[Any],
    overview: Dict[str, Any],
    get_primary_action_model: Callable[[Any], Dict[str, Any]],
    is_blocked: Callable[[Any], bool],
    is_actionable_context: Callable[[Any, Dict[str, Any]], bool],
    settings: Optional[RiskSizingSettings] = None,
) -> List[Dict[str, Any]]:
    previews = []
    for result in results:
        model = get_primary_action_model(result)
        blocked = is_blocked(result)
        previews.append(
            build_risk_sizing_preview(
                result=result,
                action_model=model,
                overview=overview,
                settings=settings,
                is_blocked=blocked,
                is_actionable_context=(False if blocked else is_actionable_context(result, model)),
            )
        )
    return previews


def render_risk_sizing_preview_lines(previews: List[Dict[str, Any]]) -> List[str]:
    if not previews:
        return []

    lines = ["**风险仓位参考（Shadow，不改变今日动作）**"]
    for preview in previews[:6]:
        code = str(preview.get("code") or "unknown")
        flags = set(preview.get("warning_flags") or [])
        if "validation_block" in flags:
            lines.append(f"- {code}：风险仓位参考：不可用，原因：validation BLOCK，仅观察。")
            continue
        capped = preview.get("capped_risk_target_weight")
        raw = preview.get("raw_risk_target_weight")
        if capped is None or raw is None:
            reason = preview.get("sizing_reason") or "输入不足；风险仓位参考不可用。"
            lines.append(f"- {code}：风险仓位参考不可用（{reason}）仅供人工复核，不改变今日 deterministic action。")
            continue
        constraints = " / ".join(str(item) for item in (preview.get("constraints_applied") or [])) or "无额外约束"
        lines.append(
            f"- {code}：当前系统目标仓位 {float(preview.get('current_target_weight') or 0.0):.2%}；"
            f"风险预算参考上限 {float(capped):.2%}；约束：{constraints}；"
            "仅供人工复核，不改变今日 deterministic action。"
        )
    if len(previews) > 6:
        lines.append(f"- 其余 {len(previews) - 6} 只标的保留在 summary artifact 的 risk_sizing_previews 中。")
    lines.append("")
    return lines


def _resolve_stop_distance(
    result: Any,
    *,
    close_price: Optional[float],
    atr_stop_multiplier: float,
) -> Tuple[Optional[float], str, List[str]]:
    warnings: List[str] = []
    stop_loss = _safe_positive_float(getattr(result, "stop_loss", None), 0.0)
    if close_price is not None and stop_loss > 0:
        distance = close_price - stop_loss
        if distance > 0:
            return distance, "stop_loss", warnings
        warnings.append("invalid_stop_distance")

    atr = _extract_atr(result)
    if atr is not None and atr_stop_multiplier > 0:
        return atr * atr_stop_multiplier, "atr", warnings

    warnings.append("missing_stop_distance")
    return None, "unavailable", warnings


def _extract_close_price(result: Any) -> Optional[float]:
    snapshot = getattr(result, "market_snapshot", None) or {}
    if isinstance(snapshot, dict):
        close_price = _safe_positive_float(snapshot.get("close"), 0.0)
        if close_price > 0:
            return close_price
    current_price = _safe_positive_float(getattr(result, "current_price", None), 0.0)
    return current_price if current_price > 0 else None


def _extract_atr(result: Any) -> Optional[float]:
    candidates = [
        getattr(result, "atr", None),
        getattr(result, "atr14", None),
    ]
    snapshot = getattr(result, "market_snapshot", None) or {}
    if isinstance(snapshot, dict):
        candidates.extend([snapshot.get("atr"), snapshot.get("atr14")])
    indicators = getattr(result, "technical_indicators", None) or {}
    if isinstance(indicators, dict):
        candidates.extend([indicators.get("atr"), indicators.get("atr14")])
    for value in candidates:
        parsed = _safe_positive_float(value, 0.0)
        if parsed > 0:
            return parsed
    return None


def _safe_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return default
    return parsed


def _safe_positive_float(value: Any, default: float) -> float:
    parsed = _safe_float(value, default)
    return parsed if parsed > 0 else default
