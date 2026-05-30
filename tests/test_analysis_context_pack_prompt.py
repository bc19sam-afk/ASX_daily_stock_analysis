# -*- coding: utf-8 -*-

from src.analysis_context import build_analysis_context_pack
from src.analysis_context_prompt import format_analysis_context_pack_prompt_section
from src.analyzer import GeminiAnalyzer


SENSITIVE_MARKERS = [
    "api_key",
    "access_token",
    "authorization",
    "webhook",
    "password",
    "cookie",
    "secret",
    "token",
]


def _assert_no_sensitive_markers(text):
    lowered = text.lower()
    for marker in SENSITIVE_MARKERS:
        assert marker not in lowered


def test_prompt_summary_renders_statuses_and_boundaries_without_raw_json_or_values():
    pack = build_analysis_context_pack(
        {
            "code": "BHP.AX",
            "stock_name": "BHP",
            "date": "2026-04-15",
            "execution_price_policy": "close_only",
            "today": {
                "close": 118.4,
                "api_key": "sk-live-raw-value",
                "warning": "authorization header missing from provider",
            },
            "market_overview": {},
            "portfolio_context": {
                "current_weight": 0.22,
                "webhook": "https://hooks.example.test/raw",
            },
            "data_missing": True,
        },
        stock_name="BHP",
        report_date="2026-04-16",
        news_context="Market note with password=letmein",
        validation_status="BLOCK",
        validation_issues=["access_token expired before quote refresh"],
    )

    section = format_analysis_context_pack_prompt_section(pack)

    assert "AnalysisContextPack v1 low-sensitivity summary" in section
    assert "BHP.AX" in section
    assert "ASX" in section
    assert "AUD" in section
    assert "Australia/Sydney" in section
    assert "human-in-the-loop" in section
    assert "daily: status=available; source=today" in section
    assert "market_overview: status=missing; source=market_overview" in section
    assert "news: status=available; source=news_context" in section
    assert "validation_status=BLOCK" in section
    assert "actionability=observation_only" in section
    assert "missing/unavailable evidence is observation-only" in section
    assert "118.4" not in section
    assert "0.22" not in section
    assert "sk-live-raw-value" not in section
    assert "https://hooks.example.test/raw" not in section
    assert "letmein" not in section
    assert "```json" not in section
    assert '"stock_identity"' not in section
    assert '"market_snapshot"' not in section
    _assert_no_sensitive_markers(section)


def test_analyzer_prompt_uses_low_sensitivity_summary_and_keeps_full_pack_in_context():
    context = {
        "code": "BHP.AX",
        "date": "2026-04-15",
        "today": {"close": 118.4, "api_key": "sk-live-raw-value"},
        "execution_price_policy": "close_only",
        "validation_status": "BLOCK",
        "validation_issues": ["secret quote source unavailable"],
        "portfolio_context": {"current_weight": 0.22, "cookie": "raw-cookie-value"},
    }

    prompt = GeminiAnalyzer(api_key=None)._format_prompt(
        context,
        "BHP",
        news_context="news body with access_token=abc123",
    )

    assert "analysis_context_pack" in context
    assert context["analysis_context_pack"]["market_snapshot"]["daily"]["data"]["close"] == 118.4
    assert "AnalysisContextPack v1 low-sensitivity summary" in prompt
    assert "BHP.AX" in prompt
    assert "ASX" in prompt
    assert "AUD" in prompt
    assert "Australia/Sydney" in prompt
    assert "human-in-the-loop" in prompt
    assert "validation_status=BLOCK" in prompt
    assert "actionability=observation_only" in prompt
    assert "```json" not in prompt
    assert '"stock_identity"' not in prompt
    assert '"market_snapshot"' not in prompt
    assert "sk-live-raw-value" not in prompt
    assert "raw-cookie-value" not in prompt
    _assert_no_sensitive_markers(prompt)
