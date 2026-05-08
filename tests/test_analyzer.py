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


def test_parse_response_accepts_only_top_level_numeric_backtest_levels():
    analyzer = GeminiAnalyzer(api_key=None)
    payload = {
        "stock_name": "必和必拓",
        "sentiment_score": 60,
        "trend_prediction": "震荡",
        "operation_advice": "观望",
        "confidence_level": "中",
        "analysis_summary": "结构化摘要",
        "risk_warning": "注意风险",
        "ideal_buy": 99,
        "secondary_buy": 97.5,
        "stop_loss": 95.0,
        "take_profit": 110.0,
    }

    result = analyzer._parse_response(json.dumps(payload, ensure_ascii=False), "BHP.AX", "必和必拓")

    assert result.ideal_buy == 99.0
    assert result.secondary_buy == 97.5
    assert result.stop_loss == 95.0
    assert result.take_profit == 110.0


def test_parse_response_rejects_non_numeric_backtest_levels_and_dashboard_text():
    analyzer = GeminiAnalyzer(api_key=None)
    payload = {
        "stock_name": "必和必拓",
        "sentiment_score": 60,
        "trend_prediction": "震荡",
        "operation_advice": "观望",
        "confidence_level": "中",
        "analysis_summary": "结构化摘要",
        "risk_warning": "注意风险",
        "ideal_buy": "99.0",
        "secondary_buy": float("nan"),
        "stop_loss": True,
        "take_profit": float("inf"),
        "dashboard": {
            "core_conclusion": {
                "one_sentence": "仅观察",
                "time_sensitivity": "本周内",
                "position_advice": {
                    "no_position": "等待确认",
                    "has_position": "持有观察",
                },
            },
            "data_perspective": {
                "price_position": {
                    "current_vs_ma5": "N/A",
                    "bias_ma5": 0,
                    "bias_status": "安全",
                    "support_level": 95.0,
                    "resistance_level": 110.0,
                },
                "volume_analysis": {
                    "volume_ratio": 1.0,
                    "volume_status": "平量",
                    "turnover_rate": 1.0,
                    "volume_meaning": "N/A",
                },
                "chip_structure": {
                    "profit_ratio": 50,
                    "avg_cost": 100.0,
                    "concentration": 50,
                    "chip_health": "一般",
                },
            },
            "intelligence": {
                "latest_news": "N/A",
                "risk_alerts": [],
                "positive_catalysts": [],
                "earnings_outlook": "N/A",
                "sentiment_summary": "N/A",
            },
            "battle_plan": {
                "sniper_points": {
                    "ideal_buy": "理想买入点：99元",
                    "stop_loss": "止损位：95元",
                    "take_profit": "目标位：110元",
                },
                "position_strategy": {
                    "suggested_position": "轻仓观察",
                    "entry_plan": "等待确认",
                    "risk_control": "跌破95元复核",
                },
                "action_checklist": ["观察"],
            },
        },
    }

    result = analyzer._parse_response(json.dumps(payload, ensure_ascii=False), "BHP.AX", "必和必拓")

    assert result.ideal_buy is None
    assert result.secondary_buy is None
    assert result.stop_loss is None
    assert result.take_profit is None


def test_market_snapshot_carries_structured_technical_levels_for_report_display():
    analyzer = GeminiAnalyzer(api_key=None)

    snapshot = analyzer._build_market_snapshot(
        {
            "date": "2026-05-07",
            "today": {
                "close": 30.85,
                "ma5": 30.31,
                "ma10": 30.02,
                "ma20": 29.76,
            },
            "atr": 0.4213,
        }
    )

    assert snapshot["close"] == "30.85"
    assert snapshot["ma5"] == "30.31"
    assert snapshot["ma10"] == "30.02"
    assert snapshot["ma20"] == "29.76"
    assert snapshot["atr14"] == 0.4213
