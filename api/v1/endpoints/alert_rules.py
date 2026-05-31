# -*- coding: utf-8 -*-
"""Read-only alert rule dry-run endpoint."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.deps import get_database_manager, get_system_config_service
from api.v1.endpoints.workbench import _load_workbench_context
from src.services.asx_alert_rule_presets import build_alert_rule_presets_response
from src.services.asx_alert_rule_service import AlertRuleDryRunService
from src.services.system_config_service import SystemConfigService
from src.storage import DatabaseManager

router = APIRouter()


class AlertRuleDryRunRequest(BaseModel):
    """Temporary alert rule to evaluate immediately without persistence."""

    name: Optional[str] = Field(default=None, description="Optional display name for this temporary rule")
    target_scope: Literal["single_symbol", "watchlist", "portfolio_holdings", "portfolio_account"]
    target: str = Field(default="all", description="Symbol or all")
    alert_type: Literal[
        "validation_block",
        "data_gap",
        "announcement_risk",
        "stale_price",
        "portfolio_concentration",
        "portfolio_drawdown",
        "portfolio_price_stale",
    ]
    severity: Literal["info", "warning", "critical"] = "warning"
    parameters: Dict[str, Any] = Field(default_factory=dict)


class AlertRuleBatchDryRunRequest(BaseModel):
    """Temporary alert rules to evaluate together without persistence."""

    name: Optional[str] = Field(default=None, description="Optional display name for this temporary diagnostic batch")
    rules: List[AlertRuleDryRunRequest] = Field(
        min_length=1,
        max_length=20,
        description="Temporary dry-run rules to evaluate as one read-only diagnostic batch",
    )


@router.get(
    "/presets",
    summary="List ASX alert rule presets",
    description="Return reusable read-only alert-rule dry-run presets without starting workers, notifications, broker calls, or persisted actions.",
)
def list_alert_rule_presets() -> Dict[str, Any]:
    return build_alert_rule_presets_response()


@router.post(
    "/dry-run",
    summary="Dry-run one ASX alert rule",
    description="Evaluate a temporary read-only alert rule without starting workers, notifications, broker calls, or persisted actions.",
)
def dry_run_alert_rule(
    payload: AlertRuleDryRunRequest,
    db_manager: DatabaseManager = Depends(get_database_manager),
    config_service: SystemConfigService = Depends(get_system_config_service),
) -> Dict[str, Any]:
    context = _load_workbench_context(db_manager)
    return AlertRuleDryRunService(db_manager, config_service).dry_run(
        payload.model_dump(),
        context=context,
    )


@router.post(
    "/dry-run/batch",
    summary="Batch dry-run ASX alert rules",
    description=(
        "Evaluate temporary read-only alert rules as one diagnostics batch without starting workers, "
        "notifications, broker calls, persisted execution state, or account writes."
    ),
)
def batch_dry_run_alert_rules(
    payload: AlertRuleBatchDryRunRequest,
    db_manager: DatabaseManager = Depends(get_database_manager),
    config_service: SystemConfigService = Depends(get_system_config_service),
) -> Dict[str, Any]:
    context = _load_workbench_context(db_manager)
    rules = [rule.model_dump() for rule in payload.rules]
    return AlertRuleDryRunService(db_manager, config_service).batch_dry_run(
        name=payload.name,
        rules=rules,
        context=context,
    )
