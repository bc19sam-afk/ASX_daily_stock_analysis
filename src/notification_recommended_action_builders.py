# -*- coding: utf-8 -*-
"""Pure builders for notification recommended-action tables."""

from __future__ import annotations

from typing import Any, Callable, Dict, List


def build_recommended_actions_table(
    *,
    results: List[Any],
    get_primary_action_model: Callable[[Any], Dict[str, Any]],
    get_signal_level: Callable[[Any], tuple],
    format_stock_display_name: Callable[[Any, Any], str],
    escape_md: Callable[[str], str],
    to_markdown_table_cell: Callable[[Any], str],
    format_position_action_label: Callable[[str], str],
    format_sizing_brief: Callable[[float, str], str],
    get_conflict_safe_ai_commentary: Callable[[Any], str],
) -> List[str]:
    """Build recommended actions table (analysis output; not yet executed)."""
    lines = [
        "| 标的 | 今日主动作（确定性/未执行） | AI补充（仅参考） |",
        "|---|---|---|",
    ]

    for result in results:
        action_model = get_primary_action_model(result)
        _, signal_emoji, _ = get_signal_level(result)
        display_name = format_stock_display_name(result.name, result.code)
        stock_cell = to_markdown_table_cell(f"{signal_emoji} **{escape_md(display_name)}**")
        action_cell = to_markdown_table_cell(
            f"{format_position_action_label(action_model['position_action'])} · "
            f"{format_sizing_brief(action_model['target_weight'], action_model['position_action'])}"
        )
        ai_view_text = (
            f"{get_conflict_safe_ai_commentary(result)} · "
            f"评分 {result.sentiment_score} · {result.trend_prediction}"
        )
        if action_model["ai_conflict"]:
            ai_view_text += " ⚠️(已抑制冲突态AI操作措辞)"
        ai_view_cell = to_markdown_table_cell(ai_view_text)

        lines.append(
            "| "
            f"{stock_cell} | "
            f"{action_cell} | "
            f"{ai_view_cell} "
            "|"
        )
    return lines
