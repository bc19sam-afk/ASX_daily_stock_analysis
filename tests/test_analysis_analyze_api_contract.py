# -*- coding: utf-8 -*-

from pathlib import Path

from fastapi.testclient import TestClient

from api.app import create_app
from api.v1.endpoints import analysis as analysis_endpoint
from api.v1.schemas.analysis import AnalysisResultResponse


def _build_client() -> TestClient:
    app = create_app(static_dir=Path("tests/nonexistent-static-dir"))
    return TestClient(app)


def test_analyze_rejects_multiple_stock_codes_with_validation_error():
    client = _build_client()

    response = client.post(
        "/api/v1/analysis/analyze",
        json={
            "stock_codes": ["600519", "000858"],
            "report_type": "full",
            "force_refresh": False,
            "async_mode": False,
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error"] == "validation_error"
    assert "当前一次只支持分析一只股票" in payload["message"]


def test_analyze_allows_single_stock_codes_and_enters_existing_path(monkeypatch):
    client = _build_client()
    captured = {}

    def _fake_sync_handler(stock_code, request):
        captured["stock_code"] = stock_code
        captured["request_stock_codes"] = request.stock_codes
        return AnalysisResultResponse(
            query_id="test_query_id",
            stock_code=stock_code,
            stock_name=None,
            report=None,
            created_at="2026-01-01T00:00:00",
        )

    monkeypatch.setattr(analysis_endpoint, "_handle_sync_analysis", _fake_sync_handler)

    response = client.post(
        "/api/v1/analysis/analyze",
        json={
            "stock_codes": ["600519"],
            "report_type": "full",
            "force_refresh": False,
            "async_mode": False,
        },
    )

    assert response.status_code == 200
    assert captured["stock_code"] == "600519"
    assert captured["request_stock_codes"] == ["600519"]
