# -*- coding: utf-8 -*-
"""ASX alert-rule preset contract tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import create_app
from api.deps import get_database_manager, get_system_config_service


EXPECTED_PRESET_IDS = [
    "latest_report_validation_block",
    "latest_report_data_gap",
    "asx_announcement_risk",
    "watchlist_data_basis_review",
    "portfolio_concentration_review",
    "portfolio_price_stale_review",
]

REQUIRED_FIELDS = {
    "id",
    "label",
    "description",
    "target_scope",
    "alert_type",
    "default_parameters",
    "severity",
    "manual_review_note",
    "is_trade_instruction",
}

SENSITIVE_TOKENS = {
    "API_AUTH_TOKEN",
    "HIN",
    "account_number",
    "order_id",
    "fill_id",
    "secret",
    "token",
}


def _client(tmp_path: Path):
    app = create_app(static_dir=tmp_path / "empty-static")
    app.dependency_overrides[get_database_manager] = lambda: SimpleNamespace()
    app.dependency_overrides[get_system_config_service] = lambda: SimpleNamespace(
        get_config=lambda include_schema=False: {"items": [], "updated_at": None}
    )
    return TestClient(app), app


def _latest_detail(**overrides):
    payload = {
        "query_id": "latest-q",
        "stock_code": "BHP.AX",
        "stock_name": "BHP",
        "created_at": "2026-05-29T08:00:00+10:00",
        "report_date": "2026-05-29",
        "technical_basis_date": "2026-05-28",
        "analysis_status": "OK",
        "validation_status": "PASS",
        "validation_issues": [],
        "price_policy": "close_only",
        "execution_price_source": "close_only",
        "data_quality_flag": "OK",
    }
    payload.update(overrides)
    return payload


def _context():
    return {
        "history": {"total": 1, "items": [{"query_id": "latest-q", "stock_code": "BHP.AX"}]},
        "history_items": [{"query_id": "latest-q", "stock_code": "BHP.AX"}],
        "latest_item": {"query_id": "latest-q", "stock_code": "BHP.AX"},
        "latest_detail": _latest_detail(),
        "summary_artifact": {
            "report_date": "2026-05-29",
            "generated_at": "2026-05-29T08:05:00+10:00",
            "price_policy": "close_only",
            "evidence_matrix": {},
            "watch_items": [],
            "blocked_items": [],
        },
        "portfolio_alert_context": {},
    }


def _workbench_client(tmp_path: Path):
    app = create_app(static_dir=tmp_path / "empty-static")
    fake_db = SimpleNamespace(
        get_portfolio_overview=lambda: {
            "cash": 1000.0,
            "total_value": 5000.0,
            "holdings": [{"code": "BHP.AX", "weight": 0.2, "current_price": 40.0}],
        },
        get_trade_journal=lambda limit=20: [],
        get_paper_portfolio_overview=lambda: {"initialized": True, "holdings": []},
        check_portfolio_account_integrity=lambda: {"is_valid": True, "errors": [], "warnings": []},
    )
    app.dependency_overrides[get_database_manager] = lambda: fake_db
    app.dependency_overrides[get_system_config_service] = lambda: SimpleNamespace(
        get_config=lambda include_schema=False: {
            "items": [
                {"key": "STOCK_LIST", "value": "BHP.AX,CBA.AX", "raw_value_exists": True},
                {"key": "API_AUTH_TOKEN", "value": "******", "raw_value_exists": True},
            ],
            "updated_at": "2026-05-29T08:00:00+10:00",
        }
    )
    return TestClient(app), app


def test_presets_endpoint_returns_stable_review_only_contract(tmp_path: Path):
    client, app = _client(tmp_path)

    response = client.get("/api/v1/alert-rules/presets")

    assert response.status_code == 200
    payload = response.json()
    presets = payload["presets"]
    assert [preset["id"] for preset in presets] == EXPECTED_PRESET_IDS
    assert payload["is_trade_instruction"] is False
    assert payload["links"]["dry_run"] == "/api/v1/alert-rules/dry-run"
    assert payload["schema"]["required_fields"] == sorted(REQUIRED_FIELDS)

    for preset in presets:
        assert REQUIRED_FIELDS.issubset(preset)
        assert preset["is_trade_instruction"] is False
        assert preset["target_scope"] in {
            "single_symbol",
            "watchlist",
            "portfolio_holdings",
            "portfolio_account",
        }
        assert preset["severity"] in {"info", "warning", "critical"}
        assert isinstance(preset["default_parameters"], dict)
        assert "人工复核" in preset["manual_review_note"]

    serialized = str(payload)
    for token in SENSITIVE_TOKENS:
        assert token not in serialized
    app.dependency_overrides.clear()


def test_presets_are_convertible_to_dry_run_requests(tmp_path: Path):
    client, app = _client(tmp_path)
    presets = client.get("/api/v1/alert-rules/presets").json()["presets"]

    for preset in presets:
        target = "BHP.AX" if preset["target_scope"] == "single_symbol" else "all"
        dry_run_request = {
            "name": preset["label"],
            "target_scope": preset["target_scope"],
            "target": target,
            "alert_type": preset["alert_type"],
            "severity": preset["severity"],
            "parameters": preset["default_parameters"],
        }
        with patch("api.v1.endpoints.alert_rules._load_workbench_context", return_value=_context()):
            response = client.post("/api/v1/alert-rules/dry-run", json=dry_run_request)
        assert response.status_code == 200
        payload = response.json()
        assert payload["is_trade_instruction"] is False
        assert all(result["is_trade_instruction"] is False for result in payload["target_results"])
        assert "人工复核" in str(payload)
    app.dependency_overrides.clear()


def test_workbench_exposes_preset_selector_schema_and_dynamic_payloads(tmp_path: Path):
    client, app = _workbench_client(tmp_path)
    history_list = {
        "total": 1,
        "items": [
            {
                "query_id": "latest-q",
                "stock_code": "BHP.AX",
                "stock_name": "BHP",
                "report_type": "full",
                "sentiment_score": 72,
                "operation_advice": "HOLD",
                "created_at": "2026-05-29T08:00:00+10:00",
            }
        ],
    }

    with (
        patch("api.v1.endpoints.workbench.HistoryService") as history_service,
        patch("api.v1.endpoints.workbench.BacktestService") as backtest_service,
    ):
        history_service.return_value.get_history_list.return_value = history_list
        history_service.return_value.get_history_detail.return_value = _latest_detail()
        backtest_service.return_value.get_summary.return_value = None
        response = client.get("/api/v1/workbench/summary")

    assert response.status_code == 200
    config = response.json()["alert_rule_dry_run"]
    presets = config["presets"]
    assert [preset["id"] for preset in presets] == EXPECTED_PRESET_IDS
    assert config["links"]["presets"] == "/api/v1/alert-rules/presets"
    assert config["selector"]["mode"] == "preset"
    assert config["preset_schema"]["required_fields"] == sorted(REQUIRED_FIELDS)
    assert config["is_trade_instruction"] is False
    assert config["manual_review_required"] is True

    latest_validation = next(item for item in presets if item["id"] == "latest_report_validation_block")
    assert latest_validation["enabled"] is True
    assert latest_validation["payload"]["target"] == "BHP.AX"
    assert latest_validation["payload"]["alert_type"] == "validation_block"
    assert latest_validation["payload"]["parameters"] == latest_validation["default_parameters"]

    stale_review = next(item for item in presets if item["id"] == "watchlist_data_basis_review")
    assert stale_review["payload"]["target_scope"] == "watchlist"
    assert stale_review["payload"]["target"] == "all"
    assert "人工复核" in stale_review["manual_review_note"]

    serialized = str(config)
    for token in SENSITIVE_TOKENS:
        assert token not in serialized
    app.dependency_overrides.clear()
