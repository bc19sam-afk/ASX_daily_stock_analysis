# -*- coding: utf-8 -*-
"""Contract tests for notification recommended-action builders."""

import unittest

from src.analyzer import AnalysisResult
from src.notification import NotificationService
from src.notification_recommended_action_builders import build_recommended_actions_table


class NotificationRecommendedActionBuildersTestCase(unittest.TestCase):
    def _build_service(self) -> NotificationService:
        service = NotificationService.__new__(NotificationService)
        service._report_summary_only = True
        return service

    def _build_result(self, **overrides) -> AnalysisResult:
        base = dict(
            code="600519",
            name="贵州茅台",
            sentiment_score=75,
            trend_prediction="震荡上行",
            operation_advice="区间交易",
            position_action="ADD",
            current_weight=0.12,
            target_weight=0.18,
            delta_amount=3200.0,
            action_reason="趋势确认后分批加仓",
        )
        base.update(overrides)
        return AnalysisResult(**base)

    def test_builder_preserves_markdown_table_contract_and_cell_escaping(self) -> None:
        service = self._build_service()
        result = self._build_result(
            code="BHP.AX",
            name="BHP|Group",
            operation_advice="区间交易|高抛\n低吸",
        )

        lines = build_recommended_actions_table(
            results=[result],
            get_primary_action_model=service._get_primary_action_model,
            get_signal_level=service._get_signal_level,
            format_stock_display_name=service._format_stock_display_name,
            escape_md=service._escape_md,
            to_markdown_table_cell=service._to_markdown_table_cell,
            format_position_action_label=service._format_position_action_label,
            format_sizing_brief=service._format_sizing_brief,
            get_conflict_safe_ai_commentary=service._get_conflict_safe_ai_commentary,
        )

        self.assertEqual(lines[0], "| 标的 | 今日主动作（确定性/未执行） | AI补充（仅参考） |")
        self.assertEqual(lines[1], "|---|---|---|")
        self.assertEqual(
            lines[2],
            "| 🟢 **BHP\\|Group (BHP.AX)** | 加仓 · 中等仓位（约 18%） | 区间交易\\|高抛 低吸 · 评分 75 · 震荡上行 |",
        )

    def test_builder_keeps_final_decision_fallback_and_conflict_marker(self) -> None:
        service = self._build_service()
        result = self._build_result(
            code="BBB",
            position_action="",
            final_decision="HOLD",
            operation_advice="可买入",
        )

        lines = build_recommended_actions_table(
            results=[result],
            get_primary_action_model=service._get_primary_action_model,
            get_signal_level=service._get_signal_level,
            format_stock_display_name=service._format_stock_display_name,
            escape_md=service._escape_md,
            to_markdown_table_cell=service._to_markdown_table_cell,
            format_position_action_label=service._format_position_action_label,
            format_sizing_brief=service._format_sizing_brief,
            get_conflict_safe_ai_commentary=service._get_conflict_safe_ai_commentary,
        )

        self.assertEqual(
            lines[2],
            "| ⚪ **贵州茅台 (BBB)** | 持有观察 · 中等仓位（约 18%） | AI解读与确定性主动作存在方向冲突，已转为中性说明 · 评分 75 · 震荡上行 ⚠️(已抑制冲突态AI操作措辞) |",
        )


if __name__ == "__main__":
    unittest.main()
