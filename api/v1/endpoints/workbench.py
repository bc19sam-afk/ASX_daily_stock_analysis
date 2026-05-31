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
from src.services.asx_alert_rule_presets import (
    DRY_RUN_ENDPOINT,
    FORBIDDEN_SIDE_EFFECTS,
    PRESETS_ENDPOINT,
    PRESET_REQUIRED_FIELDS,
    WORKBENCH_ENDPOINT,
    build_workbench_alert_rule_presets,
)
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
    alert_rule_dry_run = _build_alert_rule_dry_run_ui_config(
        context=context,
        portfolio_summary=portfolio_summary,
        config_status=config_status,
    )
    ledger_v2_dry_run = _build_ledger_v2_dry_run_summary()
    ledger_v2_diagnostics = _build_ledger_v2_diagnostics_summary()
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
        "alert_rule_dry_run": alert_rule_dry_run,
        "ledger_v2_dry_run": ledger_v2_dry_run,
        "ledger_v2_diagnostics": ledger_v2_diagnostics,
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
            "alert_rule_dry_run": DRY_RUN_ENDPOINT,
            "alert_rule_presets": PRESETS_ENDPOINT,
            "ledger_v2_dry_run": "/api/v1/portfolio-events/ledger-v2/dry-run",
            "ledger_v2_diagnostics": "/api/v1/portfolio-events/ledger-v2/diagnostics",
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


def _build_alert_rule_dry_run_ui_config(
    *,
    context: Mapping[str, Any],
    portfolio_summary: Mapping[str, Any],
    config_status: Mapping[str, Any],
) -> Dict[str, Any]:
    """Return minimal static-workbench config for temporary alert-rule dry-runs."""
    presets = build_workbench_alert_rule_presets(
        context=context,
        portfolio_summary=portfolio_summary,
        has_watchlist=bool(config_status.get("stock_list_configured")),
    )

    return {
        "mode": "dry_run_manual_review",
        "endpoint": DRY_RUN_ENDPOINT,
        "method": "POST",
        "is_trade_instruction": False,
        "manual_review_required": True,
        "side_effects": [],
        "forbidden_side_effects": list(FORBIDDEN_SIDE_EFFECTS),
        "result_fields": [
            "status",
            "triggered_count",
            "degraded_count",
            "skipped_count",
            "target_results",
            "market_context",
            "is_trade_instruction",
        ],
        "basis_values_requiring_manual_review": ["close_only", "delayed", "unavailable"],
        "copy": {
            "title": "Alert Rule Dry-Run",
            "boundary": "dry-run / manual review only; not a trade instruction",
            "degraded": "close_only, delayed, or unavailable data cannot be inferred as clear.",
        },
        "selector": {
            "mode": "preset",
            "label": "Alert rule preset",
            "options_field": "presets",
        },
        "preset_schema": {
            "required_fields": list(PRESET_REQUIRED_FIELDS),
        },
        "links": {
            "dry_run": DRY_RUN_ENDPOINT,
            "presets": PRESETS_ENDPOINT,
            "workbench": WORKBENCH_ENDPOINT,
        },
        "presets": presets,
        "templates": presets,
    }


def _build_ledger_v2_dry_run_summary() -> Dict[str, Any]:
    """Return a compact pointer to the ledger v2 dry-run diagnostics endpoint."""
    endpoint = "/api/v1/portfolio-events/ledger-v2/dry-run"
    return {
        "mode": "dry_run_manual_review",
        "endpoint": endpoint,
        "method": "GET",
        "is_trade_instruction": False,
        "manual_review_required": True,
        "side_effects": [],
        "forbidden_side_effects": [
            "ledger_v2_storage_write",
            "migration_cutover",
            "broker_connection",
            "order_submission",
            "paper_simulation_write",
            "notification_delivery",
        ],
        "result_fields": [
            "candidate_count",
            "supported_candidate_count",
            "unsupported_candidate_count",
            "comparison",
            "warnings",
            "boundaries",
        ],
        "copy": {
            "title": "Ledger v2 Dry-Run",
            "boundary": "candidate comparison only; v1 portfolio summary remains authoritative",
        },
        "links": {
            "dry_run": endpoint,
            "workbench": WORKBENCH_ENDPOINT,
        },
    }


