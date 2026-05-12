# -*- coding: utf-8 -*-

from types import SimpleNamespace

import src.stock_analyzer as stock_analyzer_module
from src.analyzer import GeminiAnalyzer
from src.config import Config
from src.stock_analyzer import StockTrendAnalyzer, TrendAnalysisResult, TrendStatus


def _prompt_with_bias_config(
    monkeypatch,
    tmp_path,
    *,
    bias_threshold=None,
    strong_trend_relax_multiplier=None,
):
    env_path = tmp_path / ".env"
    env_path.write_text("STOCK_LIST=BHP.AX\n", encoding="utf-8")

    monkeypatch.setenv("ENV_FILE", str(env_path))
    if bias_threshold is None:
        monkeypatch.delenv("BIAS_THRESHOLD", raising=False)
    else:
        monkeypatch.setenv("BIAS_THRESHOLD", str(bias_threshold))
    if strong_trend_relax_multiplier is None:
        monkeypatch.delenv("BIAS_STRONG_TREND_RELAX_MULTIPLIER", raising=False)
    else:
        monkeypatch.setenv(
            "BIAS_STRONG_TREND_RELAX_MULTIPLIER",
            str(strong_trend_relax_multiplier),
        )

    Config.reset_instance()
    try:
        return GeminiAnalyzer(api_key=None)._format_prompt(
            {
                "code": "BHP.AX",
                "date": "2026-05-12",
                "today": {"close": 118.4},
                "execution_price_policy": "close_only",
            },
            "BHP",
        )
    finally:
        Config.reset_instance()


def test_config_bias_threshold_defaults_to_five_percent_with_configured_relax_multiplier(
    monkeypatch,
    tmp_path,
):
    env_path = tmp_path / ".env"
    env_path.write_text("STOCK_LIST=BHP.AX\n", encoding="utf-8")

    monkeypatch.setenv("ENV_FILE", str(env_path))
    monkeypatch.delenv("BIAS_THRESHOLD", raising=False)
    monkeypatch.delenv("BIAS_STRONG_TREND_RELAX_MULTIPLIER", raising=False)
    Config.reset_instance()
    try:
        config = Config.get_instance()
        assert config.bias_threshold == 5.0
        assert config.bias_strong_trend_relax_multiplier == 1.5
    finally:
        Config.reset_instance()


def test_analyzer_prompt_renders_configured_bias_threshold_policy(monkeypatch, tmp_path):
    prompt = _prompt_with_bias_config(
        monkeypatch,
        tmp_path,
        bias_threshold=6.0,
        strong_trend_relax_multiplier=1.2,
    )

    assert "基础乖离率阈值：6%" in prompt
    assert "强趋势最多按配置倍数 1.2x 放宽至 7.2%" in prompt
    assert "乖离率 < 8% 即可视为安全区间" not in prompt


def test_system_prompt_delegates_bias_threshold_numbers_to_runtime_config():
    prompt = GeminiAnalyzer.SYSTEM_PROMPT

    assert "乖离率 < 8% 即可视为安全区间" not in prompt
    assert "乖离率 <5%" not in prompt
    assert "乖离率 >5%" not in prompt
    assert "乖离率阈值约束" in prompt


def test_stock_analyzer_uses_configured_strong_trend_relax_multiplier(monkeypatch):
    monkeypatch.setattr(
        stock_analyzer_module,
        "get_config",
        lambda: SimpleNamespace(
            bias_threshold=5.0,
            bias_strong_trend_relax_multiplier=1.2,
        ),
    )
    result = TrendAnalysisResult(
        code="BHP.AX",
        trend_status=TrendStatus.STRONG_BULL,
        trend_strength=80,
        bias_ma5=6.4,
    )

    StockTrendAnalyzer()._generate_signal(result)

    joined_risks = "\n".join(result.risk_factors)
    joined_reasons = "\n".join(result.signal_reasons)
    assert "强趋势放宽上限 6%" in joined_risks
    assert "可轻仓追踪" not in joined_reasons


def test_stock_analyzer_reason_discloses_base_and_relaxed_bias_threshold(monkeypatch):
    monkeypatch.setattr(
        stock_analyzer_module,
        "get_config",
        lambda: SimpleNamespace(
            bias_threshold=5.0,
            bias_strong_trend_relax_multiplier=1.5,
        ),
    )
    result = TrendAnalysisResult(
        code="BHP.AX",
        trend_status=TrendStatus.STRONG_BULL,
        trend_strength=80,
        bias_ma5=6.0,
    )

    StockTrendAnalyzer()._generate_signal(result)

    joined_reasons = "\n".join(result.signal_reasons)
    assert "基础阈值 5%" in joined_reasons
    assert "按配置 1.5x 放宽至 7.5%" in joined_reasons
