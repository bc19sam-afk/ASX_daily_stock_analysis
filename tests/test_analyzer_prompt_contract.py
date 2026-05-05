# -*- coding: utf-8 -*-

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
