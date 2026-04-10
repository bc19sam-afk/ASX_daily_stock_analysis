# -*- coding: utf-8 -*-
"""Pure builders for dashboard observation appendix rendering."""

from __future__ import annotations

from typing import Dict, List


def build_dashboard_observation_appendix_lines(
    *,
    observation_items: List[Dict[str, str]],
    section_title: str,
    section_intro: str,
) -> List[str]:
    """Render appendix lines from pre-normalized observation display data."""
    if not observation_items:
        return []

    lines = [
        section_title,
        "",
        section_intro,
        "",
    ]

    for item in observation_items:
        lines.extend(
            [
                item["heading"],
                item["summary_line"],
                item["action_line"],
                item["reason_line"],
                item["risk_line"],
                item["reference_line"],
                "",
            ]
        )

    lines.extend(["", "---", ""])
    return lines
