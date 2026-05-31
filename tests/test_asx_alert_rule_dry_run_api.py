# -*- coding: utf-8 -*-
"""ASX alert-rule dry-run API contract tests."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import create_app
from api.deps import get_database_manager, get_system_config_service
from scripts.manual_portfolio_workflows import HoldingInput, init_portfolio
from src.storage import AccountSnapshot, DatabaseManager


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


class _ConfigService:
    def __init__(self, stock_list: str = "BHP.AX,CBA.AX"):
        self.stock_list = stock_list

    def get_config(self, include_schema=False):
        return {
            "items": [
                {"key": "STOCK_LIST", "value": self.stock_list, "raw_value_exists": True},
            ],
            "updated_at": "2026-05-29T08:00:00+10:00",
        }


def _client(tmp_path: Path, *, db=None, config_service=None):
    app = create_app(static_dir=tmp_path / "empty-static")
    if db is None:
        db = SimpleNamespace(
            get_portfolio_overview=lambda: {"holdings": []},
            check_portfolio_account_integrity=lambda: {"is_valid": True, "errors": [], "warnings": []},
        )
    app.dependency_overrides[get_database_manager] = lambda: db
    app.dependency_overrides[get_system_config_service] = lambda: config_service or _ConfigService()
    return TestClient(app), app


def _post_with_context(client, context, payload):
    with patch("api.v1.endpoints.alert_rules._load_workbench_context", return_value=context):
        return client.post("/api/v1/alert-rules/dry-run", json=payload)


def _table_counts(db: DatabaseManager) -> dict[str, int]:
    from src.storage import PortfolioPosition, TradeJournal

    with db.get_session() as session:
        return {
            "positions": session.query(PortfolioPosition).count(),
            "snapshots": session.query(AccountSnapshot).count(),
            "journal": session.query(TradeJournal).count(),
        }


def test_single_symbol_validation_and_data_gap_dry_run(tmp_path: Path):
    client, app = _client(tmp_path)
    context = _context(
        latest_detail=_latest_detail(
            validation_status="BLOCK",
            validation_issues=["收盘价缺失，无法确认昨收计划。"],
            data_quality_flag="MISSING",
        )
    )

    validation = _post_with_context(
        client,
        context,
        {
            "target_scope": "single_symbol",
            "target": "BHP.AX",
            "alert_type": "validation_block",
            "severity": "critical",
            "parameters": {},
        },
    )
    data_gap = _post_with_context(
        client,
        context,
        {
            "target_scope": "single_symbol",
            "target": "BHP.AX",
            "alert_type": "data_gap",
            "severity": "warning",
            "parameters": {},
        },
    )

    assert validation.status_code == 200
    validation_payload = validation.json()
    assert validation_payload["status"] == "triggered"
    assert validation_payload["triggered"] is True
    assert validation_payload["triggered_count"] == 1
    assert validation_payload["is_trade_instruction"] is False
    result = validation_payload["target_results"][0]
    assert result["target"] == "BHP.AX"
    assert result["status"] == "triggered"
    assert result["observed_value"] == "BLOCK"
    assert result["is_trade_instruction"] is False
    assert "人工复核" in result["action_hint"]

    assert data_gap.status_code == 200
    data_gap_payload = data_gap.json()
    assert data_gap_payload["status"] == "triggered"
    assert data_gap_payload["target_results"][0]["observed_value"] == "MISSING"
    app.dependency_overrides.clear()


def test_announcement_risk_triggers_and_unavailable_degrades(tmp_path: Path):
    client, app = _client(tmp_path)
    context = _context(
        summary_artifact=_summary_artifact(
            evidence_matrix={
                "BHP.AX": [
                    {
                        "category": "announcement",
                        "source": "asx_market_announcements",
                        "as_of_date": "2026-05-29T08:00:00+10:00",
                        "status": "risk_found",
                        "severity": "block",
                        "details": "ASX 官方公告发现 price-sensitive 标记。",
                    }
                ],
                "CBA.AX": [
                    {
                        "category": "announcement",
                        "source": "asx_market_announcements",
                        "as_of_date": "2026-05-29T08:00:00+10:00",
                        "status": "unavailable",
                        "severity": "warning",
                        "details": "ASX 公告源不可用，执行前人工检查。",
                    }
                ],
            }
        )
    )

    risk = _post_with_context(
        client,
        context,
        {
            "target_scope": "single_symbol",
            "target": "BHP.AX",
            "alert_type": "announcement_risk",
            "severity": "critical",
            "parameters": {},
        },
    )
    unavailable = _post_with_context(
        client,
        context,
        {
            "target_scope": "single_symbol",
            "target": "CBA.AX",
            "alert_type": "announcement_risk",
            "severity": "warning",
            "parameters": {},
        },
    )

    assert risk.status_code == 200
    assert risk.json()["status"] == "triggered"
    assert risk.json()["target_results"][0]["observed_value"] == "risk_found"
    assert unavailable.status_code == 200
    unavailable_payload = unavailable.json()
    assert unavailable_payload["status"] == "degraded"
    assert unavailable_payload["triggered"] is False
    assert unavailable_payload["degraded_count"] == 1
    assert unavailable_payload["target_results"][0]["observed_value"] == "unavailable"
    assert "不能推断为 clear" in unavailable_payload["target_results"][0]["message"]
    app.dependency_overrides.clear()


def test_watchlist_expansion_is_capped(tmp_path: Path):
    symbols = ",".join(f"T{i:03d}.AX" for i in range(105))
    client, app = _client(tmp_path, config_service=_ConfigService(symbols))

    response = _post_with_context(
        client,
        _context(),
        {
            "target_scope": "watchlist",
            "target": "all",
            "alert_type": "stale_price",
            "severity": "warning",
            "parameters": {},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["evaluated_count"] == 100
    assert payload["skipped_count"] == 5
    assert len(payload["target_results"]) == 100
    assert all(result["status"] in {"degraded", "skipped"} for result in payload["target_results"])
    app.dependency_overrides.clear()


def test_portfolio_holdings_and_account_rules_are_read_only(tmp_path: Path):
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'alert_rules.db'}")
    init_portfolio(
        db,
        cash=700.0,
        holdings=[HoldingInput(code="BHP.AX", quantity=3.0, avg_cost=100.0)],
    )
    with db.get_session() as session:
        session.add(
            AccountSnapshot(
                snapshot_date=date(2026, 5, 29),
                cash=700.0,
                equity_value=300.0,
                total_value=1000.0,
                daily_pnl=-25.0,
                note="manual snapshot",
                created_at=datetime(2026, 5, 29, 8, 0, tzinfo=timezone.utc),
            )
        )
        session.commit()
    before = _table_counts(db)
    client, app = _client(tmp_path, db=db)

    concentration = _post_with_context(
        client,
        _context(),
        {
            "target_scope": "portfolio_holdings",
            "target": "all",
            "alert_type": "portfolio_concentration",
            "severity": "warning",
            "parameters": {"max_weight": 0.2},
        },
    )
    drawdown = _post_with_context(
        client,
        _context(),
        {
            "target_scope": "portfolio_account",
            "target": "all",
            "alert_type": "portfolio_drawdown",
            "severity": "critical",
            "parameters": {"drawdown_pct": 1.0},
        },
    )

    assert concentration.status_code == 200
    assert concentration.json()["status"] == "triggered"
    assert concentration.json()["target_results"][0]["target"] == "BHP.AX"
    assert concentration.json()["target_results"][0]["observed_value"] == 0.3
    assert drawdown.status_code == 200
    drawdown_payload = drawdown.json()
    assert drawdown_payload["status"] == "triggered"
    assert drawdown_payload["target_results"][0]["target"] == "portfolio_account"
    assert drawdown_payload["target_results"][0]["is_trade_instruction"] is False
    assert _table_counts(db) == before
    app.dependency_overrides.clear()
    DatabaseManager.reset_instance()


def test_close_only_delayed_and_unavailable_price_basis_never_infer_clear(tmp_path: Path):
    client, app = _client(tmp_path)

    close_only = _post_with_context(
        client,
        _context(latest_detail=_latest_detail(price_policy="close_only", execution_price_source="close_only")),
        {
            "target_scope": "single_symbol",
            "target": "BHP.AX",
            "alert_type": "stale_price",
            "severity": "warning",
            "parameters": {},
        },
    )
    delayed = _post_with_context(
        client,
        _context(latest_detail=_latest_detail(price_policy="close_only", execution_price_source="realtime")),
        {
            "target_scope": "single_symbol",
            "target": "BHP.AX",
            "alert_type": "stale_price",
            "severity": "warning",
            "parameters": {},
        },
    )
    unavailable = _post_with_context(
        client,
        _context(latest_detail={}, summary_artifact={}),
        {
            "target_scope": "single_symbol",
            "target": "BHP.AX",
            "alert_type": "stale_price",
            "severity": "warning",
            "parameters": {},
        },
    )

    for response in (close_only, delayed, unavailable):
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] in {"degraded", "triggered"}
        assert payload["status"] != "not_triggered"
        assert payload["target_results"][0]["status"] in {"degraded", "triggered"}
        assert "不能推断" in payload["target_results"][0]["message"]
    app.dependency_overrides.clear()


def test_response_contract_keeps_trade_instruction_false(tmp_path: Path):
    client, app = _client(tmp_path)

    response = _post_with_context(
        client,
        _context(),
        {
            "name": "review only",
            "target_scope": "single_symbol",
            "target": "BHP.AX",
            "alert_type": "validation_block",
            "severity": "info",
            "parameters": {},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["is_trade_instruction"] is False
    assert all(result["is_trade_instruction"] is False for result in payload["target_results"])
    assert "buy" not in str(payload).lower()
    assert "sell" not in str(payload).lower()
    app.dependency_overrides.clear()


def test_invalid_rule_returns_validation_error_or_evaluation_error(tmp_path: Path):
    client, app = _client(tmp_path)

    invalid_scope = client.post(
        "/api/v1/alert-rules/dry-run",
        json={
            "target_scope": "broker_account",
            "target": "all",
            "alert_type": "portfolio_concentration",
            "severity": "warning",
            "parameters": {},
        },
    )
    bad_parameter = _post_with_context(
        client,
        _context(),
        {
            "target_scope": "portfolio_holdings",
            "target": "all",
            "alert_type": "portfolio_concentration",
            "severity": "warning",
            "parameters": {"max_weight": "not-a-number"},
        },
    )

    assert invalid_scope.status_code == 422
    assert bad_parameter.status_code == 200
    assert bad_parameter.json()["status"] == "evaluation_error"
    assert bad_parameter.json()["target_results"][0]["status"] == "evaluation_error"
    app.dependency_overrides.clear()


def test_portfolio_drawdown_rejects_non_account_scope(tmp_path: Path):
    client, app = _client(tmp_path)

    response = _post_with_context(
        client,
        _context(),
        {
            "target_scope": "single_symbol",
            "target": "BHP.AX",
            "alert_type": "portfolio_drawdown",
            "severity": "critical",
            "parameters": {"drawdown_pct": 1.0},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "evaluation_error"
    assert payload["target_results"][0]["target"] == "BHP.AX"
    assert payload["target_results"][0]["observed_value"] == "invalid_scope"
    assert "portfolio_account" in payload["target_results"][0]["message"]
    app.dependency_overrides.clear()
