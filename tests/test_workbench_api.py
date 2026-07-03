# -*- coding: utf-8 -*-
"""Workbench API contract tests."""

import inspect
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import create_app
from api.deps import get_database_manager, get_system_config_service
from api.v1.endpoints import workbench
from src.search_service import SearchResponse, SearchResult
from src.storage import DatabaseManager, NewsIntel


def test_workbench_summary_answers_daily_operational_questions(tmp_path: Path):
    app = create_app(static_dir=tmp_path / "empty-static")
    fake_db = SimpleNamespace(
        get_portfolio_overview=lambda: {
            "cash": 1000.0,
            "total_value": 5000.0,
            "holdings": [{"code": "BHP.AX", "weight": 0.2}],
        },
        get_trade_journal=lambda limit=20: [
            SimpleNamespace(
                code="BHP.AX",
                action="ADD",
                target_weight=0.25,
                current_weight=0.2,
                delta_amount=250.0,
                reason="manual review",
                action_date=None,
            )
        ],
        get_paper_portfolio_overview=lambda: {"initialized": True, "holdings": []},
    )
    app.dependency_overrides[get_database_manager] = lambda: fake_db
    app.dependency_overrides[get_system_config_service] = lambda: SimpleNamespace(
        get_config=lambda include_schema=False: {
            "items": [
                {"key": "STOCK_LIST", "value": "BHP.AX", "raw_value_exists": True},
                {"key": "API_AUTH_TOKEN", "value": "******", "raw_value_exists": True},
            ],
            "updated_at": "2026-05-28T08:00:00",
        }
    )

    history_list = {
        "total": 2,
        "items": [
            {
                "query_id": "latest-q",
                "stock_code": "BHP.AX",
                "stock_name": "BHP",
                "report_type": "full",
                "sentiment_score": 72,
                "operation_advice": "HOLD",
                "created_at": "2026-05-28T07:30:00",
            }
        ],
    }
    latest_detail = {
        "query_id": "latest-q",
        "stock_code": "BHP.AX",
        "stock_name": "BHP",
        "report_date": "2026-05-28",
        "analysis_status": "OK",
        "validation_status": "BLOCK",
        "validation_issues": ["收盘价缺失"],
        "position_action": "HOLD",
        "delta_amount": 0.0,
        "data_quality_flag": "MISSING",
        "price_policy": "close_only",
        "execution_price_source": "close_only",
        "analysis_summary": "等待复核",
    }

    backtest_summary = {
        "scope": "overall",
        "eval_window_days": 10,
        "computed_at": "2026-05-28T06:45:00",
        "total_evaluations": 20,
        "completed_count": 14,
        "insufficient_count": 6,
        "win_rate_pct": 57.1,
        "direction_accuracy_pct": 64.3,
        "decision_accuracy_pct": 61.5,
        "avg_simulated_return_pct": 1.8,
    }

    with (
        patch("api.v1.endpoints.workbench.HistoryService") as history_service,
        patch("api.v1.endpoints.workbench.BacktestService") as backtest_service,
    ):
        history_service.return_value.get_history_list.return_value = history_list
        history_service.return_value.get_history_detail.return_value = latest_detail
        backtest_service.return_value.get_summary.return_value = backtest_summary

        response = TestClient(app).get("/api/v1/workbench/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["latest_report"]["query_id"] == "latest-q"
    assert payload["latest_report"]["detail_path"] == "/api/v1/history/latest-q"
    assert payload["history"]["total"] == 2
    assert payload["portfolio"]["cash"] == 1000.0
    assert payload["paper_portfolio"]["initialized"] is True
    assert payload["risk"]["blocked_count"] == 1
    assert payload["risk"]["data_gap_count"] == 1
    assert payload["risk"]["items"][0]["issue"] == "收盘价缺失"
    assert payload["config_status"]["stock_list_configured"] is True
    assert payload["config_status"]["secrets_configured"] == 1
    assert payload["backtest"]["status"] == "available"
    assert payload["backtest"]["completed_count"] == 14
    assert payload["backtest"]["win_rate_pct"] == 57.1
    assert payload["links"]["history"] == "/api/v1/history"
    assert payload["links"]["backtest"] == "/api/v1/backtest/performance"
    assert payload["links"]["alert_rule_presets"] == "/api/v1/alert-rules/presets"
    assert payload["links"]["alert_rule_batch_dry_run"] == "/api/v1/alert-rules/dry-run/batch"
    assert payload["alert_rule_batch_dry_run"]["method"] == "POST"
    assert payload["alert_rule_batch_dry_run"]["is_trade_instruction"] is False
    assert payload["alert_rule_batch_dry_run"]["side_effects"] == []
    assert "notification" in payload["alert_rule_batch_dry_run"]["forbidden_side_effects"]
    assert "background_worker" in payload["alert_rule_batch_dry_run"]["forbidden_side_effects"]
    assert payload["alert_rule_batch_dry_run"]["links"]["batch_dry_run"] == (
        "/api/v1/alert-rules/dry-run/batch"
    )
    assert payload["links"]["ledger_v2_dry_run"] == "/api/v1/portfolio-events/ledger-v2/dry-run"
    assert payload["ledger_v2_dry_run"]["method"] == "GET"
    assert payload["ledger_v2_dry_run"]["is_trade_instruction"] is False
    assert payload["ledger_v2_dry_run"]["side_effects"] == []
    assert "migration_cutover" in payload["ledger_v2_dry_run"]["forbidden_side_effects"]
    assert payload["ledger_v2_dry_run"]["links"]["dry_run"] == "/api/v1/portfolio-events/ledger-v2/dry-run"
    assert payload["links"]["ledger_v2_diagnostics"] == "/api/v1/portfolio-events/ledger-v2/diagnostics"
    assert payload["links"]["diagnostics_hub"] == "/api/v1/workbench/diagnostics"
    assert payload["diagnostics_hub"]["mode"] == "read_only_diagnostics_hub"
    assert payload["diagnostics_hub"]["endpoint"] == "/api/v1/workbench/diagnostics"
    assert payload["diagnostics_hub"]["method"] == "GET"
    assert payload["diagnostics_hub"]["is_trade_instruction"] is False
    assert payload["diagnostics_hub"]["side_effects"] == []
    assert payload["diagnostics_hub"]["sections"] == [
        "provider_status",
        "alert_rule_presets",
        "alert_rule_batch_dry_run",
        "ledger_v2_dry_run",
        "ledger_v2_diagnostics",
        "ledger_v2_rehearsal_report",
    ]
    assert payload["diagnostics_hub"]["links"]["self"] == "/api/v1/workbench/diagnostics"
    assert payload["diagnostics_hub"]["links"]["provider_status"] == "/api/v1/workbench/summary#config_status.provider_status"
    assert payload["diagnostics_hub"]["links"]["alert_rule_presets"] == "/api/v1/alert-rules/presets"
    assert payload["diagnostics_hub"]["links"]["alert_rule_batch_dry_run"] == "/api/v1/alert-rules/dry-run/batch"
    assert payload["diagnostics_hub"]["links"]["ledger_v2_dry_run"] == "/api/v1/portfolio-events/ledger-v2/dry-run"
    assert payload["diagnostics_hub"]["links"]["ledger_v2_diagnostics"] == (
        "/api/v1/portfolio-events/ledger-v2/diagnostics"
    )
    assert payload["diagnostics_hub"]["links"]["ledger_v2_rehearsal_report"] == (
        "/api/v1/portfolio-events/ledger-v2/rehearsal-report"
    )
    assert "run_flow_contract" not in payload["diagnostics_hub"]["links"]
    assert "run_flow_contract" not in payload["diagnostics_hub"]
    assert "summary only" in payload["diagnostics_hub"]["copy"]["boundary"]
    assert payload["ledger_v2_diagnostics"]["method"] == "GET"
    assert payload["ledger_v2_diagnostics"]["is_trade_instruction"] is False
    assert payload["ledger_v2_diagnostics"]["side_effects"] == []
    assert payload["ledger_v2_diagnostics"]["result_fields"] == [
        "summary",
        "details",
        "warnings",
        "boundaries",
    ]
    assert payload["ledger_v2_diagnostics"]["links"]["diagnostics"] == (
        "/api/v1/portfolio-events/ledger-v2/diagnostics"
    )
    assert payload["ledger_v2_diagnostics"]["links"]["dry_run"] == (
        "/api/v1/portfolio-events/ledger-v2/dry-run"
    )
    assert payload["links"]["ledger_v2_rehearsal_report"] == (
        "/api/v1/portfolio-events/ledger-v2/rehearsal-report"
    )
    assert payload["ledger_v2_rehearsal_report"]["method"] == "GET"
    assert payload["ledger_v2_rehearsal_report"]["is_trade_instruction"] is False
    assert payload["ledger_v2_rehearsal_report"]["manual_review_required"] is True
    assert payload["ledger_v2_rehearsal_report"]["side_effects"] == []
    assert "ledger_v2_storage_write" in payload["ledger_v2_rehearsal_report"]["forbidden_side_effects"]
    assert "non_cutover_ready" in payload["ledger_v2_rehearsal_report"]["result_fields"]
    assert payload["ledger_v2_rehearsal_report"]["links"]["rehearsal_report"] == (
        "/api/v1/portfolio-events/ledger-v2/rehearsal-report"
    )
    backtest_service.return_value.get_summary.assert_called_once_with(
        scope="overall",
        code=None,
        eval_window_days=None,
    )

    app.dependency_overrides.clear()


def test_workbench_summary_exposes_provider_cache_status_without_secrets(tmp_path: Path):
    app = create_app(static_dir=tmp_path / "empty-static")
    fake_db = SimpleNamespace(
        get_portfolio_overview=lambda: {},
        get_trade_journal=lambda limit=20: [],
        get_paper_portfolio_overview=lambda: {},
    )
    app.dependency_overrides[get_database_manager] = lambda: fake_db
    app.dependency_overrides[get_system_config_service] = lambda: SimpleNamespace(
        get_config=lambda include_schema=False: {
            "items": [
                {"key": "STOCK_LIST", "value": "BHP.AX", "raw_value_exists": True},
                {"key": "TAVILY_API_KEYS", "value": "secret-tavily", "raw_value_exists": True},
                {"key": "GEMINI_API_KEYS", "value": "secret-gemini", "raw_value_exists": True},
                {"key": "SERPAPI_API_KEYS", "value": "secret-serpapi", "raw_value_exists": False},
                {"key": "SERPAPI_MARKET_REVIEW_FALLBACK_ENABLED", "value": "false", "raw_value_exists": True},
                {"key": "GEMINI_GROUNDING_SEARCH_ENABLED", "value": "true", "raw_value_exists": True},
                {"key": "GEMINI_GROUNDING_MODEL", "value": "gemini-3.5-flash", "raw_value_exists": True},
                {"key": "NEWS_INTEL_CACHE_ENABLED", "value": "true", "raw_value_exists": True},
                {"key": "NEWS_INTEL_CACHE_DAYS", "value": "2", "raw_value_exists": True},
                {"key": "NEWS_INTEL_CACHE_MIN_RESULTS", "value": "3", "raw_value_exists": True},
            ],
            "updated_at": "2026-05-31T08:00:00",
        }
    )

    with (
        patch("api.v1.endpoints.workbench.HistoryService") as history_service,
        patch("api.v1.endpoints.workbench.BacktestService") as backtest_service,
    ):
        history_service.return_value.get_history_list.return_value = {"total": 0, "items": []}
        backtest_service.return_value.get_summary.return_value = None

        response = TestClient(app).get("/api/v1/workbench/summary")

    assert response.status_code == 200
    payload = response.json()
    provider_status = payload["config_status"]["provider_status"]

    assert provider_status["provider_order"] == ["Tavily", "Gemini Grounding", "SerpAPI"]
    assert provider_status["providers"]["tavily"]["configured"] is True
    assert provider_status["providers"]["gemini"]["configured"] is True
    assert provider_status["providers"]["gemini"]["grounding_enabled"] is True
    assert provider_status["providers"]["gemini"]["grounding_model"] == "gemini-3.5-flash"
    assert provider_status["providers"]["serpapi"]["configured"] is False
    assert provider_status["providers"]["serpapi"]["role"] == "low_frequency_fallback"
    assert provider_status["providers"]["serpapi"]["market_review_fallback_enabled"] is False
    assert provider_status["news_intel_cache"] == {
        "enabled": True,
        "days": 2,
        "min_results": 3,
    }
    assert "ordinary stocks" in provider_status["search_fallback_note"]
    assert "SerpAPI is a low-frequency fallback" in provider_status["search_fallback_note"]
    assert "market review skips it by default" in provider_status["search_fallback_note"]
    assert "SERPAPI_MARKET_REVIEW_FALLBACK_ENABLED=true" in provider_status["search_fallback_note"]
    assert "routine rotation" in provider_status["search_fallback_note"]
    assert "does not run external search" in provider_status["quota_safe_note"]

    serialized = str(provider_status)
    assert "secret-tavily" not in serialized
    assert "secret-gemini" not in serialized
    assert "secret-serpapi" not in serialized
    assert "******" not in serialized

    app.dependency_overrides.clear()


def test_workbench_summary_exposes_local_provider_cache_usage_telemetry_without_content(tmp_path: Path):
    app = create_app(static_dir=tmp_path / "empty-static")
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'provider_cache_usage.db'}")
    saved = db.save_news_intel(
        code="BHP.AX",
        name="BHP",
        dimension="latest_news",
        query="BHP private cache query",
        response=SearchResponse(
            query="BHP private cache query",
            provider="Tavily",
            success=True,
            results=[
                SearchResult(
                    title="Provider cache evidence should not leak",
                    snippet="local cache content should remain out of telemetry",
                    url="https://example.com/private-cache-row",
                    source="example.com",
                    published_date="2026-05-30",
                )
            ],
        ),
    )
    assert saved == 1
    with db.get_session() as session:
        row = session.query(NewsIntel).one()
        row.fetched_at = datetime(2026, 5, 31, 23, 15, tzinfo=timezone.utc)
        session.commit()

    app.dependency_overrides[get_database_manager] = lambda: db
    app.dependency_overrides[get_system_config_service] = lambda: SimpleNamespace(
        get_config=lambda include_schema=False: {
            "items": [
                {"key": "STOCK_LIST", "value": "BHP.AX", "raw_value_exists": True},
                {"key": "TAVILY_API_KEYS", "value": "secret-tavily", "raw_value_exists": True},
                {"key": "NEWS_INTEL_CACHE_ENABLED", "value": "true", "raw_value_exists": True},
                {"key": "NEWS_INTEL_CACHE_DAYS", "value": "2", "raw_value_exists": True},
                {"key": "NEWS_INTEL_CACHE_MIN_RESULTS", "value": "1", "raw_value_exists": True},
            ],
            "updated_at": "2026-06-01T08:00:00+10:00",
        }
    )

    with (
        patch("api.v1.endpoints.workbench.HistoryService") as history_service,
        patch("api.v1.endpoints.workbench.BacktestService") as backtest_service,
        patch("src.search_service.SearchService.search_comprehensive_intel") as external_search,
    ):
        history_service.return_value.get_history_list.return_value = {"total": 0, "items": []}
        backtest_service.return_value.get_summary.return_value = None

        response = TestClient(app).get("/api/v1/workbench/summary")

    assert response.status_code == 200
    telemetry = response.json()["config_status"]["provider_status"]["usage_telemetry"]
    assert telemetry["status"] == "available"
    assert telemetry["source"] == "local_news_intel_cache"
    assert telemetry["cache_reuse_provider"] == "news_intel_cache"
    assert telemetry["cache_reuse_enabled"] is True
    assert telemetry["cache_window_days"] == 2
    assert telemetry["min_results"] == 1
    assert telemetry["observed_rows"] == 1
    assert telemetry["observed_dimensions"] == ["latest_news"]
    assert telemetry["last_observed"] == {
        "fetched_at": "2026-05-31T23:15:00+00:00",
        "provider": "Tavily",
        "dimension": "latest_news",
    }
    assert telemetry["side_effects"] == []
    assert telemetry["forbidden_side_effects"] == [
        "external_provider_call",
        "secret_read",
        "cache_clear",
        "db_write",
    ]
    external_search.assert_not_called()

    serialized = str(telemetry)
    assert "secret-tavily" not in serialized
    assert "Provider cache evidence should not leak" not in serialized
    assert "private-cache-row" not in serialized
    assert "private cache query" not in serialized

    app.dependency_overrides.clear()


