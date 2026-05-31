# -*- coding: utf-8 -*-
"""Reusable ASX alert-rule preset definitions for dry-run review surfaces."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Mapping, Optional

from src.stock_code import canonical_stock_code


DRY_RUN_ENDPOINT = "/api/v1/alert-rules/dry-run"
PRESETS_ENDPOINT = "/api/v1/alert-rules/presets"
WORKBENCH_ENDPOINT = "/api/v1/workbench/summary"

PRESET_REQUIRED_FIELDS = sorted(
    [
        "alert_type",
        "default_parameters",
        "description",
        "id",
        "is_trade_instruction",
        "label",
        "manual_review_note",
        "severity",
        "target_scope",
    ]
)

DRY_RUN_PAYLOAD_FIELDS = [
    "name",
    "target_scope",
    "target",
    "alert_type",
    "severity",
    "parameters",
]

FORBIDDEN_SIDE_EFFECTS = [
    "db_write",
    "background_worker",
    "notification",
    "broker_execution",
    "paper_simulation",
]

_PRESETS = [
    {
        "id": "latest_report_validation_block",
        "label": "Latest report validation block",
        "description": "Dry-run the latest report validation BLOCK review for the current symbol.",
        "target_scope": "single_symbol",
        "alert_type": "validation_block",
        "default_parameters": {},
        "severity": "critical",
        "manual_review_note": "仅作为最新日报验证阻断的人工复核提醒，不生成任何执行动作。",
        "is_trade_instruction": False,
    },
    {
        "id": "latest_report_data_gap",
        "label": "Latest report data gap",
        "description": "Dry-run the latest report data-quality review for the current symbol.",
        "target_scope": "single_symbol",
        "alert_type": "data_gap",
        "default_parameters": {},
        "severity": "warning",
        "manual_review_note": "仅作为最新日报数据缺口的人工复核提醒，不生成任何执行动作。",
        "is_trade_instruction": False,
    },
    {
        "id": "asx_announcement_risk",
        "label": "ASX announcement risk",
        "description": "Dry-run ASX official announcement risk review for the current symbol.",
        "target_scope": "single_symbol",
        "alert_type": "announcement_risk",
        "default_parameters": {},
        "severity": "warning",
        "manual_review_note": "仅作为 ASX 公告风险的人工复核提醒，不生成任何执行动作。",
        "is_trade_instruction": False,
    },
    {
        "id": "watchlist_data_basis_review",
        "label": "Watchlist data basis review",
        "description": "Dry-run close-only, delayed, or unavailable data-basis review across the configured watchlist.",
        "target_scope": "watchlist",
        "alert_type": "stale_price",
        "default_parameters": {"max_targets": 50},
        "severity": "warning",
        "manual_review_note": "仅作为自选股行情时间基准的人工复核提醒，不生成任何执行动作。",
        "is_trade_instruction": False,
    },
    {
        "id": "portfolio_concentration_review",
        "label": "Portfolio concentration review",
        "description": "Dry-run holding concentration review across current portfolio holdings.",
        "target_scope": "portfolio_holdings",
        "alert_type": "portfolio_concentration",
        "default_parameters": {"max_weight": 0.25},
        "severity": "warning",
        "manual_review_note": "仅作为组合集中度的人工复核提醒，不生成调仓或交易动作。",
        "is_trade_instruction": False,
    },
    {
        "id": "portfolio_price_stale_review",
        "label": "Portfolio price stale review",
        "description": "Dry-run missing or stale portfolio price-basis review across current holdings.",
        "target_scope": "portfolio_holdings",
        "alert_type": "portfolio_price_stale",
        "default_parameters": {},
        "severity": "warning",
        "manual_review_note": "仅作为组合持仓价格时间基准的人工复核提醒，不生成调仓或交易动作。",
        "is_trade_instruction": False,
    },
]


def get_alert_rule_presets() -> List[Dict[str, Any]]:
    """Return immutable-by-convention preset definitions as plain dictionaries."""
    return deepcopy(_PRESETS)


def build_alert_rule_presets_response() -> Dict[str, Any]:
    """Return the read-only public preset catalog contract."""
    return {
        "mode": "dry_run_manual_review",
        "endpoint": DRY_RUN_ENDPOINT,
        "method": "POST",
        "is_trade_instruction": False,
        "manual_review_required": True,
        "side_effects": [],
        "forbidden_side_effects": list(FORBIDDEN_SIDE_EFFECTS),
        "schema": {
            "required_fields": list(PRESET_REQUIRED_FIELDS),
            "dry_run_payload_fields": list(DRY_RUN_PAYLOAD_FIELDS),
        },
        "links": {
            "dry_run": DRY_RUN_ENDPOINT,
            "presets": PRESETS_ENDPOINT,
            "workbench": WORKBENCH_ENDPOINT,
        },
        "presets": get_alert_rule_presets(),
    }


def build_workbench_alert_rule_presets(
    *,
    context: Mapping[str, Any],
    portfolio_summary: Mapping[str, Any],
    has_watchlist: bool,
) -> List[Dict[str, Any]]:
    """Return context-aware workbench presets with dry-run payloads."""
    latest_code = _latest_symbol(context)
    portfolio = portfolio_summary.get("portfolio") if isinstance(portfolio_summary.get("portfolio"), Mapping) else {}
    holdings = list(portfolio.get("holdings") or []) if isinstance(portfolio, Mapping) else []
    has_holdings = bool(holdings)

    result: List[Dict[str, Any]] = []
    for preset in get_alert_rule_presets():
        enabled, disabled_reason = _availability_for_preset(
            preset,
            latest_code=latest_code,
            has_holdings=has_holdings,
            has_watchlist=has_watchlist,
        )
        item = {
            **preset,
            "enabled": enabled,
            "disabled_reason": disabled_reason,
            "payload": _dry_run_payload_for_preset(preset, latest_code=latest_code),
        }
        result.append(item)
    return result


def _availability_for_preset(
    preset: Mapping[str, Any],
    *,
    latest_code: Optional[str],
    has_holdings: bool,
    has_watchlist: bool,
) -> tuple[bool, Optional[str]]:
    target_scope = str(preset.get("target_scope") or "")
    if target_scope == "single_symbol" and not latest_code:
        return False, "No latest report symbol is available for this dry-run."
    if target_scope == "watchlist" and not has_watchlist:
        return False, "No configured STOCK_LIST watchlist is available for this dry-run."
    if target_scope == "portfolio_holdings" and not has_holdings:
        return False, "No portfolio holdings are available for this dry-run."
    return True, None


def _dry_run_payload_for_preset(preset: Mapping[str, Any], *, latest_code: Optional[str]) -> Dict[str, Any]:
    target_scope = str(preset.get("target_scope") or "")
    target = latest_code if target_scope == "single_symbol" and latest_code else "all"
    label = str(preset.get("label") or "")
    return {
        "name": f"{label} dry-run" if label else "",
        "target_scope": target_scope,
        "target": target,
        "alert_type": str(preset.get("alert_type") or ""),
        "severity": str(preset.get("severity") or "warning"),
        "parameters": deepcopy(preset.get("default_parameters") or {}),
    }


def _latest_symbol(context: Mapping[str, Any]) -> Optional[str]:
    latest_detail = context.get("latest_detail") if isinstance(context.get("latest_detail"), Mapping) else {}
    latest_item = context.get("latest_item") if isinstance(context.get("latest_item"), Mapping) else {}
    code = canonical_stock_code(
        latest_detail.get("stock_code")
        or latest_detail.get("code")
        or latest_item.get("stock_code")
        or latest_item.get("code")
    )
    return code or None
