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


def test_free_text_indicator_numbers_are_not_rendered_as_prices():
    points = build_conditional_plan_points(
        {
            "ideal_buy": "20日均线支撑",
            "secondary_buy": "回撤5%再观察",
            "stop_loss": "1.5倍ATR止损",
            "take_profit": "RSI 50附近反弹",
        },
        price_basis="close_only",
        technical_basis_date="2026-05-07",
        reference_price=19.8,
    )

    assert [point.price for point in points] == [None, None, None, None]
    assert [point.raw_value for point in points] == [
        "20日均线支撑",
        "回撤5%再观察",
        "1.5倍ATR止损",
        "RSI 50附近反弹",
    ]


def test_free_text_indicator_reference_uses_structured_ma_level_when_available():
    points = build_conditional_plan_points(
        {"ideal_buy": "20日均线支撑"},
        price_basis="close_only",
        technical_basis_date="2026-05-07",
        reference_price=30.85,
        technical_levels={"ma20": 29.76},
    )

    assert len(points) == 1
    assert points[0].price == 29.76
    assert "结构化技术指标：MA20=29.76" in points[0].source_detail


def test_free_text_indicator_reference_prefers_structured_ma_over_ai_price_text():
    points = build_conditional_plan_points(
        {"ideal_buy": "股价回踩MA5（约30.23 AUD）且盘中获得买盘支撑"},
        price_basis="close_only",
        technical_basis_date="2026-05-07",
        reference_price=30.85,
        technical_levels={"ma5": 30.31},
    )

    assert len(points) == 1
    assert points[0].price == 30.31
    assert "结构化技术指标：MA5=30.31" in points[0].source_detail


def test_atr_stop_reference_uses_structured_atr_and_close_when_available():
    points = build_conditional_plan_points(
        {"stop_loss": "1.5倍ATR止损"},
        price_basis="close_only",
        technical_basis_date="2026-05-07",
        reference_price=30.85,
        technical_levels={"atr14": 0.42},
    )

    assert len(points) == 1
    assert points[0].price == 30.22
    assert "昨收30.85 - 1.5×ATR(0.4200)=30.22" in points[0].source_detail


def test_free_text_parser_keeps_actual_price_when_indicator_period_is_present():
    points = build_conditional_plan_points(
        {"ideal_buy": "股价回踩20日均线（约30.23 AUD）且盘中获得买盘支撑"},
        price_basis="close_only",
        technical_basis_date="2026-05-07",
        reference_price=30.85,
    )

    assert len(points) == 1
    assert points[0].price == 30.23


def test_free_text_parser_ignores_budget_amount_but_keeps_explicit_price():
    points = build_conditional_plan_points(
        {"ideal_buy": "买入价5.00 AUD附近观察，单笔亏损严格控制在100 AUD以内"},
        price_basis="close_only",
        technical_basis_date="2026-05-07",
        reference_price=5.2,
    )

    assert len(points) == 1
    assert points[0].price == 5.0


def test_free_text_parser_keeps_nearby_price_before_budget_context():
    points = build_conditional_plan_points(
        {"ideal_buy": "5.00 AUD附近观察，单笔亏损严格控制在100 AUD以内"},
        price_basis="close_only",
        technical_basis_date="2026-05-07",
        reference_price=5.2,
    )

    assert len(points) == 1
    assert points[0].price == 5.0
