# -*- coding: utf-8 -*-
"""HTTP contract tests for stock data endpoints."""

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import create_app


def _build_client(tmp_path: Path) -> TestClient:
    app = create_app(static_dir=tmp_path / "empty-static")
    return TestClient(app)


def test_quote_endpoint_returns_service_quote(tmp_path):
    client = _build_client(tmp_path)
    quote = {
        "stock_code": "BHP.AX",
        "stock_name": "BHP Group",
        "current_price": 44.2,
        "change": 0.35,
        "change_percent": 0.8,
        "open": 43.85,
        "high": 44.5,
        "low": 43.6,
        "prev_close": 43.85,
        "volume": 1000,
        "amount": 44200,
        "update_time": "2026-05-01T16:10:00+10:00",
    }

    with patch("api.v1.endpoints.stocks.StockService") as stock_service:
        stock_service.return_value.get_realtime_quote.return_value = quote

        response = client.get("/api/v1/stocks/BHP.AX/quote")

    assert response.status_code == 200
    data = response.json()
    assert data["stock_code"] == "BHP.AX"
    assert data["stock_name"] == "BHP Group"
    assert data["current_price"] == 44.2
    stock_service.return_value.get_realtime_quote.assert_called_once_with("BHP.AX")


def test_quote_endpoint_returns_404_when_service_has_no_quote(tmp_path):
    client = _build_client(tmp_path)

    with patch("api.v1.endpoints.stocks.StockService") as stock_service:
        stock_service.return_value.get_realtime_quote.return_value = None

        response = client.get("/api/v1/stocks/MISSING.AX/quote")

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"
    stock_service.return_value.get_realtime_quote.assert_called_once_with("MISSING.AX")


def test_history_endpoint_returns_service_kline_data(tmp_path):
    client = _build_client(tmp_path)
    history = {
        "stock_name": "BHP Group",
        "data": [
            {
                "date": "2026-05-01",
                "open": 43.0,
                "high": 44.5,
                "low": 42.8,
                "close": 44.2,
                "volume": 1000,
                "amount": 44200,
                "change_percent": 1.2,
            }
        ],
    }

    with patch("api.v1.endpoints.stocks.StockService") as stock_service:
        stock_service.return_value.get_history_data.return_value = history

        response = client.get("/api/v1/stocks/BHP.AX/history?period=daily&days=5")

    assert response.status_code == 200
    data = response.json()
    assert data["stock_code"] == "BHP.AX"
    assert data["stock_name"] == "BHP Group"
    assert data["period"] == "daily"
    assert data["data"][0]["close"] == 44.2
    stock_service.return_value.get_history_data.assert_called_once_with(
        stock_code="BHP.AX",
        period="daily",
        days=5,
    )


def test_history_endpoint_rejects_invalid_period_before_service_call(tmp_path):
    client = _build_client(tmp_path)

    with patch("api.v1.endpoints.stocks.StockService") as stock_service:
        response = client.get("/api/v1/stocks/BHP.AX/history?period=intraday")

    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"
    stock_service.assert_not_called()


def test_extract_from_image_rejects_unsupported_mime_type(tmp_path):
    client = _build_client(tmp_path)

    response = client.post(
        "/api/v1/stocks/extract-from-image",
        files={"file": ("stocks.txt", b"not an image", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["error"] == "unsupported_type"
