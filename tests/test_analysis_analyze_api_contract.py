# -*- coding: utf-8 -*-

import json
import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from api.app import create_app
from api.v1.endpoints import analysis as analysis_endpoint
from api.v1.endpoints import history as history_endpoint
from api.v1.schemas.analysis import AnalysisResultResponse
from src.analyzer import AnalysisResult
from src.enums import ReportType
from src.services.analysis_service import AnalysisService
from src.storage import DatabaseManager


def _build_client() -> TestClient:
    app = create_app(static_dir=Path("tests/nonexistent-static-dir"))
    return TestClient(app)


def _build_result(**overrides) -> AnalysisResult:
    result = AnalysisResult(
        code="600519",
        name="茅台",
        sentiment_score=60,
        trend_prediction="震荡",
        operation_advice="持有",
        analysis_summary="观察等待",
    )
    result.current_price = 123.4
    result.change_pct = 1.2
    result.analysis_status = "OK"
    result.validation_status = "PASS"
    result.validation_issues = []
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

    for key, value in overrides.items():
        setattr(result, key, value)

    return result


def _build_status_response_from_db(monkeypatch, db: DatabaseManager, task_id: str):
    class _TaskQueueStub:
        @staticmethod
        def get_task(_task_id):
            return None

    monkeypatch.setattr(analysis_endpoint, "get_task_queue", lambda: _TaskQueueStub())
    monkeypatch.setattr(DatabaseManager, "get_instance", lambda: db)
    return analysis_endpoint.get_analysis_status(task_id)


def _save_result_to_temp_db(result: AnalysisResult, query_id: str, *, with_snapshot: bool = False) -> DatabaseManager:
    tmpdir = tempfile.TemporaryDirectory()
    db_path = os.path.join(tmpdir.name, "analysis.db")
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url=f"sqlite:///{db_path}")
    db.save_analysis_history(
        result=result,
        query_id=query_id,
        report_type="full",
        news_content="",
        context_snapshot=(
            {"enhanced_context": {"realtime": {"price": result.current_price, "change_pct": result.change_pct}}}
            if with_snapshot
            else None
        ),
    )
    db._test_tmpdir = tmpdir  # keep temp dir alive for test lifetime
    return db


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
    assert "只支持分析一只股票" in payload["message"]


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
        name = "茅台"
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
                "validation_issues": ["mixed price basis"],
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
    assert report["summary"]["validation_issues"] == ["mixed price basis"]


def test_sync_analyze_response_normalizes_warn_to_pass():
    service = AnalysisService()
    result = _build_result(validation_status="WARN", validation_issues=["non-blocking"])

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
        name = "茅台"
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


def test_get_analysis_status_db_fallback_matches_sync_and_history_summary_for_blocked_holding(monkeypatch):
    service = AnalysisService()
    result = _build_result(
        code="BHP.AX",
        name="BHP",
        sentiment_score=65,
        analysis_status="DEGRADED",
        validation_status="BLOCK",
        validation_issues=["mixed price basis", "stale daily context"],
        operation_advice="不可决策，仅观察",
        position_action="HOLD",
        alpha_decision="HOLD",
        final_decision="HOLD",
        watchlist_state="OBSERVE",
        data_quality_flag="MISSING",
        current_weight=2 / 3,
        target_weight=2 / 3,
        delta_amount=0.0,
        action_reason="validator blocked",
    )
    sync_summary = service._build_analysis_response(
        result,
        "query_blocked_sync",
        ReportType.FULL,
    )["report"]["summary"]
    db = _save_result_to_temp_db(result, "query_blocked_sync", with_snapshot=True)

    try:
        status_summary = _build_status_response_from_db(
            monkeypatch,
            db,
            "query_blocked_sync",
        ).result.report["summary"]
        history_summary = history_endpoint.get_history_detail(
            "query_blocked_sync",
            db_manager=db,
        ).summary.model_dump()
    finally:
        DatabaseManager.reset_instance()
        db._test_tmpdir.cleanup()

    for field in (
        "sentiment_label",
        "validation_status",
        "validation_issues",
        "position_action",
        "current_weight",
        "target_weight",
        "delta_amount",
        "action_reason",
        "alpha_decision",
        "final_decision",
        "watchlist_state",
        "market_regime",
        "news_sentiment",
        "event_risk",
        "sector_tone",
        "data_quality_flag",
    ):
        assert status_summary[field] == sync_summary[field] == history_summary[field]


def test_get_analysis_status_db_fallback_preserves_blocked_holding_weights(monkeypatch):
    result = _build_result(
        code="BHP.AX",
        name="BHP",
        sentiment_score=65,
        analysis_status="DEGRADED",
        validation_status="BLOCK",
        validation_issues=["mixed price basis"],
        operation_advice="不可决策，仅观察",
        position_action="HOLD",
        current_weight=2 / 3,
        target_weight=2 / 3,
        delta_amount=0.0,
        action_reason="keep current holding",
    )
    db = _save_result_to_temp_db(result, "query_blocked_weights")

    try:
        summary = _build_status_response_from_db(
            monkeypatch,
            db,
            "query_blocked_weights",
        ).result.report["summary"]
    finally:
        DatabaseManager.reset_instance()
        db._test_tmpdir.cleanup()

    assert summary["position_action"] == "HOLD"
    assert summary["current_weight"] == 2 / 3
    assert summary["target_weight"] == 2 / 3
    assert summary["delta_amount"] == 0.0
    assert summary["action_reason"] == "keep current holding"


def test_get_analysis_status_db_fallback_preserves_pass_action_fields(monkeypatch):
    result = _build_result(
        position_action="ADD",
        alpha_decision="BUY",
        final_decision="BUY",
        watchlist_state="ACTIVE",
        current_weight=0.1,
        target_weight=0.18,
        delta_amount=3200.0,
        action_reason="trend confirmation",
    )
    db = _save_result_to_temp_db(result, "query_pass_fields")

    try:
        summary = _build_status_response_from_db(
            monkeypatch,
            db,
            "query_pass_fields",
        ).result.report["summary"]
    finally:
        DatabaseManager.reset_instance()
        db._test_tmpdir.cleanup()

    assert summary["position_action"] == "ADD"
    assert summary["alpha_decision"] == "BUY"
    assert summary["final_decision"] == "BUY"
    assert summary["watchlist_state"] == "ACTIVE"
    assert summary["current_weight"] == 0.1
    assert summary["target_weight"] == 0.18
    assert summary["delta_amount"] == 3200.0
    assert summary["action_reason"] == "trend confirmation"
