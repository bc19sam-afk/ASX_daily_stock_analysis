# -*- coding: utf-8 -*-
"""Contract tests for optional API Bearer authentication."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from src.config import Config


@pytest.fixture()
def client(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "STOCK_LIST=BHP.AX,CBA.AX",
                "GEMINI_API_KEY=secret-key-value",
                "SCHEDULE_TIME=08:00",
                "LOG_LEVEL=INFO",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("ENV_FILE", str(env_path))
    monkeypatch.delenv("API_AUTH_ENABLED", raising=False)
    monkeypatch.delenv("API_AUTH_TOKEN", raising=False)
    Config.reset_instance()

    app = create_app(static_dir=Path(tmp_path) / "empty-static")
    test_client = TestClient(app)
    yield test_client

    Config.reset_instance()


def test_config_endpoint_stays_compatible_when_api_auth_disabled(client):
    response = client.get("/api/v1/system/config")

    assert response.status_code == 200


def test_config_endpoint_returns_401_when_auth_enabled_without_token(client, monkeypatch):
    monkeypatch.setenv("API_AUTH_ENABLED", "true")
    monkeypatch.delenv("API_AUTH_TOKEN", raising=False)

    response = client.get("/api/v1/system/config")

    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


def test_v1_analysis_task_list_requires_auth_when_enabled(client, monkeypatch):
    monkeypatch.setenv("API_AUTH_ENABLED", "true")
    monkeypatch.setenv("API_AUTH_TOKEN", "expected-token")

    response = client.get("/api/v1/analysis/tasks")

    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


def test_v1_mutation_endpoint_requires_auth_when_enabled(client, monkeypatch):
    monkeypatch.setenv("API_AUTH_ENABLED", "true")
    monkeypatch.setenv("API_AUTH_TOKEN", "expected-token")

    response = client.post("/api/v1/paper-portfolio/apply", json={"results": []})

    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


def test_config_endpoint_returns_401_for_wrong_bearer_token(client, monkeypatch):
    monkeypatch.setenv("API_AUTH_ENABLED", "true")
    monkeypatch.setenv("API_AUTH_TOKEN", "expected-token")

    response = client.get(
        "/api/v1/system/config",
        headers={"Authorization": "Bearer wrong-token"},
    )

    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


def test_config_endpoint_accepts_correct_bearer_token(client, monkeypatch):
    monkeypatch.setenv("API_AUTH_ENABLED", "true")
    monkeypatch.setenv("API_AUTH_TOKEN", "expected-token")

    response = client.get(
        "/api/v1/system/config",
        headers={"Authorization": "Bearer expected-token"},
    )

    assert response.status_code == 200


def test_v1_routes_accept_correct_bearer_token_when_auth_enabled(client, monkeypatch):
    monkeypatch.setenv("API_AUTH_ENABLED", "true")
    monkeypatch.setenv("API_AUTH_TOKEN", "expected-token")

    response = client.get(
        "/api/v1/analysis/tasks",
        headers={"Authorization": "Bearer expected-token"},
    )

    assert response.status_code == 200


def test_health_endpoint_does_not_require_api_auth(client, monkeypatch):
    monkeypatch.setenv("API_AUTH_ENABLED", "true")
    monkeypatch.delenv("API_AUTH_TOKEN", raising=False)

    response = client.get("/api/health")

    assert response.status_code == 200


def test_cors_preflight_allows_authorization_header_with_auth_enabled(client, monkeypatch):
    monkeypatch.setenv("API_AUTH_ENABLED", "true")
    monkeypatch.setenv("API_AUTH_TOKEN", "expected-token")

    response = client.options(
        "/api/v1/system/config",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "Authorization" in response.headers["access-control-allow-headers"]
