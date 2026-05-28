# -*- coding: utf-8 -*-
"""Notification-level ASX announcement integration stays best-effort."""

from datetime import datetime
from zoneinfo import ZoneInfo

from src.analyzer import AnalysisResult
from src.asx_announcements import ASXAnnouncementCheck
from src.notification import NotificationService


def _result(**overrides) -> AnalysisResult:
    base = dict(
        code="BHP.AX",
        name="BHP",
        sentiment_score=70,
        trend_prediction="震荡上行",
        operation_advice="按计划观察",
        final_decision="BUY",
        position_action="ADD",
        current_weight=0.2,
        target_weight=0.25,
        delta_amount=2500.0,
        execution_price_source="close_only",
        market_snapshot={"date": "2026-05-05", "close": "50.00", "source": "yfinance"},
        technical_analysis="MA10 支撑仍在",
        fundamental_analysis="估值稳定",
        news_summary="无重大新增风险",
        action_reason="等待触发条件",
        validation_status="PASS",
    )
    base.update(overrides)
    return AnalysisResult(**base)


def _service(monkeypatch, *, enabled=True):
    service = NotificationService.__new__(NotificationService)
    service._report_timezone = "Australia/Sydney"
    monkeypatch.setattr(service, "_get_primary_action_model", lambda result: {
        "position_action": result.position_action,
        "target_weight": result.target_weight,
        "delta_amount": result.delta_amount,
    })
    monkeypatch.setattr(service, "_classify_price_basis", lambda result: "close_only")
    monkeypatch.setattr(service, "_format_validation_issue_text", lambda result: "；".join(result.validation_issues or []))
    monkeypatch.setattr(service, "_get_actionable_delta_amount_threshold", lambda: 20.0)
    monkeypatch.setattr(service, "_build_backtest_confidence_panel", lambda: {})
    monkeypatch.setattr(service, "_build_score_bucket_calibration", lambda: {})

    config = type(
        "Config",
        (),
        {
            "asx_announcements_enabled": enabled,
            "asx_announcements_lookback_days": 1,
            "asx_announcements_max_items": 5,
            "asx_announcements_timeout_seconds": 10,
        },
    )()
    monkeypatch.setattr("src.notification.get_config", lambda: config)
    return service


def test_notification_summary_inserts_asx_checks_when_enabled(monkeypatch):
    service = _service(monkeypatch, enabled=True)
    captured = {}

    def fake_build_checks(codes, **kwargs):
        captured["codes"] = list(codes)
        captured["kwargs"] = kwargs
        return {
            "BHP.AX": ASXAnnouncementCheck(
                code="BHP.AX",
                checked=False,
                source="asx_market_announcements",
                checked_at="2026-05-06T07:30:00+10:00",
                status="unavailable",
                reason="ASX 公告源不可用，执行前人工检查。",
            )
        }

    monkeypatch.setattr("src.notification.build_asx_announcement_checks", fake_build_checks)

    summary = service.build_daily_decision_summary(
        [_result()],
        report_date="2026-05-06",
        generated_at=datetime(2026, 5, 6, 7, 30, tzinfo=ZoneInfo("Australia/Sydney")),
        overview={"cash": 10000.0, "holdings": []},
    )

    assert captured["codes"] == ["BHP.AX"]
    assert captured["kwargs"]["lookback_days"] == 1
    assert captured["kwargs"]["max_items"] == 5
    assert captured["kwargs"]["timeout_seconds"] == 10
    assert summary["evidence_summary"]["announcement_unavailable"] == 1
    assert summary["action_counts"]["add"] == 1
    assert summary["actionable_items"][0]["target_weight"] == 0.25
    assert summary["actionable_items"][0]["delta_amount"] == 2500.0


def test_notification_summary_keeps_current_behavior_when_asx_source_disabled(monkeypatch):
    service = _service(monkeypatch, enabled=False)
    called = {"value": False}

    def fake_build_checks(codes, **kwargs):
        called["value"] = True
        return {}

    monkeypatch.setattr("src.notification.build_asx_announcement_checks", fake_build_checks)

    summary = service.build_daily_decision_summary(
        [_result()],
        report_date="2026-05-06",
        generated_at=datetime(2026, 5, 6, 7, 30, tzinfo=ZoneInfo("Australia/Sydney")),
        overview={"cash": 10000.0, "holdings": []},
    )

    assert called["value"] is False
    assert "announcement" not in {entry["category"] for entry in summary["evidence_matrix"]["BHP.AX"]}
