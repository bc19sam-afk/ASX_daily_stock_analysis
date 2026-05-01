# -*- coding: utf-8 -*-

import json

import pytest

from src.analyzer import GeminiAnalyzer


@pytest.mark.parametrize(
    "response_text",
    [
        "强烈买入 buy now，同时也有人说 sell，立即行动。",
        '{"analysis_summary": "强烈买入 buy now sell"',
    ],
)
def test_unparseable_ai_text_degrades_to_hold_without_keyword_decision(response_text):
    analyzer = GeminiAnalyzer(api_key=None)

    result = analyzer._parse_response(response_text, "BHP.AX", "必和必拓")

    assert result.success is True
    assert result.analysis_status == "DEGRADED"
    assert result.decision_type == "hold"
    assert result.operation_advice == "观望"
    assert result.trend_prediction == "震荡"


def test_schema_invalid_json_degrades_without_action_text(monkeypatch):
    analyzer = GeminiAnalyzer(api_key=None)
    payload = {
        "stock_name": "必和必拓",
        "sentiment_score": "not-a-number",
        "trend_prediction": "看多",
        "operation_advice": "强烈买入 buy now",
        "confidence_level": "中",
        "analysis_summary": "结构里混入了 sell 和 buy now 等动作词。",
        "risk_warning": "仅供参考",
    }
    monkeypatch.setattr(analyzer, "_repair_and_revalidate", lambda _response: None)

    result = analyzer._parse_response(json.dumps(payload, ensure_ascii=False), "BHP.AX", "必和必拓")

    assert result.success is True
    assert result.analysis_status == "DEGRADED"
    assert result.sentiment_score == 50
    assert result.decision_type == "hold"
    assert result.operation_advice == "观望"
    assert result.trend_prediction == "震荡"
