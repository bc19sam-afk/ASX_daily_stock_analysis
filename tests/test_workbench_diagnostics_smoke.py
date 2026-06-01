# -*- coding: utf-8 -*-
"""Stable Workbench diagnostics smoke tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import create_app
from api.deps import get_database_manager, get_system_config_service


STATIC_HTML = Path(__file__).resolve().parents[1] / "static" / "index.html"


def test_static_workbench_page_opens_with_diagnostics_smoke_hooks():
    app = create_app()
    response = TestClient(app).get("/")

    assert response.status_code == 200
    html = response.text
    assert 'data-smoke-id="workbench-nav"' in html
    assert 'data-smoke-id="nav-diagnostics-hub"' in html
    assert 'data-smoke-id="panel-alert-rule-dry-run"' in html
    assert 'data-smoke-id="panel-diagnostics-hub"' in html
    assert 'data-smoke-id="panel-provider-cache-status"' in html
    assert 'data-smoke-id="diagnostics-hub-card-list"' in html
    assert 'data-smoke-id="diagnostics-operator-flow"' in html
    assert 'data-smoke-id="operator-diagnostics-actions"' in html
    assert 'data-smoke-id="provider-cache-action-group"' in html
    assert 'data-smoke-id="alert-diagnostics-action-group"' in html
    assert 'data-smoke-id="ledger-diagnostics-action-group"' in html
    assert 'data-smoke-id="manual-review-boundary"' in html
    assert "/api/v1/workbench/diagnostics" in html
    assert "/api/v1/alert-rules/dry-run/batch" in html
    assert "/api/v1/portfolio-events/ledger-v2/diagnostics" in html
    assert "not a trade instruction" in html
    assert "manual review only" in html


def test_static_workbench_mobile_layout_has_overflow_guards():
    html = STATIC_HTML.read_text(encoding="utf-8")

    assert "@media (max-width: 720px)" in html
    assert "overflow-wrap: anywhere" in html
    assert ".toolbar { width: 100%; }" in html
    assert "min-width: 0;" in html
    assert "table-layout: fixed;" in html
    assert "max-width: 100%" in html
    assert ".operator-actions { grid-template-columns: 1fr; }" in html


def test_diagnostics_smoke_payload_uses_low_sensitive_fields(tmp_path: Path):
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
            "updated_at": "2026-06-01T10:00:00+10:00",
        }
    )

    with (
        patch("api.v1.endpoints.workbench.HistoryService") as history_service,
        patch("api.v1.endpoints.workbench.BacktestService") as backtest_service,
    ):
        history_service.return_value.get_history_list.return_value = {"total": 0, "items": []}
        backtest_service.return_value.get_summary.return_value = None

        client = TestClient(app)
        summary = client.get("/api/v1/workbench/summary").json()
        hub = client.get("/api/v1/workbench/diagnostics").json()

    assert summary["diagnostics_hub"]["links"]["self"] == "/api/v1/workbench/diagnostics"
    assert hub["schema"]["low_sensitive_only"] is True
    assert hub["schema"]["raw_secret_fields"] == []
    assert hub["side_effects"] == []
    assert {card["id"] for card in hub["cards"]} == set(summary["diagnostics_hub"]["sections"])

    serialized = f"{summary} {hub}"
    assert "secret-tavily" not in serialized
    assert "secret-gemini" not in serialized
    assert "secret-serpapi" not in serialized
    assert "secret-token" not in serialized
    assert "HIN" not in serialized
    assert "account_number" not in serialized
    assert "order_detail" not in serialized
    assert "fill_detail" not in serialized

    app.dependency_overrides.clear()