def test_workbench_diagnostics_hub_aggregates_low_sensitive_links(tmp_path: Path):
    app = create_app(static_dir=tmp_path / "empty-static")
    fake_db = SimpleNamespace(
        get_portfolio_overview=lambda: {},
        get_trade_journal=lambda limit=20: [],
        get_paper_portfolio_overview=lambda: {},
    )
    app.dependency_overrides[get_database_manager] = lambda: fake_db
    app.dependency_overrides[get_system_config_service] = lambda: SimpleNamespace(
        get_config=lambda include_schema=False: {
            "items": [
                {"key": "STOCK_LIST", "value": "BHP.AX", "raw_value_exists": True},
                {"key": "TAVILY_API_KEYS", "value": "secret-tavily", "raw_value_exists": True},
                {"key": "GEMINI_API_KEYS", "value": "secret-gemini", "raw_value_exists": True},
                {"key": "SERPAPI_API_KEYS", "value": "secret-serpapi", "raw_value_exists": True},
                {"key": "API_AUTH_TOKEN", "value": "******", "raw_value_exists": True},
            ],
            "updated_at": "2026-05-31T08:00:00",
        }
    )

    with (
        patch("api.v1.endpoints.workbench.HistoryService") as history_service,
        patch("api.v1.endpoints.workbench.BacktestService") as backtest_service,
    ):
        history_service.return_value.get_history_list.return_value = {"total": 0, "items": []}
        backtest_service.return_value.get_summary.return_value = None

        response = TestClient(app).get("/api/v1/workbench/diagnostics")

    assert response.status_code == 200
    payload = response.json()

    assert payload["mode"] == "read_only_diagnostics_hub"
    assert payload["is_trade_instruction"] is False
    assert payload["manual_review_required"] is True
    assert payload["side_effects"] == []
    assert {
        "db_write",
        "background_worker",
        "notification",
        "broker_execution",
        "paper_simulation",
        "ledger_v2_storage_write",
        "migration_cutover",
    }.issubset(set(payload["forbidden_side_effects"]))
    assert payload["links"] == {
        "self": "/api/v1/workbench/diagnostics",
        "summary": "/api/v1/workbench/summary",
        "provider_status": "/api/v1/workbench/summary#config_status.provider_status",
        "alert_rule_presets": "/api/v1/alert-rules/presets",
        "alert_rule_batch_dry_run": "/api/v1/alert-rules/dry-run/batch",
        "ledger_v2_dry_run": "/api/v1/portfolio-events/ledger-v2/dry-run",
        "ledger_v2_diagnostics": "/api/v1/portfolio-events/ledger-v2/diagnostics",
        "ledger_v2_rehearsal_report": "/api/v1/portfolio-events/ledger-v2/rehearsal-report",
        "run_flow_contract": "/api/v1/workbench/diagnostics#run_flow_contract",
    }

    cards = payload["cards"]
    assert [card["id"] for card in cards] == [
        "provider_status",
        "alert_rule_presets",
        "alert_rule_batch_dry_run",
        "ledger_v2_dry_run",
        "ledger_v2_diagnostics",
        "ledger_v2_rehearsal_report",
        "run_flow_contract",
    ]
    assert cards[0]["status"] == "available"
    assert cards[0]["summary"]["providers_configured"] == {
        "tavily": True,
        "gemini": True,
        "serpapi": True,
    }
    assert cards[0]["summary"]["news_intel_cache_enabled"] is True
    assert cards[0]["summary"]["usage_telemetry"]["cache_reuse_provider"] == "news_intel_cache"
    assert cards[0]["summary"]["usage_telemetry"]["side_effects"] == []
    assert cards[1]["summary"]["endpoint"] == "/api/v1/alert-rules/presets"
    assert cards[2]["summary"]["method"] == "POST"
    assert cards[3]["summary"]["method"] == "GET"
    assert cards[4]["summary"]["method"] == "GET"
    assert cards[5]["summary"]["endpoint"] == "/api/v1/portfolio-events/ledger-v2/rehearsal-report"
    assert cards[5]["summary"]["v1_authoritative"] is True
    assert cards[5]["summary"]["manual_review_required"] is True
    assert cards[6]["summary"]["read_only"] is True
    assert cards[6]["summary"]["side_effects"] == []
    assert cards[6]["summary"]["is_trade_instruction"] is False

    run_flow_contract = payload["run_flow_contract"]
    assert run_flow_contract["mode"] == "read_only_run_flow_contract"
    assert run_flow_contract["read_only"] is True
    assert run_flow_contract["is_trade_instruction"] is False
    assert run_flow_contract["manual_review_required"] is True
    assert run_flow_contract["side_effects"] == []
    assert run_flow_contract["schema"]["models"] == ["lane", "node", "edge", "event", "summary", "snapshot"]
    assert run_flow_contract["links"]["schema"] == "/api/v1/workbench/diagnostics#run_flow_contract.schema"
    assert run_flow_contract["snapshot"]["summary"]["side_effects"] == []
    assert run_flow_contract["snapshot"]["summary"]["is_trade_instruction"] is False

    serialized = str(payload)
    assert "secret-tavily" not in serialized
    assert "secret-gemini" not in serialized
    assert "secret-serpapi" not in serialized
    assert "******" not in serialized
    assert "account" not in serialized.lower()
    assert "hin" not in serialized.lower()
    assert "fill" not in serialized.lower()

    app.dependency_overrides.clear()


