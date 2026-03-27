# -*- coding: utf-8 -*-
"""Helpers for GitHub Actions manual portfolio workflows.

This module supports two simple commands:
1) init-portfolio
2) record-trade
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
from typing import Iterable, List

from sqlalchemy import func, select

from src.storage import AccountSnapshot, DatabaseManager, PortfolioPosition, TradeJournal


@dataclass
class HoldingInput:
    code: str
    quantity: float
    avg_cost: float


def _positive_float(raw: str, *, field_name: str, allow_zero: bool = False) -> float:
    value = float(str(raw).strip())
    if allow_zero:
        if value < 0:
            raise ValueError(f"{field_name} must be >= 0")
    elif value <= 0:
        raise ValueError(f"{field_name} must be > 0")
    return value


def _normalize_code(value: str) -> str:
    code = (value or "").strip().upper()
    if not code:
        raise ValueError("code is required")
    return code


def _position_action(before_qty: float, after_qty: float) -> str:
    if before_qty <= 0 < after_qty:
        return "OPEN"
    if before_qty > 0 and after_qty <= 0:
        return "CLOSE"
    if after_qty > before_qty:
        return "ADD"
    if after_qty < before_qty:
        return "REDUCE"
    return "HOLD"


def _count_rows(db: DatabaseManager, model) -> int:
    with db.get_session() as session:
        return int(session.execute(select(func.count(model.id))).scalar() or 0)


def _ensure_not_initialized(db: DatabaseManager) -> None:
    snapshot_count = _count_rows(db, AccountSnapshot)
    position_count = _count_rows(db, PortfolioPosition)
    journal_count = _count_rows(db, TradeJournal)
    if snapshot_count > 0 or position_count > 0 or journal_count > 0:
        raise ValueError(
            "Portfolio already initialized. Init Portfolio is one-time only; "
            "use Record Trade workflow for future updates."
        )


def _parse_holding_rows(args: argparse.Namespace) -> List[HoldingInput]:
    rows: List[HoldingInput] = []
    for idx in range(1, 6):
        code = (getattr(args, f"code_{idx}", "") or "").strip()
        quantity_raw = (getattr(args, f"quantity_{idx}", "") or "").strip()
        avg_cost_raw = (getattr(args, f"avg_cost_{idx}", "") or "").strip()

        if not code and not quantity_raw and not avg_cost_raw:
            continue

        if not code or not quantity_raw or not avg_cost_raw:
            raise ValueError(
                f"Row {idx}: code, quantity, avg_cost must all be filled or all be empty"
            )

        rows.append(
            HoldingInput(
                code=_normalize_code(code),
                quantity=_positive_float(quantity_raw, field_name=f"quantity_{idx}"),
                avg_cost=_positive_float(avg_cost_raw, field_name=f"avg_cost_{idx}"),
            )
        )
    return rows


def init_portfolio(db: DatabaseManager, *, cash: float, holdings: Iterable[HoldingInput]) -> None:
    _ensure_not_initialized(db)

    cash = round(float(cash), 2)
    holdings = list(holdings)
    if not holdings and cash <= 0:
        raise ValueError("Provide positive cash and/or at least one holding")

    equity_value = 0.0
    total_value = cash
    for row in holdings:
        market_value = round(row.quantity * row.avg_cost, 2)
        equity_value += market_value

    total_value = round(cash + equity_value, 2)

    for row in holdings:
        market_value = round(row.quantity * row.avg_cost, 2)
        weight = round((market_value / total_value), 4) if total_value > 0 else 0.0
        db.upsert_portfolio_position(
            code=row.code,
            name=row.code,
            quantity=row.quantity,
            avg_cost=row.avg_cost,
            current_price=row.avg_cost,
            weight=weight,
            market_value=market_value,
        )

    db.save_account_snapshot(
        snapshot_date=date.today(),
        cash=cash,
        equity_value=round(equity_value, 2),
        total_value=total_value,
        note="initialized_by_manual_workflow",
    )


def record_trade(
    db: DatabaseManager,
    *,
    code: str,
    side: str,
    quantity: float,
    price: float,
    fee: float,
) -> None:
    code = _normalize_code(code)
    side = str(side or "").strip().upper()
    if side not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL")

    quantity = _positive_float(str(quantity), field_name="quantity")
    price = _positive_float(str(price), field_name="price")
    fee = _positive_float(str(fee), field_name="fee", allow_zero=True)

    latest = db.get_latest_account_snapshot()
    cash_before = float(latest.cash) if latest else 0.0
    total_before = float(latest.total_value) if latest else 0.0

    existing = db.get_portfolio_position(code)
    before_qty = float(existing.quantity) if existing else 0.0
    before_avg = float(existing.avg_cost) if existing else 0.0
    before_price = float(existing.current_price) if existing and existing.current_price else price
    before_value = round(before_qty * before_price, 2)

    gross_amount = round(quantity * price, 2)

    if side == "BUY":
        cash_change = round(-(gross_amount + fee), 2)
        after_qty = round(before_qty + quantity, 6)
        total_cost = (before_qty * before_avg) + gross_amount + fee
        after_avg = round(total_cost / after_qty, 6) if after_qty > 0 else 0.0
    else:
        if quantity > before_qty:
            raise ValueError(
                f"Cannot SELL {quantity} {code}; current holding is {round(before_qty, 6)}"
            )
        cash_change = round(gross_amount - fee, 2)
        after_qty = round(before_qty - quantity, 6)
        after_avg = 0.0 if after_qty <= 0 else before_avg

    cash_after = round(cash_before + cash_change, 2)
    after_value = round(after_qty * price, 2)

    positions = db.get_portfolio_positions(only_open=True)
    other_equity = round(
        sum(float(p.market_value or 0.0) for p in positions if p.code != code),
        2,
    )
    equity_after = round(other_equity + after_value, 2)
    total_after = round(cash_after + equity_after, 2)

    before_weight = round((before_value / total_before), 4) if total_before > 0 else 0.0
    after_weight = round((after_value / total_after), 4) if total_after > 0 else 0.0

    action = _position_action(before_qty, after_qty)
    db.upsert_portfolio_position(
        code=code,
        name=existing.name if existing and existing.name else code,
        quantity=after_qty,
        avg_cost=after_avg,
        current_price=price,
        weight=after_weight,
        market_value=after_value,
    )

    db.save_trade_journal(
        query_id="manual_trade_workflow",
        code=code,
        action_date=date.today(),
        action=action,
        final_decision=side,
        market_regime="MANUAL",
        event_risk="NA",
        data_quality_flag="MANUAL",
        current_weight=before_weight,
        target_weight=after_weight,
        delta_amount=round(after_value - before_value, 2),
        current_quantity=before_qty,
        target_quantity=after_qty,
        current_price=price,
        available_cash_before=cash_before,
        available_cash_after=cash_after,
        reason=f"manual_{side.lower()} fee={fee}",
    )

    db.save_account_snapshot(
        snapshot_date=date.today(),
        cash=cash_after,
        equity_value=equity_after,
        total_value=total_after,
        note="updated_by_manual_trade_workflow",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manual portfolio workflows")
    sub = parser.add_subparsers(dest="command", required=True)

    init_cmd = sub.add_parser("init-portfolio", help="Initialize holdings and account snapshot")
    init_cmd.add_argument("--cash", required=True)
    for idx in range(1, 6):
        init_cmd.add_argument(f"--code-{idx}", dest=f"code_{idx}", default="")
        init_cmd.add_argument(f"--quantity-{idx}", dest=f"quantity_{idx}", default="")
        init_cmd.add_argument(f"--avg-cost-{idx}", dest=f"avg_cost_{idx}", default="")

    trade_cmd = sub.add_parser("record-trade", help="Record one executed BUY/SELL trade")
    trade_cmd.add_argument("--code", required=True)
    trade_cmd.add_argument("--side", required=True)
    trade_cmd.add_argument("--quantity", required=True)
    trade_cmd.add_argument("--price", required=True)
    trade_cmd.add_argument("--fee", default="0")

    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    db = DatabaseManager.get_instance()

    if args.command == "init-portfolio":
        cash = _positive_float(args.cash, field_name="cash", allow_zero=True)
        holdings = _parse_holding_rows(args)
        init_portfolio(db, cash=cash, holdings=holdings)
        print(f"Initialized portfolio with {len(holdings)} holding(s).")
        return 0

    if args.command == "record-trade":
        record_trade(
            db,
            code=args.code,
            side=args.side,
            quantity=float(args.quantity),
            price=float(args.price),
            fee=float(args.fee),
        )
        print(f"Recorded {args.side.upper()} trade for {args.code.upper()}.")
        return 0

    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
