# -*- coding: utf-8 -*-
"""HTTP contract tests for backtest endpoints."""

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.deps import get_database_manager


@pytest.fixture()
def app(tmp_path: Path):
    app = create_app(static_dir=tmp_path / "empty-static")
    yield app
    app.dependency_overrides.clear()


@pytest.fixture()
def client(app) -> TestClient:
    return TestClient(app)


def test_backtest_post_starts_task_and_returns_task_id(app, client):
    fake_db = object()
    app.dependency_overrides[get_database_manager] = lambda: fake_db

    with patch("api.v1.endpoints.backtest.BacktestService") as backtest_service:
        backtest_service.return_value.start_backtest_task.return_value = {
            "task_id": "backtest_123",
            "status": "completed",
            "result": {"processed": 2, "saved": 2, "completed": 1, "insufficient": 1, "errors": 0},
        }

        response = client.post(
            "/api/v1/backtest",
            json={"code": "BHP.AX", "force": True, "eval_window_days": 5, "limit": 20},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["task_id"] == "backtest_123"
    assert data["result"]["processed"] == 2
    backtest_service.assert_called_once_with(fake_db)
    backtest_service.return_value.start_backtest_task.assert_called_once_with(
        code="BHP.AX",
        force=True,
        eval_window_days=5,
        min_age_days=None,
        limit=20,
    )


def test_backtest_get_task_returns_result(app, client):
    fake_db = object()
    app.dependency_overrides[get_database_manager] = lambda: fake_db

    with patch("api.v1.endpoints.backtest.BacktestService") as backtest_service:
        backtest_service.return_value.get_backtest_task.return_value = {
            "task_id": "backtest_123",
            "status": "completed",
            "result": {"processed": 1, "saved": 1, "completed": 1, "insufficient": 0, "errors": 0},
        }

        response = client.get("/api/v1/backtest/backtest_123")

    assert response.status_code == 200
    data = response.json()
    assert data["task_id"] == "backtest_123"
    assert data["result"]["completed"] == 1
    backtest_service.assert_called_once_with(fake_db)
    backtest_service.return_value.get_backtest_task.assert_called_once_with("backtest_123")


def test_backtest_get_task_returns_404_when_missing(app, client):
    fake_db = object()
    app.dependency_overrides[get_database_manager] = lambda: fake_db

    with patch("api.v1.endpoints.backtest.BacktestService") as backtest_service:
        backtest_service.return_value.get_backtest_task.return_value = None

        response = client.get("/api/v1/backtest/missing-task")

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"
    backtest_service.return_value.get_backtest_task.assert_called_once_with("missing-task")


def test_backtest_post_rejects_invalid_parameters_before_service_call(app, client):
    fake_db = object()
    app.dependency_overrides[get_database_manager] = lambda: fake_db

    with patch("api.v1.endpoints.backtest.BacktestService") as backtest_service:
        response = client.post("/api/v1/backtest", json={"eval_window_days": 0})

    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"
    backtest_service.assert_not_called()
