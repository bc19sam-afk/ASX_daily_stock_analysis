# -*- coding: utf-8 -*-
"""Alert Center v1 contract tests."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from api.app import create_app
from api.deps import get_database_manager, get_system_config_service
from src.alert_center import (
    ALERT_SEVERITY_CRITICAL,
    ALERT_SEVERITY_INFO,
    ALERT_SEVERITY_WARNING,
    build_alert_center,
)
from src.services.history_service import HistoryService


AS_OF = datetime(2026, 5, 29, 9, 15, tzinfo=ZoneInfo("Australia/Sydney"))


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
        "watchlist_state": "OBSERVE",
        "position_action": "HOLD",
        "data_quality_flag": "OK",
    }
    detail.update(overrides)
    return detail


def _summary_artifact(**overrides):
    payload = {
        "report_date": "2026-05-29",
        "generated_at": "2026-05-29T08:05:00+10:00",
        "price_policy": "close_only",
        "evidence_summary": {
            "stock_count": 1,
            "market_data_available": 1,
            "valuation_missing": 0,
            "announcement_unavailable": 0,
            "announcement_risk_found": 0,
            "backtest_not_checked": 0,
            "validation_block": 0,
        },
        "evidence_matrix": {
            "BHP.AX": [
                {
                    "category": "market_data",
                    "source": "yfinance",
                    "as_of_date": "2026-05-28",
                    "status": "available",
                    "severity": "info",
                    "details": "价格口径：close_only。",
                },
                {
                    "category": "validation",
                    "source": "validation_gate",
                    "as_of_date": "2026-05-28",
                    "status": "available",
                    "severity": "info",
                    "details": "验证通过。",
                },
            ],
        },
        "report_reliability": {"score": 92, "level": "high", "flags": []},
        "watch_items": [],
        "blocked_items": [],
    }
    payload.update(overrides)
    return payload


def _alert_ids(center):
    return {item["id"] for item in center["items"]}


def test_validation_block_generates_review_alert_without_trade_instruction():
    center = build_alert_center(
        latest_detail=_latest_detail(
            validation_status="BLOCK",
            validation_issues=["收盘价缺失，无法确认昨收计划。"],
        ),
        summary_artifact=_summary_artifact(),
        as_of=AS_OF,
    )

    item = next(alert for alert in center["items"] if alert["category"] == "validation")

    assert item["severity"] == ALERT_SEVERITY_CRITICAL
    assert item["code"] == "BHP.AX"
    assert "验证阻断" in item["title"]
    assert "收盘价缺失" in item["message"]
    assert item["source"] == "history.latest_report"
    assert item["as_of"].startswith("2026-05-29T09:15:00")
    assert item["is_trade_instruction"] is False
    assert center["summary"]["critical_count"] == 1


def test_asx_announcement_risk_and_unavailable_enter_alert_center():
    center = build_alert_center(
        latest_detail=_latest_detail(),
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
                "NAB.AX": [
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
        ),
        as_of=AS_OF,
    )

    ids = _alert_ids(center)

    assert "announcement:BHP.AX:risk_found" in ids
    assert "announcement:NAB.AX:unavailable" in ids
    risk = next(item for item in center["items"] if item["id"] == "announcement:BHP.AX:risk_found")
    unavailable = next(item for item in center["items"] if item["id"] == "announcement:NAB.AX:unavailable")
    assert risk["severity"] == ALERT_SEVERITY_CRITICAL
    assert "price-sensitive" in risk["message"]
    assert unavailable["severity"] == ALERT_SEVERITY_WARNING
    assert unavailable["is_trade_instruction"] is False


def test_report_reliability_and_evidence_gaps_enter_alert_center():
    center = build_alert_center(
        latest_detail=_latest_detail(),
        summary_artifact=_summary_artifact(
            report_reliability={
                "score": 48,
                "level": "low_observe_only",
                "flags": [
                    {
                        "code": "evidence_missing",
                        "severity": "warning",
                        "message": "1/2 项技术 / 估值 / 新闻证据缺失、部分可用、过期或未检查。",
                    },
                    {
                        "code": "backtest_not_checked",
                        "severity": "warning",
                        "message": "1/2 只股票回测证据未检查。",
                    },
                ],
            },
            evidence_matrix={
                "BHP.AX": [
                    {
                        "category": "valuation",
                        "source": "valuation_snapshot",
                        "as_of_date": "2026-05-28",
                        "status": "partial",
                        "severity": "warning",
                        "details": "估值快照缺少 PE/PB/股息率。",
                    },
                    {
                        "category": "backtest",
                        "source": "backtest_service",
                        "as_of_date": None,
                        "status": "not_checked",
                        "severity": "warning",
                        "details": "回测证据未检查或未提供。",
                    },
                ]
            },
        ),
        as_of=AS_OF,
    )

    ids = _alert_ids(center)

    assert "report_reliability:evidence_missing" in ids
    assert "evidence:BHP.AX:valuation:partial" in ids
    assert "evidence:BHP.AX:backtest:not_checked" in ids
    assert all(item["is_trade_instruction"] is False for item in center["items"])


def test_portfolio_import_warnings_and_integrity_issues_enter_alert_center():
    center = build_alert_center(
        latest_detail=_latest_detail(),
        summary_artifact=_summary_artifact(),
        portfolio_import_result={
            "status": "preview",
            "warnings": ["Reserved dividend/franking fields are retained for audit."],
            "errors": ["line 3 side must be BUY or SELL"],
            "integrity": {
                "is_valid": False,
                "errors": ["Cash/equity total mismatch"],
                "warnings": ["Position weight mismatch"],
            },
        },
        as_of=AS_OF,
    )

    ids = _alert_ids(center)

    assert "portfolio_import:error:0" in ids
    assert "portfolio_import:warning:0" in ids
    assert "portfolio_integrity:error:0" in ids
    assert "portfolio_integrity:warning:0" in ids
    assert next(item for item in center["items"] if item["id"] == "portfolio_integrity:error:0")["severity"] == ALERT_SEVERITY_CRITICAL


def test_alert_center_uses_sydney_timezone_and_asx_market_calendar():
    pre_close = datetime(2026, 4, 7, 8, 30, tzinfo=ZoneInfo("Australia/Sydney"))

    center = build_alert_center(
        latest_detail=_latest_detail(),
        summary_artifact=_summary_artifact(),
        as_of=pre_close,
    )

    assert center["market_context"]["timezone"] == "Australia/Sydney"
    assert center["market_context"]["calendar"] == "ASX"
    assert center["market_context"]["report_date"] == "2026-04-07"
    assert center["market_context"]["technical_basis_date"] == "2026-04-02"
    assert center["market_context"]["data_basis"] == "close_only"


def test_conflicting_close_only_and_realtime_basis_is_marked_delayed():
    center = build_alert_center(
        latest_detail=_latest_detail(
            price_policy="close_only",
            execution_price_source="realtime",
        ),
        summary_artifact=_summary_artifact(price_policy="close_only"),
        as_of=AS_OF,
    )

    assert center["market_context"]["data_basis"] == "delayed"


def test_blocked_items_only_summary_artifact_generates_critical_alert():
    center = build_alert_center(
        latest_detail=_latest_detail(),
        summary_artifact=_summary_artifact(
            blocked_items=[
                {
                    "code": "NAB.AX",
                    "name": "NAB",
                    "reason": "收盘价缺失，无法确认昨收计划。",
                    "price_basis": "close_only",
                }
            ],
            evidence_matrix={},
            report_reliability={"score": 92, "level": "high", "flags": []},
        ),
        as_of=AS_OF,
    )

    item = next(alert for alert in center["items"] if alert["id"] == "blocked_item:NAB.AX:0")

    assert item["severity"] == ALERT_SEVERITY_CRITICAL
    assert item["category"] == "validation"
    assert item["code"] == "NAB.AX"
    assert "收盘价缺失" in item["message"]
    assert item["is_trade_instruction"] is False


def test_analysis_context_pack_block_generates_critical_alert():
    center = build_alert_center(
        latest_detail=_latest_detail(stock_code=""),
        summary_artifact=_summary_artifact(
            analysis_context_pack={
                "stock_identity": {"code": "WES.AX"},
                "risk_context": {
                    "validation_status": "BLOCK",
                    "validation_issues": ["AnalysisContextPack 缺少稳定昨收基准。"],
                    "actionability": "observation_only",
                },
            }
        ),
        as_of=AS_OF,
    )

    item = next(alert for alert in center["items"] if alert["id"] == "risk_context:WES.AX:0")

    assert item["severity"] == ALERT_SEVERITY_CRITICAL
    assert item["category"] == "risk_context"
    assert item["code"] == "WES.AX"
    assert item["is_trade_instruction"] is False


def test_no_risk_returns_empty_items_and_info_summary_without_fake_alerts():
    center = build_alert_center(
        latest_detail=_latest_detail(),
        summary_artifact=_summary_artifact(),
        as_of=AS_OF,
    )

    assert center["items"] == []
    assert center["summary"]["total"] == 0
    assert center["summary"]["severity"] == ALERT_SEVERITY_INFO
    assert "没有必须优先处理" in center["summary"]["message"]


def test_summary_counts_all_alerts_even_when_display_list_is_capped():
    center = build_alert_center(
        latest_detail=_latest_detail(),
        summary_artifact=_summary_artifact(
            blocked_items=[
                {
                    "code": f"TST{index}.AX",
                    "reason": f"验证阻断 {index}",
                }
                for index in range(25)
            ]
        ),
        as_of=AS_OF,
    )

    assert len(center["items"]) == 20
    assert center["summary"]["display_limit"] == 20
    assert center["summary"]["total"] == 25
    assert center["summary"]["critical_count"] == 25


def test_summary_reports_uncapped_display_limit_when_item_limit_is_none():
    center = build_alert_center(
        latest_detail=_latest_detail(),
        summary_artifact=_summary_artifact(
            blocked_items=[
                {
                    "code": f"TST{index}.AX",
                    "reason": f"验证阻断 {index}",
                }
                for index in range(25)
            ]
        ),
        as_of=AS_OF,
        item_limit=None,
    )

    assert len(center["items"]) == 25
    assert center["summary"]["display_limit"] is None
    assert center["summary"]["visible_count"] == 25
    assert center["summary"]["has_more"] is False


def test_report_freshness_alerts_cover_missing_and_stale_report_data():
    missing = build_alert_center(latest_detail={}, summary_artifact={}, as_of=AS_OF)
    stale = build_alert_center(
        latest_detail=_latest_detail(report_date="2026-05-28"),
        summary_artifact=_summary_artifact(report_date="2026-05-28"),
        as_of=AS_OF,
    )

    missing_item = missing["items"][0]
    stale_item = stale["items"][0]

    assert missing_item["category"] == "report_freshness"
    assert missing_item["severity"] == ALERT_SEVERITY_CRITICAL
    assert missing_item["is_trade_instruction"] is False
    assert "未找到 2026-05-29" in missing_item["message"]
    assert stale_item["category"] == "report_freshness"
    assert stale_item["severity"] == ALERT_SEVERITY_CRITICAL
    assert "当前提醒来自 2026-05-28 日报" in stale_item["message"]


def test_workbench_summary_exposes_alert_center_summary(tmp_path: Path):
    app = create_app(static_dir=tmp_path / "empty-static")
    fake_db = SimpleNamespace(
        get_portfolio_overview=lambda: {"cash": 1000.0, "total_value": 5000.0, "holdings": []},
        get_trade_journal=lambda limit=20: [],
        get_paper_portfolio_overview=lambda: {"initialized": True, "holdings": []},
    )
    app.dependency_overrides[get_database_manager] = lambda: fake_db
    app.dependency_overrides[get_system_config_service] = lambda: SimpleNamespace(
        get_config=lambda include_schema=False: {"items": [], "updated_at": None}
    )

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
        history_service.return_value.get_history_detail.return_value = _latest_detail(
            validation_status="BLOCK",
            validation_issues=["收盘价缺失"],
        )
        backtest_service.return_value.get_summary.return_value = None

        payload = TestClient(app).get("/api/v1/workbench/summary").json()

    assert payload["alert_center"]["summary"]["critical_count"] == 1
    assert payload["alert_center"]["items"][0]["is_trade_instruction"] is False
    assert payload["links"]["alerts"] == "/api/v1/workbench/alerts"

    app.dependency_overrides.clear()


def test_workbench_alert_routes_expose_summary_and_detail(tmp_path: Path):
    app = create_app(static_dir=tmp_path / "empty-static")
    fake_db = SimpleNamespace(
        get_portfolio_overview=lambda: {"cash": 1000.0, "total_value": 5000.0, "holdings": []},
        get_trade_journal=lambda limit=20: [],
        get_paper_portfolio_overview=lambda: {"initialized": True, "holdings": []},
    )
    app.dependency_overrides[get_database_manager] = lambda: fake_db
    app.dependency_overrides[get_system_config_service] = lambda: SimpleNamespace(
        get_config=lambda include_schema=False: {"items": [], "updated_at": None}
    )

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
        history_service.return_value.get_history_detail.return_value = _latest_detail(
            validation_status="BLOCK",
            validation_issues=["收盘价缺失"],
        )
        backtest_service.return_value.get_summary.return_value = None

        client = TestClient(app)
        summary_payload = client.get("/api/v1/workbench/alerts/summary").json()
        detail_payload = client.get("/api/v1/workbench/alerts").json()

    assert summary_payload["summary"]["critical_count"] == 1
    assert summary_payload["links"]["detail"] == "/api/v1/workbench/alerts"
    assert detail_payload["summary"]["critical_count"] == 1
    assert detail_payload["links"]["summary"] == "/api/v1/workbench/summary"
    assert detail_payload["items"][0]["is_trade_instruction"] is False

    app.dependency_overrides.clear()


def test_workbench_alert_routes_load_existing_daily_summary_artifact(tmp_path: Path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "daily_decision_summary_20260529.json").write_text(
        json.dumps(
            _summary_artifact(
                report_date="2026-05-29",
                evidence_matrix={
                    "BHP.AX": [
                        {
                            "category": "announcement",
                            "source": "asx_market_announcements",
                            "as_of_date": "2026-05-29T08:00:00+10:00",
                            "status": "risk_found",
                            "severity": "block",
                            "details": "ASX 官方公告发现 price-sensitive 标记。",
                        },
                        {
                            "category": "valuation",
                            "source": "valuation_snapshot",
                            "as_of_date": "2026-05-28",
                            "status": "partial",
                            "severity": "warning",
                            "details": "估值快照缺少 PE/PB/股息率。",
                        },
                    ]
                },
                report_reliability={
                    "score": 50,
                    "level": "low_observe_only",
                    "flags": [
                        {
                            "code": "asx_announcement_risk_found",
                            "severity": "block",
                            "message": "1 只股票检测到 price-sensitive 公告风险；详见证据矩阵。",
                        }
                    ],
                },
            ),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    app = create_app(static_dir=tmp_path / "empty-static")
    fake_db = SimpleNamespace(
        get_portfolio_overview=lambda: {"cash": 1000.0, "total_value": 5000.0, "holdings": []},
        get_trade_journal=lambda limit=20: [],
        get_paper_portfolio_overview=lambda: {"initialized": True, "holdings": []},
        check_portfolio_account_integrity=lambda: {"is_valid": True, "errors": [], "warnings": []},
    )
    app.dependency_overrides[get_database_manager] = lambda: fake_db
    app.dependency_overrides[get_system_config_service] = lambda: SimpleNamespace(
        get_config=lambda include_schema=False: {"items": [], "updated_at": None}
    )

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
        patch("api.v1.endpoints.workbench.DEFAULT_REPORTS_DIR", reports_dir),
        patch("api.v1.endpoints.workbench.HistoryService") as history_service,
        patch("api.v1.endpoints.workbench.BacktestService") as backtest_service,
    ):
        history_service.return_value.get_history_list.return_value = history_list
        history_service.return_value.get_history_detail.return_value = _latest_detail(
            report_date="2026-05-29",
            validation_status="PASS",
            validation_issues=[],
        )
        backtest_service.return_value.get_summary.return_value = None

        payload = TestClient(app).get("/api/v1/workbench/alerts").json()

    ids = _alert_ids(payload)
    assert "announcement:BHP.AX:risk_found" in ids
    assert "report_reliability:asx_announcement_risk_found" in ids
    assert "evidence:BHP.AX:valuation:partial" in ids
    assert payload["summary"]["critical_count"] >= 1

    app.dependency_overrides.clear()


def test_workbench_alert_routes_include_portfolio_integrity(tmp_path: Path):
    app = create_app(static_dir=tmp_path / "empty-static")
    fake_db = SimpleNamespace(
        get_portfolio_overview=lambda: {"cash": 1000.0, "total_value": 5000.0, "holdings": []},
        get_trade_journal=lambda limit=20: [],
        get_paper_portfolio_overview=lambda: {"initialized": True, "holdings": []},
        check_portfolio_account_integrity=lambda: {
            "is_valid": False,
            "errors": ["Cash/equity total mismatch"],
            "warnings": ["Position weight mismatch"],
        },
    )
    app.dependency_overrides[get_database_manager] = lambda: fake_db
    app.dependency_overrides[get_system_config_service] = lambda: SimpleNamespace(
        get_config=lambda include_schema=False: {"items": [], "updated_at": None}
    )

    with (
        patch("api.v1.endpoints.workbench.DEFAULT_REPORTS_DIR", tmp_path / "reports"),
        patch("api.v1.endpoints.workbench.HistoryService") as history_service,
        patch("api.v1.endpoints.workbench.BacktestService") as backtest_service,
    ):
        history_service.return_value.get_history_list.return_value = {"total": 0, "items": []}
        backtest_service.return_value.get_summary.return_value = None

        payload = TestClient(app).get("/api/v1/workbench/alerts").json()

    ids = _alert_ids(payload)
    assert "portfolio_integrity:error:0" in ids
    assert "portfolio_integrity:warning:0" in ids
    assert next(item for item in payload["items"] if item["id"] == "portfolio_integrity:error:0")["severity"] == ALERT_SEVERITY_CRITICAL

    app.dependency_overrides.clear()


def test_static_workbench_has_alert_center_first_screen_region():
    html = Path("static/index.html").read_text(encoding="utf-8")

    assert "今日提醒" in html
    assert "alertCenterBlock" in html
    assert "renderAlertCenter(data)" in html
    assert "data.alert_center" in html


def test_history_alert_context_exposes_minimal_analysis_context_pack():
    service = HistoryService.__new__(HistoryService)
    payload = service._build_public_alert_context(
        raw_result={},
        context_snapshot={
            "enhanced_context": {
                "analysis_context_pack": {
                    "stock_identity": {"code": "BHP.AX", "name": "BHP"},
                    "price_basis": {"price_policy": "close_only"},
                    "market_snapshot": {"close": 40.0},
                    "portfolio_context": {"cash": 1000.0},
                    "risk_context": {
                        "validation_status": "BLOCK",
                        "validation_issues": ["缺少当日收盘价快照"],
                        "actionability": "observation_only",
                        "internal_score": 0.1,
                    },
                }
            }
        },
    )

    pack = payload["analysis_context_pack"]
    assert pack == {
        "stock_identity": {"code": "BHP.AX"},
        "risk_context": {
            "validation_status": "BLOCK",
            "validation_issues": ["缺少当日收盘价快照"],
            "actionability": "observation_only",
        },
    }
