# -*- coding: utf-8 -*-
"""Workbench alert-rule dry-run UI smoke tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import create_app
from api.deps import get_database_manager, get_system_config_service


class _NoSideEffectDB:
    """Fake DB that permits workbench reads and fails if write-like methods are used."""

    def __init__(self) -> None:
        self.write_calls: list[str] = []

    def get_portfolio_overview(self):
        return {
            "cash": 1000.0,
            "total_value": 5000.0,
            "holdings": [{"code": "BHP.AX", "weight": 0.2, "current_price": 40.0}],
        }

    def get_trade_journal(self, limit=20):
        return []

    def get_paper_portfolio_overview(self):
        return {"initialized": True, "holdings": []}

    def check_portfolio_account_integrity(self):
        return {"is_valid": True, "errors": [], "warnings": []}

    def __getattr__(self, name: str):
        write_prefixes = (
            "add",
            "apply",
            "create",
            "delete",
            "insert",
            "notify",
            "record",
            "save",
            "send",
            "start_worker",
            "update",
            "write",
        )
        if name.startswith(write_prefixes):
            self.write_calls.append(name)
            raise AssertionError(f"unexpected side-effect DB call: {name}")
        raise AttributeError(name)


class _ConfigService:
    def get_config(self, include_schema=False):
        return {
            "items": [
                {"key": "STOCK_LIST", "value": "BHP.AX,CBA.AX", "raw_value_exists": True},
                {"key": "API_AUTH_TOKEN", "value": "******", "raw_value_exists": True},
            ],
            "updated_at": "2026-05-29T08:00:00+10:00",
        }


def _latest_detail(**overrides):
    detail = {
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
    detail.update(overrides)
    return detail


def _summary_artifact(**overrides):
    payload = {
        "report_date": "2026-05-29",
        "generated_at": "2026-05-29T08:05:00+10:00",
        "price_policy": "close_only",
        "evidence_matrix": {},
        "report_reliability": {"score": 92, "level": "high", "flags": []},
        "watch_items": [],
        "blocked_items": [],
    }
    payload.update(overrides)
    return payload


def _context(*, latest_detail=None, summary_artifact=None):
    return {
        "history": {"total": 1, "items": [{"query_id": "latest-q", "stock_code": "BHP.AX"}]},
        "history_items": [{"query_id": "latest-q", "stock_code": "BHP.AX"}],
        "latest_item": {"query_id": "latest-q", "stock_code": "BHP.AX"},
        "latest_detail": latest_detail if latest_detail is not None else _latest_detail(),
        "summary_artifact": summary_artifact if summary_artifact is not None else _summary_artifact(),
        "portfolio_alert_context": {},
    }


def _client(tmp_path: Path, *, db=None, config_service=None):
    app = create_app(static_dir=tmp_path / "empty-static")
    fake_db = db or _NoSideEffectDB()
    app.dependency_overrides[get_database_manager] = lambda: fake_db
    app.dependency_overrides[get_system_config_service] = lambda: config_service or _ConfigService()
    return TestClient(app), app, fake_db


def test_workbench_summary_exposes_alert_rule_dry_run_ui_schema(tmp_path: Path):
    client, app, _db = _client(tmp_path)
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
        history_service.return_value.get_history_detail.return_value = _latest_detail(data_quality_flag="MISSING")
        backtest_service.return_value.get_summary.return_value = None

        response = client.get("/api/v1/workbench/summary")

    assert response.status_code == 200
    payload = response.json()
    config = payload["alert_rule_dry_run"]
    assert config["endpoint"] == "/api/v1/alert-rules/dry-run"
    assert config["method"] == "POST"
    assert config["mode"] == "dry_run_manual_review"
    assert config["selector"] == {
        "mode": "preset",
        "label": "Alert rule preset",
        "options_field": "presets",
    }
    assert config["links"]["presets"] == "/api/v1/alert-rules/presets"
    assert config["is_trade_instruction"] is False
    assert config["manual_review_required"] is True
    assert config["side_effects"] == []
    assert {
        "db_write",
        "background_worker",
        "notification",
        "broker_execution",
        "paper_simulation",
    }.issubset(set(config["forbidden_side_effects"]))
    assert {
        "status",
        "triggered_count",
        "degraded_count",
        "skipped_count",
        "target_results",
        "market_context",
        "is_trade_instruction",
    }.issubset(set(config["result_fields"]))

    assert config["presets"] == config["templates"]
    assert [preset["id"] for preset in config["presets"]] == [
        "latest_report_validation_block",
        "latest_report_data_gap",
        "asx_announcement_risk",
        "watchlist_data_basis_review",
        "portfolio_concentration_review",
        "portfolio_price_stale_review",
    ]

    data_gap = next(template for template in config["presets"] if template["id"] == "latest_report_data_gap")
    assert data_gap["enabled"] is True
    assert data_gap["payload"] == {
        "name": "Latest report data gap dry-run",
        "target_scope": "single_symbol",
        "target": "BHP.AX",
        "alert_type": "data_gap",
        "severity": "warning",
        "parameters": {},
    }
    assert "API_AUTH_TOKEN" not in str(config)
    app.dependency_overrides.clear()


def test_workbench_schema_template_dry_run_is_review_only_and_has_no_side_effects(tmp_path: Path):
    client, app, fake_db = _client(tmp_path)
    context = _context(latest_detail=_latest_detail(price_policy="close_only", execution_price_source="close_only"))

    with patch("api.v1.endpoints.alert_rules._load_workbench_context", return_value=context):
        response = client.post(
            "/api/v1/alert-rules/dry-run",
            json={
                "name": "Latest report price basis dry-run",
                "target_scope": "single_symbol",
                "target": "BHP.AX",
                "alert_type": "stale_price",
                "severity": "warning",
                "parameters": {},
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["degraded_count"] == 1
    assert payload["triggered_count"] == 0
    assert payload["skipped_count"] == 0
    assert payload["is_trade_instruction"] is False
    assert payload["target_results"][0]["is_trade_instruction"] is False
    assert "不能推断为 clear" in payload["target_results"][0]["message"]
    assert fake_db.write_calls == []
    app.dependency_overrides.clear()


def test_static_workbench_has_alert_rule_dry_run_controls_and_manual_review_copy():
    html = Path("static/index.html").read_text(encoding="utf-8")

    assert "Alert Rule Dry-Run" in html
    assert "alertRuleDryRunBlock" in html
    assert "alertRulePresetSelect" in html
    assert "data-run-selected-preset" in html
    assert "Preset selector" in html
    assert "runAlertRuleDryRun" in html
    assert "/api/v1/alert-rules/dry-run" in html
    assert "config.presets" in html
    assert "dry-run / manual review only" in html
    assert "not a trade instruction" in html
    assert "target_results" in html
    assert "market_context" in html


def test_static_workbench_flags_unavailable_or_degraded_basis_for_manual_review():
    html = Path("static/index.html").read_text(encoding="utf-8")

    assert "basisNeedsManualReview" in html
    assert "close_only" in html
    assert "delayed" in html
    assert "unavailable" in html
    assert "不能推断为 clear" in html
    assert "setInterval" not in html
    assert "new Notification" not in html
    assert "paper-portfolio/trades" not in html
