# -*- coding: utf-8 -*-
"""Workbench API contract tests."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import create_app
from api.deps import get_database_manager, get_system_config_service


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
    backtest_service.return_value.get_summary.assert_called_once_with(
        scope="overall",
        code=None,
        eval_window_days=None,
    )

    app.dependency_overrides.clear()