def test_diagnostics_hub_builder_has_no_run_flow_opt_in_flag():
    signature = inspect.signature(workbench._build_workbench_diagnostics_hub)

    assert "include_run_flow_contract" not in signature.parameters


def test_run_flow_diagnostics_builder_does_not_mutate_base_hub():
    base_hub = workbench._build_workbench_diagnostics_hub(
        config_status={"provider_status": {"providers": {}, "news_intel_cache": {}}},
        alert_rule_dry_run={"presets": []},
        alert_rule_batch_dry_run={"endpoint": "/batch", "method": "POST", "result_fields": []},
        ledger_v2_dry_run={"endpoint": "/dry-run", "method": "GET", "result_fields": []},
        ledger_v2_diagnostics={"endpoint": "/diagnostics", "method": "GET", "result_fields": []},
        ledger_v2_rehearsal_report={"endpoint": "/rehearsal", "method": "GET", "result_fields": []},
    )
    original_sections = list(base_hub["sections"])
    original_links = dict(base_hub["links"])
    original_cards = list(base_hub["cards"])

    diagnostics_hub = workbench._build_diagnostics_hub_with_run_flow_contract(base_hub)

    assert diagnostics_hub is not base_hub
    assert base_hub["sections"] == original_sections
    assert base_hub["links"] == original_links
    assert base_hub["cards"] == original_cards
    assert "run_flow_contract" not in base_hub
    assert "run_flow_contract" not in base_hub["sections"]
    assert "run_flow_contract" in diagnostics_hub
    assert "run_flow_contract" in diagnostics_hub["sections"]


