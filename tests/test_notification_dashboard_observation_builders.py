# -*- coding: utf-8 -*-
"""Contract tests for dashboard observation appendix builders."""

import unittest

from src.notification_dashboard_observation_builders import (
    build_dashboard_observation_appendix_lines,
)


class NotificationDashboardObservationBuildersTestCase(unittest.TestCase):
    def test_builder_renders_section_and_items_in_stable_order(self) -> None:
        lines = build_dashboard_observation_appendix_lines(
            observation_items=[
                {
                    "heading": "### heading",
                    "summary_line": "- summary",
                    "action_line": "- action",
                    "reason_line": "- reason",
                    "risk_line": "- risk",
                    "reference_line": "- reference",
                }
            ],
            section_title="## section",
            section_intro="> intro",
        )

        self.assertEqual(
            lines,
            [
                "## section",
                "",
                "> intro",
                "",
                "### heading",
                "- summary",
                "- action",
                "- reason",
                "- risk",
                "- reference",
                "",
                "",
                "---",
                "",
            ],
        )

    def test_builder_preserves_pre_normalized_text_without_extra_formatting(self) -> None:
        lines = build_dashboard_observation_appendix_lines(
            observation_items=[
                {
                    "heading": "### item",
                    "summary_line": "- summary | 75 | uptrend",
                    "action_line": "- action: hold",
                    "reason_line": "- reason: wait",
                    "risk_line": "- risk: window near; liquidity thin",
                    "reference_line": "- reference: buy 10.50 | stop 9.80",
                }
            ],
            section_title="## appendix",
            section_intro="> normalized",
        )

        rendered = "\n".join(lines)
        self.assertIn("### item", rendered)
        self.assertIn("- risk: window near; liquidity thin", rendered)
        self.assertIn("- reference: buy 10.50 | stop 9.80", rendered)


if __name__ == "__main__":
    unittest.main()
