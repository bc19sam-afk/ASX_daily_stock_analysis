# -*- coding: utf-8 -*-
"""Pure builders for notification portfolio overview and section C outputs."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Set


logger = logging.getLogger(__name__)


def build_simulated_target_allocation_table(
    *,
    results: List[Any],
    executed_weight_by_code: Optional[Dict[str, float]],
    format_stock_display_name: Callable[[Any, Any], str],
    escape_md: Callable[[str], str],
    to_markdown_table_cell: Callable[[str], str],
    get_signal_level: Callable[[Any], tuple],
    normalize_stock_code: Callable[[Any], str],
) -> List[str]:
    """Build simulated target allocation table; clearly separated from executed state."""
    executed_weight_by_code = executed_weight_by_code or {}
    lines = [
        "| 标的 | 当前已执行权重 | 模拟目标权重 | 模拟调仓金额 |",
        "|---|---:|---:|---:|",
    ]

    for result in results:
        _, signal_emoji, _ = get_signal_level(result)
        display_name = format_stock_display_name(result.name, result.code)
        stock_cell = to_markdown_table_cell(f"{signal_emoji} **{escape_md(display_name)}**")
        lines.append(
            "| "
            f"{stock_cell} | "
            f"{executed_weight_by_code.get(normalize_stock_code(result.code), 0.0):.2%} | "
            f"{getattr(result, 'target_weight', 0.0):.2%} | "
            f"{getattr(result, 'delta_amount', 0.0):,.2f} "
            "|"
        )
    return lines


def build_section_c_reconciliation_lines(
    *,
    results: List[Any],
    overview_holdings: Optional[List[Dict[str, Any]]],
    normalize_stock_code: Callable[[Any], str],
) -> List[str]:
    """Build reconciliation summary so Section C closes to 100% explicitly."""
    holdings = overview_holdings or []
    analyzed_target_weight_sum = sum(float(getattr(result, "target_weight", 0.0) or 0.0) for result in results)
    analyzed_codes = {
        normalize_stock_code(getattr(result, "code", ""))
        for result in results
        if normalize_stock_code(getattr(result, "code", ""))
    }
    unmanaged_holdings_weight = sum(
        float(item.get("weight") or 0.0)
        for item in holdings
        if normalize_stock_code(item.get("code", "")) not in analyzed_codes
    )
    raw_target_cash_weight = 1.0 - analyzed_target_weight_sum - unmanaged_holdings_weight
    target_cash_weight = max(raw_target_cash_weight, 0.0)
    residual = 1.0 - analyzed_target_weight_sum - unmanaged_holdings_weight - target_cash_weight
    tolerance = 1e-6

    lines = [
        "",
        "### C 段闭环说明（为什么目标仓位不一定等于 100%）",
        "",
        f"- 已分析标的目标仓位合计：**{analyzed_target_weight_sum:.2%}**",
        f"- 未纳入今日分析的持仓权重：**{unmanaged_holdings_weight:.2%}**",
        f"- 目标现金权重：**{target_cash_weight:.2%}**",
        f"- 闭环残差：**{residual:.4%}**",
        "- 闭环关系：**已分析标的目标仓位合计 + 未纳入今日分析的持仓权重 + 目标现金权重 + 闭环残差 = 100%**",
    ]
    if abs(residual) <= tolerance:
        lines.append(
            "- 说明：残差在四舍五入/容差范围内，可视为数值舍入带来的极小差异。"
        )
    else:
        lines.append(
            "- 说明：残差超出容差范围，表示仅靠舍入无法完全解释差异，请结合账户与分析覆盖范围进一步核对。"
        )
    return lines


def build_report_time_portfolio_overview(
    *,
    overview: Dict[str, Any],
    results: List[Any],
    normalize_stock_code: Callable[[Any], str],
    to_positive_float: Callable[[Any], Optional[float]],
) -> Dict[str, Any]:
    """Build read-only mark-to-market overview using executed holdings and report-time prices."""
    cash = round(float((overview or {}).get("cash") or 0.0), 2)
    original_holdings = (overview or {}).get("holdings") or []

    report_time_prices: Dict[str, float] = {}
    analyzed_codes: Set[str] = set()
    for result in results or []:
        code = normalize_stock_code(getattr(result, "code", ""))
        if not code:
            continue
        analyzed_codes.add(code)
        price = to_positive_float(getattr(result, "current_price", None))
        if price is not None:
            report_time_prices[code] = price

    holdings: List[Dict[str, Any]] = []
    equity_value = 0.0
    fallback_codes: List[str] = []

    for holding in original_holdings:
        code = normalize_stock_code(holding.get("code", ""))
        quantity = float(holding.get("quantity") or 0.0)
        report_time_price = report_time_prices.get(code)

        if report_time_price is not None:
            market_value = round(max(quantity, 0.0) * report_time_price, 2)
            valuation_source = "report_time_price"
        else:
            market_value = round(float(holding.get("market_value") or 0.0), 2)
            valuation_source = "stored_market_value_fallback"
            if code:
                fallback_codes.append(code)

        equity_value += max(market_value, 0.0)
        holdings.append(
            {
                "code": code,
                "name": holding.get("name"),
                "quantity": quantity,
                "avg_cost": float(holding.get("avg_cost") or 0.0),
                "current_price": report_time_price if report_time_price is not None else holding.get("current_price"),
                "market_value": market_value,
                "valuation_source": valuation_source,
                "analyzed_today": code in analyzed_codes,
            }
        )

    equity_value = round(equity_value, 2)
    total_value = round(cash + equity_value, 2)
    for item in holdings:
        item["weight"] = (item["market_value"] / total_value) if total_value > 0 else 0.0

    if fallback_codes:
        logger.info(
            "Portfolio overview price fallback to stored market_value for holdings without report-time price: %s",
            ",".join(fallback_codes),
        )

    return {
        "snapshot_date": (overview or {}).get("snapshot_date"),
        "cash": cash,
        "equity_value": equity_value,
        "total_value": total_value,
        "holdings": holdings,
    }