def test_workbench_diagnostics_hub_exposes_operator_flow_schema(tmp_path: Path):
    app = create_app(static_dir=tmp_path / "empty-static")
    fake_db = SimpleNamespace(
        get_portfolio_overview=lambda: {},
        get_trade_journal=lambda limit=20: [],
        get_paper_portfolio_overview=lambda: {},
    )
    app.dependency_overrides[get_database_manager] = lambda: fake_db
    app.dependency_overrides[get_system_config_service] = lambda: SimpleNamespace(
        get_config=lambda include_schema=False: {
            "items": [
                {"key": "STOCK_LIST", "value": "BHP.AX", "raw_value_exists": True},
                {"key": "TAVILY_API_KEYS", "value": "secret-tavily", "raw_value_exists": True},
                {"key": "GEMINI_API_KEYS", "value": "secret-gemini", "raw_value_exists": True},
                {"key": "SERPAPI_API_KEYS", "value": "secret-serpapi", "raw_value_exists": True},
                {"key": "API_AUTH_TOKEN", "value": "secret-token", "raw_value_exists": True},
            ],
            "updated_at": "2026-06-01T08:00:00+10:00",
        }
    )

    with (
        patch("api.v1.endpoints.workbench.HistoryService") as history_service,
        patch("api.v1.endpoints.workbench.BacktestService") as backtest_service,
    ):
        history_service.return_value.get_history_list.return_value = {"total": 0, "items": []}
        backtest_service.return_value.get_summary.return_value = None

        response = TestClient(app).get("/api/v1/workbench/summary")

    assert response.status_code == 200
    payload = response.json()
    hub = payload["diagnostics_hub"]

    assert hub["schema"]["productization_fields"] == [
        "nav",
        "quick_links",
        "status_badges",
        "action_groups",
    ]
    assert [item["id"] for item in hub["nav"]] == [
        "summary",
        "provider_cache_status",
        "alert_diagnostics",
        "ledger_diagnostics",
        "diagnostics_schema",
    ]
    assert {item["id"] for item in hub["quick_links"]} == {
        "provider_status",
        "alert_rule_batch_dry_run",
        "ledger_v2_diagnostics",
        "ledger_v2_rehearsal_report",
    }
    assert {badge["id"] for badge in hub["status_badges"]} == {
        "read_only",
        "manual_review",
        "not_trade_instruction",
        "no_workers",
        "no_broker",
    }
    assert [group["id"] for group in hub["action_groups"]] == [
        "provider_cache_status",
        "alert_diagnostics",
        "ledger_diagnostics",
        "review_boundary",
    ]
    assert hub["action_groups"][0]["links"] == {
        "provider_status": "/api/v1/workbench/summary#config_status.provider_status",
    }
    assert hub["action_groups"][1]["links"]["alert_rule_presets"] == "/api/v1/alert-rules/presets"
    assert hub["action_groups"][1]["links"]["alert_rule_batch_dry_run"] == (
        "/api/v1/alert-rules/dry-run/batch"
    )
    assert hub["action_groups"][2]["links"]["ledger_v2_diagnostics"] == (
        "/api/v1/portfolio-events/ledger-v2/diagnostics"
    )
    assert hub["action_groups"][2]["links"]["ledger_v2_rehearsal_report"] == (
        "/api/v1/portfolio-events/ledger-v2/rehearsal-report"
    )
    assert hub["action_groups"][3]["is_trade_instruction"] is False
    assert hub["action_groups"][3]["manual_review_required"] is True
    assert all(group["side_effects"] == [] for group in hub["action_groups"])

    serialized = str(hub)
    assert "secret-tavily" not in serialized
    assert "secret-gemini" not in serialized
    assert "secret-serpapi" not in serialized
    assert "secret-token" not in serialized
    assert "account_number" not in serialized
    assert "HIN" not in serialized
    assert "order_detail" not in serialized
    assert "fill_detail" not in serialized

    app.dependency_overrides.clear()


def test_static_workbench_renders_provider_cache_status_copy():
    html = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text(encoding="utf-8")

    assert "Provider & Cache Status" in html
    assert "Quota-safe status only" in html
    assert "news_intel cache" in html
    assert "provider-cache-usage-telemetry" in html
    assert "cache observations" in html
    assert "last observed" in html


def test_static_workbench_renders_diagnostics_hub_entry():
    html = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text(encoding="utf-8")

    assert "Diagnostics Hub" in html
    assert "diagnosticsHubBlock" in html
    assert "renderDiagnosticsHub" in html
    assert "/api/v1/workbench/diagnostics" in html
    assert "provider_status" in html
    assert "ledger_v2_diagnostics" in html
    assert "summary only" in html
