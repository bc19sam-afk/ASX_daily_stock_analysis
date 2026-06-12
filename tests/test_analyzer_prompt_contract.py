# -*- coding: utf-8 -*-

from src.config import Config
from src.analyzer import GeminiAnalyzer


def test_system_prompt_defers_final_action_fields_to_deterministic_system():
    prompt = GeminiAnalyzer.SYSTEM_PROMPT

    assert "final_decision" in prompt
    assert "position_action" in prompt
    assert "validation gate" in prompt
    assert "系统确定性动作" in prompt
    assert "不能覆盖" in prompt


def test_system_prompt_marks_operation_advice_as_explanatory_only():
    prompt = GeminiAnalyzer.SYSTEM_PROMPT

    assert "operation_advice" in prompt
    assert "解释性分类" in prompt
    assert "不是最终执行动作" in prompt


def test_system_prompt_blocks_executable_actions_when_gate_blocks_or_data_is_unreliable():
    prompt = GeminiAnalyzer.SYSTEM_PROMPT

    assert "BLOCK" in prompt
    assert "数据质量不足" in prompt
    assert "价格口径不一致" in prompt
    assert "不可决策" in prompt
    assert "仅观察" in prompt


def test_system_prompt_bans_strong_execution_semantics():
    prompt = GeminiAnalyzer.SYSTEM_PROMPT

    assert "禁止输出自动执行语义" in prompt
    for phrase in [
        "立即执行",
        "必须买入",
        "必须卖出",
        "优先执行",
        "直接下单",
        "买入多少股",
        "目标股数",
        "目标仓位",
    ]:
        assert phrase in prompt

    assert "直接告诉用户做什么" not in prompt
    assert "立即行动" not in prompt
    assert "一句话说清该买该卖" not in prompt


def test_system_prompt_requires_conditional_plan_points_with_human_review():
    prompt = GeminiAnalyzer.SYSTEM_PROMPT

    assert "条件化计划点位" in prompt
    for phrase in ["来源", "触发条件", "失效条件", "执行前人工复核"]:
        assert phrase in prompt


def _prompt_with_runtime_risk_config(monkeypatch, tmp_path, max_trade_risk_pct=None):
    env_path = tmp_path / ".env"
    env_path.write_text("STOCK_LIST=BHP.AX\n", encoding="utf-8")

    monkeypatch.setenv("ENV_FILE", str(env_path))
    if max_trade_risk_pct is None:
        monkeypatch.delenv("MAX_TRADE_RISK_PCT", raising=False)
    else:
        monkeypatch.setenv("MAX_TRADE_RISK_PCT", str(max_trade_risk_pct))

    Config.reset_instance()
    try:
        return GeminiAnalyzer(api_key=None)._format_prompt(
            {
                "code": "BHP.AX",
                "date": "2026-04-15",
                "today": {"close": 118.4},
                "execution_price_policy": "close_only",
            },
            "BHP",
        )
    finally:
        Config.reset_instance()


def test_analysis_prompt_uses_default_half_percent_trade_risk_budget(monkeypatch, tmp_path):
    prompt = _prompt_with_runtime_risk_config(monkeypatch, tmp_path)

    assert "单笔交易最大允许亏损为总本金的 0.5%（即 50.0 AUD）" in prompt
    assert "单笔交易最大允许亏损为总本金的 1%" not in prompt


def test_analysis_prompt_uses_configured_one_percent_trade_risk_budget(monkeypatch, tmp_path):
    prompt = _prompt_with_runtime_risk_config(monkeypatch, tmp_path, max_trade_risk_pct=0.01)

    assert "单笔交易最大允许亏损为总本金的 1%（即 100.0 AUD）" in prompt


def test_analysis_prompt_embeds_low_sensitivity_context_pack_summary(monkeypatch, tmp_path):
    prompt = _prompt_with_runtime_risk_config(monkeypatch, tmp_path)

    assert "AnalysisContextPack v1 low-sensitivity summary" in prompt
    assert "Subject: BHP.AX" in prompt
    assert "Market/time/currency: market=ASX; timezone=Australia/Sydney; currency=AUD" in prompt
    assert "daily: status=available; source=today" in prompt
    assert "realtime: status=missing; source=realtime" in prompt
    assert "validation_status=UNAVAILABLE" in prompt
    assert "actionability=pending_validation" in prompt
    assert "deterministic_fields=final_decision, position_action" in prompt
    assert "```json" not in prompt
    assert '"stock_identity"' not in prompt
    assert '"market_snapshot"' not in prompt
    assert "Australia/Sydney" in prompt
    assert "AUD" in prompt


def test_analysis_prompt_uses_verified_backtest_window_without_hardcoded_30_day(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("STOCK_LIST=BHP.AX\n", encoding="utf-8")
    monkeypatch.setenv("ENV_FILE", str(env_path))

    Config.reset_instance()
    try:
        prompt = GeminiAnalyzer(api_key=None)._format_prompt(
            {
                "code": "BHP.AX",
                "date": "2026-04-15",
                "today": {"close": 118.4},
                "execution_price_policy": "close_only",
                "backtest_summary": {
                    "sample_size": 39,
                    "win_rate_pct": 56.67,
                    "eval_window_days": 10,
                },
            },
            "BHP",
        )
    finally:
        Config.reset_instance()

    assert "| 回测窗口 | 10 日 |" in prompt
    assert "30天历史回测胜率" not in prompt
    assert "不得改写为固定 30 天" in prompt
