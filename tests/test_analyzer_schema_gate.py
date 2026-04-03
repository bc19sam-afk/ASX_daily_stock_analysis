# -*- coding: utf-8 -*-

import json

import pytest
from pydantic import ValidationError

from src.analyzer import GeminiAnalyzer


def _valid_payload(include_dashboard: bool = True) -> dict:
    payload = {
        "stock_name": "澳洲联邦银行",
        "sentiment_score": 68,
        "trend_prediction": "看多",
        "operation_advice": "持有",
        "confidence_level": "中",
        "analysis_summary": "趋势偏强，建议跟踪量能变化。",
        "risk_warning": "宏观波动可能加大回撤。",
    }
    if include_dashboard:
        payload["dashboard"] = {
            "core_conclusion": {"one_sentence": "短期偏多，逢回调关注。"},
            "data_perspective": {"trend_status": "ok"},
            "intelligence": {"latest_news": "无重大利空"},
            "battle_plan": {"sniper_points": "观察MA10支撑"},
        }
    return payload


def test_top_level_valid_without_dashboard_still_passes_as_success():
    analyzer = GeminiAnalyzer(api_key=None)
    payload = _valid_payload(include_dashboard=False)

    result = analyzer._parse_response(json.dumps(payload, ensure_ascii=False), "CBA.AX", "股票CBA.AX")

    assert result.success is True
    assert result.dashboard is None
    assert result.analysis_summary == payload["analysis_summary"]


def test_schema_fails_when_dashboard_exists_but_structure_invalid():
    analyzer = GeminiAnalyzer(api_key=None)
    payload = _valid_payload()
    payload["dashboard"] = {
        "core_conclusion": {},
        "data_perspective": {"trend_status": "ok"},
        "intelligence": {"latest_news": "无重大利空"},
        "battle_plan": {"sniper_points": "观察MA10支撑"},
    }

    with pytest.raises(ValidationError):
        analyzer._validate_analysis_output(payload)


def test_repair_path_uses_single_attempt_only(monkeypatch):
    analyzer = GeminiAnalyzer(api_key=None)
    payload = _valid_payload()
    payload.pop("analysis_summary")

    calls = {"single": 0}

    def _single_attempt(_prompt: str, _generation_config: dict) -> str:
        calls["single"] += 1
        repaired = _valid_payload(include_dashboard=False)
        return json.dumps(repaired, ensure_ascii=False)

    monkeypatch.setattr(analyzer, "_call_single_attempt_repair", _single_attempt)
    monkeypatch.setattr(
        analyzer,
        "_call_api_with_retry",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not call _call_api_with_retry")),
    )

    result = analyzer._parse_response(json.dumps(payload, ensure_ascii=False), "CBA.AX", "股票CBA.AX")

    assert calls["single"] == 1
    assert result.success is True


def test_schema_invalid_fallback_does_not_use_keyword_sentiment_guess(monkeypatch):
    analyzer = GeminiAnalyzer(api_key=None)
    payload = {
        "stock_name": "澳洲联邦银行",
        "sentiment_score": "not-an-int",
        "confidence_level": "中",
        "analysis_summary": "",
        "risk_warning": "",
        "buy_reason": "看多，建议买入，bullish buy",
    }

    monkeypatch.setattr(analyzer, "_repair_and_revalidate", lambda _response: None)

    result = analyzer._parse_response(json.dumps(payload, ensure_ascii=False), "CBA.AX", "股票CBA.AX")

    assert result.success is True
    assert result.analysis_status == "DEGRADED"
    assert result.decision_type == "hold"
    assert result.operation_advice == "观望"
    assert result.trend_prediction == "震荡"


def test_missing_top_level_required_fields_triggers_safe_degrade(monkeypatch):
    analyzer = GeminiAnalyzer(api_key=None)
    payload = _valid_payload(include_dashboard=False)
    payload.pop("analysis_summary")

    monkeypatch.setattr(analyzer, "_repair_and_revalidate", lambda _response: None)

    result = analyzer._parse_response(json.dumps(payload, ensure_ascii=False), "CBA.AX", "股票CBA.AX")

    assert result.success is True
    assert result.analysis_status == "DEGRADED"
    assert result.confidence_level == "低"
    assert result.error_message is not None
    assert "schema 校验失败" in result.error_message


def test_normal_success_response_status_is_ok():
    analyzer = GeminiAnalyzer(api_key=None)
    payload = _valid_payload(include_dashboard=False)

    result = analyzer._parse_response(json.dumps(payload, ensure_ascii=False), "CBA.AX", "股票CBA.AX")

    assert result.success is True
    assert result.analysis_status == "OK"


def test_schema_fails_when_sentiment_score_out_of_range():
    analyzer = GeminiAnalyzer(api_key=None)
    payload = _valid_payload()
    payload["sentiment_score"] = 101

    with pytest.raises(ValidationError):
        analyzer._validate_analysis_output(payload)
