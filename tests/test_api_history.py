# -*- coding: utf-8 -*-
"""HTTP contract tests for history endpoints."""

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.deps import get_database_manager


@pytest.fixture()
def app(tmp_path):
    app = create_app(static_dir=tmp_path / "empty-static")
    yield app
    app.dependency_overrides.clear()


@pytest.fixture()
def client(app):
    return TestClient(app)


def test_history_list_endpoint_returns_paginated_service_results(app, client):
    fake_db = object()
    app.dependency_overrides[get_database_manager] = lambda: fake_db
    service_result = {
        "total": 1,
        "items": [
            {
                "query_id": "q1",
                "stock_code": "BHP.AX",
                "stock_name": "BHP Group",
                "report_type": "full",
                "sentiment_score": 75,
                "operation_advice": "HOLD",
                "created_at": "2026-05-01T10:00:00",
            }
        ],
    }

    with patch("api.v1.endpoints.history.HistoryService") as history_service:
        history_service.return_value.get_history_list.return_value = service_result

        response = client.get("/api/v1/history?page=2&limit=10&stock_code=BHP.AX")

    assert response.status_code == 200
    data = response.json()
    assert data["page"] == 2
    assert data["limit"] == 10
    assert data["total"] == 1
    assert data["items"][0]["query_id"] == "q1"
    assert data["items"][0]["stock_code"] == "BHP.AX"
    history_service.assert_called_once_with(fake_db)
    history_service.return_value.get_history_list.assert_called_once_with(
        stock_code="BHP.AX",
        start_date=None,
        end_date=None,
        page=2,
        limit=10,
    )


def test_history_detail_endpoint_returns_report(app, client):
    fake_db = object()
    app.dependency_overrides[get_database_manager] = lambda: fake_db
    report = {
        "query_id": "q1",
        "stock_code": "BHP.AX",
        "stock_name": "BHP Group",
        "report_type": "full",
        "analysis_summary": "Manual review support only.",
        "operation_advice": "HOLD",
        "sentiment_score": 75,
        "created_at": "2026-05-01T10:00:00",
        "validation_status": "PASS",
        "ideal_buy": "43.00",
        "secondary_buy": "42.00",
        "stop_loss": "40.00",
        "take_profit": "48.00",
    }

    with patch("api.v1.endpoints.history.HistoryService") as history_service:
        history_service.return_value.get_history_detail.return_value = report

        response = client.get("/api/v1/history/q1")

    assert response.status_code == 200
    data = response.json()
    assert data["meta"]["query_id"] == "q1"
    assert data["meta"]["stock_code"] == "BHP.AX"
    assert data["summary"]["sentiment_score"] == 75
    assert data["strategy"]["ideal_buy"] == "43.00"
    history_service.assert_called_once_with(fake_db)
    history_service.return_value.get_history_detail.assert_called_once_with("q1")


def test_history_detail_endpoint_returns_404_when_missing(app, client):
    fake_db = object()
    app.dependency_overrides[get_database_manager] = lambda: fake_db

    with patch("api.v1.endpoints.history.HistoryService") as history_service:
        history_service.return_value.get_history_detail.return_value = None

        response = client.get("/api/v1/history/missing-query")

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"
    history_service.return_value.get_history_detail.assert_called_once_with("missing-query")


def test_portfolio_summary_endpoint_returns_overview_and_recent_actions(app, client):
    fake_db = SimpleNamespace(
        get_portfolio_overview=lambda: {"cash": 1000.0, "holdings": []},
        get_trade_journal=lambda limit=20: [
            SimpleNamespace(
                code="BHP.AX",
                action="OPEN",
                target_weight=0.2,
                current_weight=0.0,
                delta_amount=1000.0,
                reason="test action",
                action_date=date(2026, 5, 1),
            )
        ],
    )
    app.dependency_overrides[get_database_manager] = lambda: fake_db

    response = client.get("/api/v1/history/portfolio/summary")

    assert response.status_code == 200
    data = response.json()
    assert data["portfolio"]["cash"] == 1000.0
    assert data["today_actions"][0] == {
        "code": "BHP.AX",
        "action": "OPEN",
        "target_weight": 0.2,
        "current_weight": 0.0,
        "delta_amount": 1000.0,
        "reason": "test action",
        "action_date": "2026-05-01",
    }
