# -*- coding: utf-8 -*-
"""Read-only ASX workbench summary endpoint."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from fastapi import APIRouter, Depends

from api.deps import get_database_manager, get_system_config_service
from src.alert_center import build_alert_center_from_workbench_inputs
from src.services.backtest_service import BacktestService
from src.services.history_service import HistoryService
from src.services.system_config_service import SystemConfigService
from src.storage import DatabaseManager

logger = logging.getLogger(__name__)

router = APIRouter()
DEFAULT_REPORTS_DIR = Path(__file__).resolve().parents[3] / "reports"


@router.get(
    "/summary",
    summary="Get workbench summary",
    description="Read-only first-screen summary for the ASX daily workbench.",
)
def get_workbench_summary(
    db_manager: DatabaseManager = Depends(get_database_manager),
    config_service: SystemConfigService = Depends(get_system_config_service),
) -> Dict[str, Any]:
    """Return the daily workbench summary without triggering analysis or account writes."""
    context = _load_workbench_context(db_manager)
    history = context["history"]
    history_items = context["history_items"]
    latest_item = context["latest_item"]
    latest_detail = context["latest_detail"]
    portfolio_summary = _build_portfolio_summary(db_manager)
    risk_summary = _build_risk_summary(latest_detail=latest_detail, history_items=history_items)
    alert_center = _build_alert_center(context)
    config_status = _build_config_status(config_service)
    backtest_summary = _build_backtest_summary(db_manager)

    return {
        "latest_report": _build_latest_report(latest_item, latest_detail),
        "history": {
            "total": int(history.get("total") or 0),
            "items": history_items,
            "path": "/api/v1/history",
        },
        "portfolio": portfolio_summary.get("portfolio", {}),
        "paper_portfolio": portfolio_summary.get("paper_portfolio", {}),
        "recent_actions": portfolio_summary.get("today_actions", []),
        "risk": risk_summary,
        "alert_center": alert_center,
        "backtest": backtest_summary,
        "config_status": config_status,
        "links": {
            "latest_report": _latest_detail_path(latest_item),
            "history": "/api/v1/history",
            "portfolio": "/api/v1/history/portfolio/summary",
            "paper_portfolio": "/api/v1/paper-portfolio/overview",
            "backtest": "/api/v1/backtest/performance",
            "config": "/api/v1/system/config",
            "alerts": "/api/v1/workbench/alerts",
        },
    }


@router.get(
    "/alerts",
    summary="Get Alert Center detail",
    description="Read-only alert center built from existing report, evidence, and portfolio context.",
)
def get_workbench_alerts(
    db_manager: DatabaseManager = Depends(get_database_manager),
) -> Dict[str, Any]:
    """Return alert detail without triggering analysis, broker calls, or account writes."""
    context = _load_workbench_context(db_manager)
    alert_center = _build_alert_center(context, item_limit=None)
    alert_center["links"] = {
        "summary": "/api/v1/workbench/summary",
        "latest_report": _latest_detail_path(context["latest_item"]),
    }
    return alert_center


@router.get(
    "/alerts/summary",
    summary="Get Alert Center summary",
    description="Compact read-only alert counts for the ASX daily workbench.",
)
def get_workbench_alert_summary(
    db_manager: DatabaseManager = Depends(get_database_manager),
) -> Dict[str, Any]:
    """Return compact alert counts for first-screen clients."""
    context = _load_workbench_context(db_manager)
    alert_center = _build_alert_center(context)
    return {
        "summary": alert_center.get("summary", {}),
        "market_context": alert_center.get("market_context", {}),
        "is_trade_instruction": False,
        "links": {
            "detail": "/api/v1/workbench/alerts",
            "workbench": "/api/v1/workbench/summary",
        },
    }


def _load_workbench_context(db_manager: DatabaseManager) -> Dict[str, Any]:
    history_service = HistoryService(db_manager)
    history = history_service.get_history_list(page=1, limit=8)
    history_items = list(history.get("items") or [])
    latest_item = history_items[0] if history_items else None
    latest_detail = _load_latest_detail(history_service, latest_item)
    summary_artifact = _load_daily_decision_summary(latest_detail)
    portfolio_alert_context = _load_portfolio_alert_context(db_manager)
    return {
        "history": history,
        "history_items": history_items,
        "latest_item": latest_item,
        "latest_detail": latest_detail,
        "summary_artifact": summary_artifact,
        "portfolio_alert_context": portfolio_alert_context,
    }


def _build_alert_center(context: Mapping[str, Any], *, item_limit: Optional[int] = 20) -> Dict[str, Any]:
    return build_alert_center_from_workbench_inputs(
        latest_detail=context.get("latest_detail"),
        summary_artifact=context.get("summary_artifact"),
        portfolio_import_result=context.get("portfolio_alert_context"),
        item_limit=item_limit,
    )


def _load_latest_detail(history_service: HistoryService, latest_item: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    query_id = str((latest_item or {}).get("query_id") or "").strip()
    if not query_id:
        return {}
    try:
        return history_service.get_history_detail(query_id) or {}
    except Exception as exc:
        logger.warning("Failed to load latest workbench report detail: %s", exc)
        return {}


def _load_daily_decision_summary(latest_detail: Mapping[str, Any]) -> Dict[str, Any]:
    """Load the existing daily summary artifact for the latest report date."""
    report_date = str((latest_detail or {}).get("report_date") or "").strip()
    candidate = _daily_summary_path_for_report_date(report_date)
    if candidate is None:
        return {"artifact_status": "missing"}
    try:
        with candidate.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict):
            return payload
        return {"artifact_status": "invalid", "report_date": report_date}
    except FileNotFoundError:
        return {"artifact_status": "missing", "report_date": report_date}
    except Exception as exc:
        logger.warning("Failed to load workbench daily decision summary %s: %s", candidate, exc)
        return {"artifact_status": "invalid", "report_date": report_date}


def _daily_summary_path_for_report_date(report_date: str) -> Optional[Path]:
    digits = "".join(ch for ch in str(report_date or "") if ch.isdigit())
    if len(digits) < 8:
        return None
    return DEFAULT_REPORTS_DIR / f"daily_decision_summary_{digits[:8]}.json"


def _load_portfolio_alert_context(db_manager: DatabaseManager) -> Dict[str, Any]:
    """Expose current ledger integrity issues as read-only Alert Center input."""
    try:
        integrity = db_manager.check_portfolio_account_integrity()
    except AttributeError:
        return {}
    except Exception as exc:
        logger.warning("Failed to load workbench portfolio integrity: %s", exc)
        return {}
    if not isinstance(integrity, Mapping):
        return {}
    return {
        "status": "current_integrity",
        "integrity": {
            "is_valid": bool(integrity.get("is_valid")),
            "errors": list(integrity.get("errors") or []),
            "warnings": list(integrity.get("warnings") or []),
        },
    }


def _build_latest_report(latest_item: Optional[Dict[str, Any]], latest_detail: Dict[str, Any]) -> Dict[str, Any]:
    if not latest_item:
        return {
            "status": "missing",
            "query_id": None,
            "detail_path": None,
            "message": "还没有报告历史。",
        }

    query_id = latest_item.get("query_id")
    return {
        "status": "available",
        "query_id": query_id,
        "detail_path": _latest_detail_path(latest_item),
        "stock_code": latest_item.get("stock_code") or latest_detail.get("stock_code"),
        "stock_name": latest_item.get("stock_name") or latest_detail.get("stock_name"),
        "created_at": latest_item.get("created_at") or latest_detail.get("created_at"),
        "report_date": latest_detail.get("report_date"),
        "technical_basis_date": latest_detail.get("technical_basis_date"),
        "price_policy": latest_detail.get("price_policy"),
        "analysis_summary": latest_detail.get("analysis_summary"),
        "operation_advice": latest_item.get("operation_advice") or latest_detail.get("operation_advice"),
        "position_action": latest_detail.get("position_action"),
        "validation_status": latest_detail.get("validation_status"),
        "data_quality_flag": latest_detail.get("data_quality_flag"),
    }


def _latest_detail_path(latest_item: Optional[Dict[str, Any]]) -> Optional[str]:
    query_id = str((latest_item or {}).get("query_id") or "").strip()
    return f"/api/v1/history/{query_id}" if query_id else None


def _build_portfolio_summary(db_manager: DatabaseManager) -> Dict[str, Any]:
    try:
        overview = db_manager.get_portfolio_overview()
    except Exception as exc:
        logger.warning("Failed to load workbench portfolio overview: %s", exc)
        overview = {"status": "unavailable", "holdings": []}
    try:
        journal = db_manager.get_trade_journal(limit=20)
    except Exception as exc:
        logger.warning("Failed to load workbench recent actions: %s", exc)
        journal = []
    try:
        paper_overview = db_manager.get_paper_portfolio_overview()
    except Exception as exc:
        logger.warning("Failed to load workbench paper portfolio overview: %s", exc)
        paper_overview = {
            "status": "unavailable",
            "initialized": False,
            "holdings": [],
        }

    return {
        "portfolio": overview or {},
        "paper_portfolio": paper_overview or {},
        "today_actions": [
            {
                "code": item.code,
                "action": item.action,
                "target_weight": item.target_weight,
                "current_weight": item.current_weight,
                "delta_amount": item.delta_amount,
                "reason": item.reason,
                "action_date": item.action_date.isoformat() if item.action_date else None,
            }
            for item in journal
        ],
    }


def _build_backtest_summary(db_manager: DatabaseManager) -> Dict[str, Any]:
    try:
        summary = BacktestService(db_manager).get_summary(
            scope="overall",
            code=None,
            eval_window_days=None,
        )
    except Exception as exc:
        logger.warning("Failed to load workbench backtest summary: %s", exc)
        return {
            "status": "unavailable",
            "message": "回测汇总暂时不可用。",
        }

    if not summary:
        return {
            "status": "missing",
            "message": "暂无回测汇总。",
        }

    keys = [
        "scope",
        "eval_window_days",
        "engine_version",
        "computed_at",
        "total_evaluations",
        "completed_count",
        "insufficient_count",
        "win_rate_pct",
        "direction_accuracy_pct",
        "decision_accuracy_pct",
        "avg_simulated_return_pct",
    ]
    compact = {key: summary.get(key) for key in keys}
    compact["status"] = "available"
    return compact


def _build_risk_summary(*, latest_detail: Dict[str, Any], history_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    validation_status = str(latest_detail.get("validation_status") or "").upper()
    if validation_status == "BLOCK":
        issues = latest_detail.get("validation_issues") or ["Validation blocked"]
        for issue in issues:
            items.append(
                {
                    "category": "BLOCK",
                    "code": latest_detail.get("stock_code"),
                    "issue": str(issue),
                    "severity": "block",
                }
            )

    data_quality = str(latest_detail.get("data_quality_flag") or "").upper()
    if data_quality == "MISSING":
        items.append(
            {
                "category": "Data gap",
                "code": latest_detail.get("stock_code"),
                "issue": "Data quality flag is MISSING",
                "severity": "warning",
            }
        )

    if not history_items:
        items.append(
            {
                "category": "Report",
                "code": None,
                "issue": "还没有报告历史。",
                "severity": "warning",
            }
        )

    return {
        "blocked_count": sum(1 for item in items if item["category"] == "BLOCK"),
        "data_gap_count": sum(1 for item in items if item["category"] in {"Data gap", "Report"}),
        "items": items,
    }


def _build_config_status(config_service: SystemConfigService) -> Dict[str, Any]:
    try:
        payload = config_service.get_config(include_schema=False)
    except Exception as exc:
        logger.warning("Failed to load workbench config status: %s", exc)
        return {
            "status": "unavailable",
            "stock_list_configured": False,
            "secrets_configured": 0,
            "updated_at": None,
        }

    items = list(payload.get("items") or [])
    item_by_key = {str(item.get("key") or "").upper(): item for item in items}
    secret_count = sum(
        1
        for key, item in item_by_key.items()
        if (
            key.endswith("_KEY")
            or key.endswith("_TOKEN")
            or "WEBHOOK" in key
        )
        and bool(item.get("raw_value_exists") or item.get("value"))
    )

    stock_list = item_by_key.get("STOCK_LIST") or {}
    return {
        "status": "available",
        "stock_list_configured": bool(stock_list.get("raw_value_exists") or stock_list.get("value")),
        "secrets_configured": secret_count,
        "updated_at": payload.get("updated_at"),
    }
