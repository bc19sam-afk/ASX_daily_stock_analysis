# -*- coding: utf-8 -*-
"""Helpers for GitHub Actions manual portfolio workflows.

This module supports two simple commands:
1) init-portfolio
2) record-trade
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime
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


def _count_rows_in_session(session, model) -> int:
    return int(session.execute(select(func.count(model.id))).scalar() or 0)


def _ensure_not_initialized_in_session(session) -> None:
    snapshot_count = _count_rows_in_session(session, AccountSnapshot)
    position_count = _count_rows_in_session(session, PortfolioPosition)
    journal_count = _count_rows_in_session(session, TradeJournal)
    if snapshot_count > 0 or position_count > 0 or journal_count > 0:
        raise ValueError(
            "Portfolio already initialized. Init Portfolio is one-time only; "
            "use Record Trade workflow for future updates."
        )


def _ensure_initialized_in_session(session) -> None:
    snapshot_count = _count_rows_in_session(session, AccountSnapshot)
    position_count = _count_rows_in_session(session, PortfolioPosition)
    if snapshot_count <= 0 and position_count <= 0:
        raise ValueError(
            "Portfolio is not initialized yet. Please run Init Portfolio workflow first."
        )


def _upsert_position_in_session(
    session,
    *,
    code: str,
    name: str,
    quantity: float,
    avg_cost: float,
    current_price: float,
    weight: float,
    market_value: float,
) -> None:
    now = datetime.now()
    row = session.execute(
        select(PortfolioPosition).where(PortfolioPosition.code == code).limit(1)
    ).scalar_one_or_none()

    if row is None:
        row = PortfolioPosition(
            code=code,
            name=name,
            quantity=max(float(quantity), 0.0),
            avg_cost=max(float(avg_cost), 0.0),
            current_price=current_price,
            weight=max(float(weight), 0.0),
            market_value=max(float(market_value), 0.0),
            unrealized_pnl=None,
            status="OPEN" if quantity > 0 else "CLOSED",
            opened_at=now if quantity > 0 else None,
            closed_at=None if quantity > 0 else now,
            updated_at=now,
        )
        session.add(row)
        return

    prev_qty = float(row.quantity or 0.0)
    row.name = name or row.name
    row.quantity = max(float(quantity), 0.0)
    row.avg_cost = max(float(avg_cost), 0.0) if quantity > 0 else 0.0
    row.current_price = current_price
    row.weight = max(float(weight), 0.0)
    row.market_value = max(float(market_value), 0.0)
    if row.quantity > 0:
        row.status = "OPEN"
        row.closed_at = None
        if row.opened_at is None and prev_qty <= 0:
            row.opened_at = now
    else:
        row.status = "CLOSED"
        if row.closed_at is None:
            row.closed_at = now
    row.updated_at = now


def _upsert_snapshot_in_session(
    session,
    *,
    snapshot_date: date,
    cash: float,
    equity_value: float,
    total_value: float,
    note: str,
) -> None:
    row = session.execute(
        select(AccountSnapshot).where(AccountSnapshot.snapshot_date == snapshot_date).limit(1)
    ).scalar_one_or_none()
    if row is None:
        row = AccountSnapshot(
            snapshot_date=snapshot_date,
            cash=float(cash),
            equity_value=float(equity_value),
            total_value=float(total_value),
            note=note,
            created_at=datetime.now(),
        )
        session.add(row)
        return

    row.cash = float(cash)
    row.equity_value = float(equity_value)
    row.total_value = float(total_value)
    row.note = note


def _parse_holding_rows(args: argparse.Namespace) -> List[HoldingInput]:
    rows: List[HoldingInput] = []
    seen_codes = set()
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

        normalized_code = _normalize_code(code)
        if normalized_code in seen_codes:
            raise ValueError(f"Duplicate code detected in Init Portfolio rows: {normalized_code}")
        seen_codes.add(normalized_code)

        rows.append(
            HoldingInput(
                code=normalized_code,
                quantity=_positive_float(quantity_raw, field_name=f"quantity_{idx}"),
                avg_cost=_positive_float(avg_cost_raw, field_name=f"avg_cost_{idx}"),
            )
        )
    return rows


def init_portfolio(db: DatabaseManager, *, cash: float, holdings: Iterable[HoldingInput]) -> None:
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

    with db.get_session() as session:
        _ensure_not_initialized_in_session(session)

        for row in holdings:
            market_value = round(row.quantity * row.avg_cost, 2)
            weight = round((market_value / total_value), 4) if total_value > 0 else 0.0
            _upsert_position_in_session(
                session,
                code=row.code,
                name=row.code,
                quantity=row.quantity,
                avg_cost=row.avg_cost,
                current_price=row.avg_cost,
                weight=weight,
                market_value=market_value,
            )

        _upsert_snapshot_in_session(
            session,
            snapshot_date=date.today(),
            cash=cash,
            equity_value=round(equity_value, 2),
            total_value=total_value,
            note="initialized_by_manual_workflow",
        )
        session.commit()


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

    with db.get_session() as session:
        _ensure_initialized_in_session(session)

        latest = session.execute(
            select(AccountSnapshot)
            .order_by(AccountSnapshot.snapshot_date.desc(), AccountSnapshot.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        cash_before = float(latest.cash) if latest else 0.0
        total_before = float(latest.total_value) if latest else 0.0

        existing = session.execute(
            select(PortfolioPosition).where(PortfolioPosition.code == code).limit(1)
        ).scalar_one_or_none()
        before_qty = float(existing.quantity) if existing else 0.0
        before_avg = float(existing.avg_cost) if existing else 0.0
        before_price = float(existing.current_price) if existing and existing.current_price else price
        before_value = round(before_qty * before_price, 2)

        gross_amount = round(quantity * price, 2)

        if side == "BUY":
            required_cash = round(gross_amount + fee, 2)
            if required_cash > cash_before:
                raise ValueError(
                    "BUY rejected: insufficient cash. "
                    f"Required {required_cash:.2f} (quantity × price + fee), "
                    f"but available cash is {cash_before:.2f}. "
                    "Please reduce quantity/price, or add cash first."
                )
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

        open_positions = session.execute(
            select(PortfolioPosition).where(PortfolioPosition.status == "OPEN")
        ).scalars().all()
        other_equity = round(
            sum(float(p.market_value or 0.0) for p in open_positions if p.code != code),
            2,
        )
        equity_after = round(other_equity + after_value, 2)
        total_after = round(cash_after + equity_after, 2)

        before_weight = round((before_value / total_before), 4) if total_before > 0 else 0.0
        after_weight = round((after_value / total_after), 4) if total_after > 0 else 0.0

        action = _position_action(before_qty, after_qty)
        _upsert_position_in_session(
            session,
            code=code,
            name=existing.name if existing and existing.name else code,
            quantity=after_qty,
            avg_cost=after_avg,
            current_price=price,
            weight=after_weight,
            market_value=after_value,
        )

        session.add(
            TradeJournal(
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
                created_at=datetime.now(),
            )
        )

        _upsert_snapshot_in_session(
            session,
            snapshot_date=date.today(),
            cash=cash_after,
            equity_value=equity_after,
            total_value=total_after,
            note="updated_by_manual_trade_workflow",
        )

        integrity = db.check_portfolio_account_integrity(session=session, journal_code=code)
        if not integrity["is_valid"]:
            detail = "; ".join(integrity["errors"])
            raise ValueError(f"Manual trade aborted by integrity check: {detail}")

        session.commit()


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
