# -*- coding: utf-8 -*-
"""Contract tests for conditional plan point normalization."""

from src.conditional_plan import build_conditional_plan_points


def test_ai_extracted_points_are_observation_only_with_required_conditions():
    points = build_conditional_plan_points(
        {
            "ideal_buy": "10.50",
            "secondary_buy": "10.20",
            "stop_loss": "9.80",
            "take_profit": "11.60",
        },
        price_basis="close_only",
        technical_basis_date="2026-05-04",
    )

    assert [point.label for point in points] == [
        "ideal_buy",
        "secondary_buy",
        "stop_loss",
        "take_profit",
    ]
    assert all(point.requires_manual_review is True for point in points)
    assert all(point.price_basis == "close_only" for point in points)
    assert all(point.technical_basis_date == "2026-05-04" for point in points)
    assert all(point.condition for point in points)
    assert all(point.invalidation for point in points)
    assert all("未验证" in point.source_detail for point in points)
    assert all("仅作观察参考" in point.source_detail for point in points)
    assert all("不作为执行价格" in point.source_detail for point in points)


def test_non_close_only_points_are_explicitly_non_executable_reference():
    points = build_conditional_plan_points(
        {"ideal_buy": "MA10 10.50"},
        price_basis="realtime",
        technical_basis_date="2026-05-04",
    )

    assert len(points) == 1
    assert points[0].source_type == "ma"
    assert points[0].price_basis == "non_executable_reference"


def test_blocked_symbols_do_not_build_displayable_plan_points():
    points = build_conditional_plan_points(
        {"ideal_buy": "10.50", "stop_loss": "9.80"},
        price_basis="close_only",
        technical_basis_date="2026-05-04",
        validation_status="BLOCK",
    )

    assert points == []
