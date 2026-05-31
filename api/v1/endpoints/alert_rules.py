# -*- coding: utf-8 -*-
"""Read-only alert rule dry-run endpoint."""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.deps import get_database_manager, get_system_config_service
from api.v1.endpoints.workbench import _load_workbench_context
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
