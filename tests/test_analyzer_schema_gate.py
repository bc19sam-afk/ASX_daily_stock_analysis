# -*- coding: utf-8 -*-

import json

import pytest
from pydantic import ValidationError

from src.analyzer import GeminiAnalyzer


def _valid_payload() -> dict:
    return {
        "stock_name": "澳洲联邦银行",
        "sentiment_score": 68,
        "trend_prediction": "看多",
        "operation_advice": "持有",
        "confidence_level": "中",
        "analysis_summary": "趋势偏强，建议跟踪量能变化。",
        "risk_warning": "宏观波动可能加大回撤。",
        "dashboard": {
            "core_conclusion": {"one_sentence": "短期偏多，逢回调关注。"},
            "data_perspective": {"trend_status": "ok"},
            "intelligence": {"latest_news": "无重大利空"},
            "battle_plan": {"sniper_points": "观察MA10支撑"},
        },
    }


def test_valid_minimal_json_passes_schema_and_maps_to_analysis_result(monkeypatch):
    analyzer = GeminiAnalyzer(api_key=None)
    payload = _valid_payload()
    response_text = json.dumps(payload, ensure_ascii=False)

    result = analyzer._parse_response(response_text, "CBA.AX", "股票CBA.AX")

    assert result.success is True
    assert result.analysis_summary == payload["analysis_summary"]
    assert result.sentiment_score == 68
    assert result.dashboard["core_conclusion"]["one_sentence"] == "短期偏多，逢回调关注。"


def test_schema_fails_when_missing_required_field_analysis_summary():
    analyzer = GeminiAnalyzer(api_key=None)
    payload = _valid_payload()
    payload.pop("analysis_summary")

    with pytest.raises(ValidationError):
        analyzer._validate_analysis_output(payload)


def test_schema_fails_when_sentiment_score_out_of_range():
    analyzer = GeminiAnalyzer(api_key=None)
    payload = _valid_payload()
    payload["sentiment_score"] = 101

    with pytest.raises(ValidationError):
        analyzer._validate_analysis_output(payload)


def test_schema_fails_when_dashboard_core_structure_missing():
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


def test_schema_failure_falls_back_safely_instead_of_silent_success(monkeypatch):
    analyzer = GeminiAnalyzer(api_key=None)
    payload = _valid_payload()
    payload.pop("analysis_summary")

    monkeypatch.setattr(analyzer, "_repair_and_revalidate", lambda _response: None)

    result = analyzer._parse_response(json.dumps(payload, ensure_ascii=False), "CBA.AX", "股票CBA.AX")

    assert result.success is False
    assert result.confidence_level == "低"
    assert result.error_message is not None
    assert "schema 校验失败" in result.error_message