def _build_ledger_v2_diagnostics_summary() -> Dict[str, Any]:
    """Return a compact pointer to grouped ledger v2 shadow-read diagnostics."""
    diagnostics_endpoint = "/api/v1/portfolio-events/ledger-v2/diagnostics"
    dry_run_endpoint = "/api/v1/portfolio-events/ledger-v2/dry-run"
    return {
        "mode": "dry_run_manual_review",
        "endpoint": diagnostics_endpoint,
        "method": "GET",
        "is_trade_instruction": False,
        "manual_review_required": True,
        "side_effects": [],
        "forbidden_side_effects": [
            "ledger_v2_storage_write",
            "migration_cutover",
            "broker_connection",
            "order_submission",
            "paper_simulation_write",
            "notification_delivery",
        ],
        "result_fields": [
            "summary",
            "details",
            "warnings",
            "boundaries",
        ],
        "copy": {
            "title": "Ledger v2 Diagnostics",
            "boundary": "shadow-read diagnostics only; v1 portfolio summary remains authoritative",
        },
        "links": {
            "diagnostics": diagnostics_endpoint,
            "dry_run": dry_run_endpoint,
            "workbench": WORKBENCH_ENDPOINT,
        },
    }


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
            "provider_status": _build_provider_status({}),
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
        "provider_status": _build_provider_status(item_by_key),
    }


def _build_provider_status(item_by_key: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    """Return low-sensitivity provider/cache status without exposing raw credentials."""
    gemini_model = _config_value(item_by_key, "GEMINI_MODEL", default="gemini-3.5-flash")
    grounding_model = _config_value(item_by_key, "GEMINI_GROUNDING_MODEL", default=gemini_model)
    grounding_enabled = _config_bool(item_by_key, "GEMINI_GROUNDING_SEARCH_ENABLED", default=True)
    tavily_configured = _config_raw_exists(item_by_key, "TAVILY_API_KEYS")
    gemini_configured = _config_raw_exists(item_by_key, "GEMINI_API_KEYS", "GEMINI_API_KEY")
    serpapi_configured = _config_raw_exists(item_by_key, "SERPAPI_API_KEYS")

    return {
        "provider_order": ["Tavily", "Gemini Grounding", "SerpAPI"],
        "active_provider_order": [
            name
            for name, enabled in [
                ("Tavily", tavily_configured),
                ("Gemini Grounding", bool(gemini_configured and grounding_enabled)),
                ("SerpAPI", serpapi_configured),
            ]
            if enabled
        ],
        "providers": {
            "tavily": {
                "label": "Tavily",
                "configured": tavily_configured,
            },
            "gemini": {
                "label": "Gemini",
                "configured": gemini_configured,
                "model": gemini_model,
                "grounding_enabled": grounding_enabled,
                "grounding_configured": bool(gemini_configured and grounding_enabled),
                "grounding_model": grounding_model,
            },
            "serpapi": {
                "label": "SerpAPI",
                "configured": serpapi_configured,
            },
        },
        "news_intel_cache": {
            "enabled": _config_bool(item_by_key, "NEWS_INTEL_CACHE_ENABLED", default=True),
            "days": _config_int(item_by_key, "NEWS_INTEL_CACHE_DAYS", default=1, minimum=1),
            "min_results": _config_int(item_by_key, "NEWS_INTEL_CACHE_MIN_RESULTS", default=1, minimum=1),
        },
        "search_fallback_note": (
            "news_intel cache is checked before external providers when enabled; "
            "stock-news fallback order remains Tavily -> Gemini Grounding -> SerpAPI; "
            "news_intel dimensions may rotate providers across dimensions to spread quota."
        ),
        "quota_safe_note": (
            "Quota-safe status only: this endpoint does not run external search, clear caches, "
            "change provider order, or expose raw secrets."
        ),
    }


def _config_raw_exists(item_by_key: Mapping[str, Mapping[str, Any]], *keys: str) -> bool:
    return any(bool(item_by_key.get(key.upper(), {}).get("raw_value_exists")) for key in keys)


def _config_value(
    item_by_key: Mapping[str, Mapping[str, Any]],
    key: str,
    *,
    default: str,
) -> str:
    item = item_by_key.get(key.upper(), {})
    value = item.get("value")
    if value is None or str(value).strip() == "":
        schema = item.get("schema") if isinstance(item.get("schema"), Mapping) else {}
        value = schema.get("default_value") if schema else None
    if value is None or str(value).strip() == "" or bool(item.get("is_masked")):
        return default
    return str(value).strip()


def _config_bool(
    item_by_key: Mapping[str, Mapping[str, Any]],
    key: str,
    *,
    default: bool,
) -> bool:
    value = _config_value(item_by_key, key, default="true" if default else "false")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _config_int(
    item_by_key: Mapping[str, Mapping[str, Any]],
    key: str,
    *,
    default: int,
    minimum: int,
) -> int:
    value = _config_value(item_by_key, key, default=str(default))
    try:
        return max(minimum, int(value))
    except (TypeError, ValueError):
        return max(minimum, int(default))
