# -*- coding: utf-8 -*-

import json
from pathlib import Path

from fastapi.testclient import TestClient

from api.app import create_app
from api.v1.endpoints import analysis as analysis_endpoint
from api.v1.schemas.analysis import AnalysisResultResponse
from src.analyzer import AnalysisResult
from src.enums import ReportType
from src.services.analysis_service import AnalysisService
from src.storage import DatabaseManager


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


def test_get_analysis_status_db_fallback_preserves_validation_status(monkeypatch):
    class _TaskQueueStub:
        @staticmethod
        def get_task(_task_id):
            return None

    class _RecordStub:
        code = "600519"
        name = "贵州茅台"
        report_type = "full"
        created_at = None
        sentiment_score = 60
        operation_advice = "持有"
        trend_prediction = "震荡"
        analysis_summary = "回调观察"
        raw_result = json.dumps(
            {
                "analysis_status": "DEGRADED",
                "validation_status": "BLOCK",
                "validation_issues": ["价格口径混用：信号基于旧日线，但执行价使用实时价格。"],
            },
            ensure_ascii=False,
        )

    class _DBStub:
        @staticmethod
        def get_analysis_history(query_id, limit=1):
            assert query_id == "task_x"
            assert limit == 1
            return [_RecordStub()]

    monkeypatch.setattr(analysis_endpoint, "get_task_queue", lambda: _TaskQueueStub())
    monkeypatch.setattr(DatabaseManager, "get_instance", lambda: _DBStub())

    status = analysis_endpoint.get_analysis_status("task_x")
    report = status.result.report

    assert report["meta"]["analysis_status"] == "DEGRADED"
    assert report["summary"]["analysis_status"] == "DEGRADED"
    assert report["meta"]["validation_status"] == "BLOCK"
    assert report["summary"]["validation_status"] == "BLOCK"
    assert report["summary"]["validation_issues"] == ["价格口径混用：信号基于旧日线，但执行价使用实时价格。"]


def test_sync_analyze_response_normalizes_warn_to_pass():
    service = AnalysisService()
    result = AnalysisResult(
        code="600519",
        name="贵州茅台",
        sentiment_score=60,
        trend_prediction="震荡",
        operation_advice="持有",
        analysis_summary="观察",
    )
    result.current_price = 123.4
    result.change_pct = 1.2
    result.analysis_status = "OK"
    result.validation_status = "WARN"
    result.validation_issues = ["non-blocking"]
    result.position_action = "HOLD"
    result.alpha_decision = "HOLD"
    result.final_decision = "HOLD"
    result.watchlist_state = "OBSERVE"
    result.market_regime = "NEUTRAL"
    result.news_sentiment = "NEU"
    result.event_risk = "LOW"
    result.sector_tone = "NEU"
    result.data_quality_flag = "OK"
    result.current_weight = 0.1
    result.target_weight = 0.1
    result.delta_amount = 0.0
    result.action_reason = "observe"
    result.dashboard = None
    result.news_summary = ""
    result.success = True

    payload = service._build_analysis_response(result, "query_sync_warn", ReportType.FULL)

    assert payload["report"]["meta"]["validation_status"] == "PASS"
    assert payload["report"]["summary"]["validation_status"] == "PASS"


def test_get_analysis_status_db_fallback_normalizes_warn_to_pass(monkeypatch):
    class _TaskQueueStub:
        @staticmethod
        def get_task(_task_id):
            return None

    class _RecordStub:
        code = "600519"
        name = "贵州茅台"
        report_type = "full"
        created_at = None
        sentiment_score = 60
        operation_advice = "持有"
        trend_prediction = "震荡"
        analysis_summary = "回调观察"
        raw_result = json.dumps(
            {
                "analysis_status": "OK",
                "validation_status": "WARN",
                "validation_issues": ["legacy warn"],
            },
            ensure_ascii=False,
        )

    class _DBStub:
        @staticmethod
        def get_analysis_history(query_id, limit=1):
            assert query_id == "task_warn"
            assert limit == 1
            return [_RecordStub()]

    monkeypatch.setattr(analysis_endpoint, "get_task_queue", lambda: _TaskQueueStub())
    monkeypatch.setattr(DatabaseManager, "get_instance", lambda: _DBStub())

    status = analysis_endpoint.get_analysis_status("task_warn")
    report = status.result.report

    assert report["meta"]["validation_status"] == "PASS"
    assert report["summary"]["validation_status"] == "PASS"
