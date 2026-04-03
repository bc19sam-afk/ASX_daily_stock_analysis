# -*- coding: utf-8 -*-

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any, Dict, Iterable, Mapping, Optional

from sqlalchemy import desc, select

from src.analyzer import AnalysisResult
from src.storage import (
    AccountSnapshot,
    DatabaseManager,
    PaperPortfolioHolding,
    PaperPortfolioSnapshot,
    PaperPortfolioState,
    PaperPortfolioTrade,
    PortfolioPosition,
)


class PaperPortfolioService:
    """paper portfolio v1 service.

    目标：基于当前真实持仓初始化一份独立账本，并按 AnalysisResult 做保守模拟执行。
    """

    SUPPORTED_ACTIONS = {"OPEN", "ADD", "REDUCE", "CLOSE", "HOLD"}

    def __init__(self, db: DatabaseManager):
        self.db = db

    def init_from_current(self, *, force: bool = False) -> Dict[str, Any]:
        with self.db.get_portfolio_write_lock():
            with self.db.get_session() as session:
                self.db.begin_portfolio_write_transaction(session)

                state = session.execute(
                    select(PaperPortfolioState).order_by(desc(PaperPortfolioState.id)).limit(1)
                ).scalar_one_or_none()
                if state and state.initialized and not force:
                    raise ValueError("Paper portfolio already initialized; use force=true to override.")

                real_snapshot = session.execute(
                    select(AccountSnapshot)
                    .order_by(desc(AccountSnapshot.snapshot_date), desc(AccountSnapshot.created_at))
                    .limit(1)
                ).scalar_one_or_none()
                if real_snapshot is None:
                    raise ValueError("Real portfolio is not initialized; cannot seed paper portfolio.")

                real_positions = session.execute(select(PortfolioPosition)).scalars().all()

                session.query(PaperPortfolioHolding).delete()
                session.query(PaperPortfolioTrade).delete()
                session.query(PaperPortfolioSnapshot).delete()

                if state is None:
                    state = PaperPortfolioState(initialized=True)
                    session.add(state)

                state.initialized = True
                state.seeded_from_snapshot_date = real_snapshot.snapshot_date
                state.seeded_from_note = "current_real_portfolio_snapshot"
                state.initialized_at = datetime.now()
                state.last_simulation_time = None

                for pos in real_positions:
                    session.add(
                        PaperPortfolioHolding(
                            code=pos.code,
                            name=pos.name,
                            quantity=float(pos.quantity or 0.0),
                            avg_cost=float(pos.avg_cost or 0.0),
                            current_price=pos.current_price,
                            market_value=float(pos.market_value or 0.0),
                            weight=float(pos.weight or 0.0),
                            status=pos.status or "OPEN",
                            opened_at=pos.opened_at,
                            closed_at=pos.closed_at,
                            updated_at=datetime.now(),
                        )
                    )

                session.add(
                    PaperPortfolioSnapshot(
                        snapshot_date=real_snapshot.snapshot_date,
                        cash=float(real_snapshot.cash or 0.0),
                        equity_value=float(real_snapshot.equity_value or 0.0),
                        total_value=float(real_snapshot.total_value or 0.0),
                        note="seed_from_current_real_portfolio_snapshot",
                        created_at=datetime.now(),
                    )
                )
                session.commit()

        return self.db.get_paper_portfolio_overview()

    def apply_analysis_results(
        self,
        results: Iterable[AnalysisResult | Mapping[str, Any]],
        *,
        simulation_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        sim_time = simulation_time or datetime.now()

        with self.db.get_portfolio_write_lock():
            with self.db.get_session() as session:
                self.db.begin_portfolio_write_transaction(session)

                state = session.execute(
                    select(PaperPortfolioState).order_by(desc(PaperPortfolioState.id)).limit(1)
                ).scalar_one_or_none()
                if not state or not state.initialized:
                    raise ValueError("Paper portfolio is not initialized.")

                latest = self.db.get_latest_paper_snapshot_in_session(session)
                cash = float(latest.cash or 0.0) if latest else 0.0
                working_holdings = self._load_working_holdings_in_session(session)
                pending_trades: list[dict[str, Any]] = []

                for raw in results:
                    payload = raw if isinstance(raw, Mapping) else raw.to_dict()
                    code = str(payload.get("code") or "").upper().strip()
                    if not code:
                        continue

                    action = str(payload.get("position_action") or "HOLD").upper()
                    analysis_status = str(payload.get("analysis_status") or "OK").upper()
                    if action not in self.SUPPORTED_ACTIONS:
                        action = "HOLD"

                    pos = working_holdings.get(
                        code,
                        {
                            "code": code,
                            "name": payload.get("name") or code,
                            "quantity": 0.0,
                            "avg_cost": 0.0,
                            "current_price": None,
                            "market_value": 0.0,
                            "status": "CLOSED",
                        },
                    )
                    is_existing_holding = code in working_holdings
                    before_qty = float(pos.get("quantity") or 0.0)
                    before_avg = float(pos.get("avg_cost") or 0.0)

                    price = self._extract_price(payload)
                    if analysis_status != "OK":
                        pending_trades.append(
                            dict(
                            simulation_time=sim_time,
                            code=code,
                            action=action,
                            analysis_status=analysis_status,
                            executed=False,
                            before_qty=before_qty,
                            after_qty=before_qty,
                            price=price,
                            cash_before=cash,
                            cash_after=cash,
                            reason=f"Skipped: analysis_status={analysis_status}",
                            target_weight=payload.get("target_weight"),
                            target_quantity=payload.get("target_quantity"),
                            )
                        )
                        continue

                    if action == "HOLD":
                        if is_existing_holding and price is not None and math.isfinite(price) and price > 0:
                            pos["current_price"] = price
                            pos["market_value"] = round(before_qty * price, 2)
                            pos["status"] = "OPEN" if before_qty > 0 else "CLOSED"
                        pending_trades.append(
                            dict(
                            simulation_time=sim_time,
                            code=code,
                            action=action,
                            analysis_status=analysis_status,
                            executed=False,
                            before_qty=before_qty,
                            after_qty=before_qty,
                            price=price,
                            cash_before=cash,
                            cash_after=cash,
                            reason="Skipped: HOLD action",
                            target_weight=payload.get("target_weight"),
                            target_quantity=payload.get("target_quantity"),
                            )
                        )
                        continue

                    if price is None or (not math.isfinite(price)) or price <= 0:
                        pending_trades.append(
                            dict(
                            simulation_time=sim_time,
                            code=code,
                            action=action,
                            analysis_status=analysis_status,
                            executed=False,
                            before_qty=before_qty,
                            after_qty=before_qty,
                            price=price,
                            cash_before=cash,
                            cash_after=cash,
                            reason="Skipped: invalid current price",
                            target_weight=payload.get("target_weight"),
                            target_quantity=payload.get("target_quantity"),
                            )
                        )
                        continue

                    target_qty = self._resolve_target_qty(
                        working_holdings=working_holdings,
                        cash=cash,
                        payload=payload,
                        code=code,
                        price=price,
                    )
                    if action == "CLOSE":
                        target_qty = 0.0
                    if target_qty is None:
                        pending_trades.append(
                            dict(
                            simulation_time=sim_time,
                            code=code,
                            action=action,
                            analysis_status=analysis_status,
                            executed=False,
                            before_qty=before_qty,
                            after_qty=before_qty,
                            price=price,
                            cash_before=cash,
                            cash_after=cash,
                            reason="Skipped: missing/invalid target info",
                            target_weight=payload.get("target_weight"),
                            target_quantity=payload.get("target_quantity"),
                            )
                        )
                        continue

                    target_qty = max(float(target_qty), 0.0)
                    if action in {"OPEN", "ADD"} and target_qty <= before_qty:
                        target_qty = before_qty
                    if action == "REDUCE" and target_qty >= before_qty:
                        target_qty = before_qty

                    delta_qty = round(target_qty - before_qty, 6)
                    if abs(delta_qty) <= 1e-9:
                        if is_existing_holding and price is not None and math.isfinite(price) and price > 0:
                            pos["current_price"] = price
                            pos["market_value"] = round(before_qty * price, 2)
                            pos["status"] = "OPEN" if before_qty > 0 else "CLOSED"
                        pending_trades.append(
                            dict(
                            simulation_time=sim_time,
                            code=code,
                            action=action,
                            analysis_status=analysis_status,
                            executed=False,
                            before_qty=before_qty,
                            after_qty=before_qty,
                            price=price,
                            cash_before=cash,
                            cash_after=cash,
                            reason="Skipped: no-op (already at target or clamped to current quantity)",
                            target_weight=payload.get("target_weight"),
                            target_quantity=target_qty,
                            )
                        )
                        continue

                    cash_before = cash
                    if delta_qty > 0:
                        required_cash = round(delta_qty * price, 2)
                        if required_cash > cash_before:
                            pending_trades.append(
                                dict(
                                simulation_time=sim_time,
                                code=code,
                                action=action,
                                analysis_status=analysis_status,
                                executed=False,
                                before_qty=before_qty,
                                after_qty=before_qty,
                                price=price,
                                cash_before=cash_before,
                                cash_after=cash_before,
                                reason=(
                                    "Skipped: insufficient cash for target quantity "
                                    f"(required={required_cash:.2f}, available={cash_before:.2f})"
                                ),
                                target_weight=payload.get("target_weight"),
                                target_quantity=target_qty,
                                )
                            )
                            continue
                        cash -= required_cash
                    elif delta_qty < 0:
                        cash += round(abs(delta_qty) * price, 2)
                    cash = round(cash, 2)

                    after_qty = target_qty
                    if after_qty > 0:
                        if delta_qty > 0:
                            new_cost = before_qty * before_avg + max(delta_qty, 0.0) * price
                            avg_cost = round(new_cost / after_qty, 6)
                        else:
                            avg_cost = before_avg
                        status = "OPEN"
                    else:
                        avg_cost = 0.0
                        status = "CLOSED"

                    pos["name"] = payload.get("name") or pos.get("name") or code
                    pos["quantity"] = after_qty
                    pos["avg_cost"] = avg_cost
                    pos["current_price"] = price
                    pos["market_value"] = round(after_qty * price, 2)
                    pos["status"] = status
                    working_holdings[code] = pos

                    pending_trades.append(
                        dict(
                        simulation_time=sim_time,
                        code=code,
                        action=action,
                        analysis_status=analysis_status,
                        executed=True,
                        before_qty=before_qty,
                        after_qty=after_qty,
                        price=price,
                        cash_before=cash_before,
                        cash_after=cash,
                        reason="Applied",
                        target_weight=payload.get("target_weight"),
                        target_quantity=target_qty,
                        )
                    )

                for item in working_holdings.values():
                    current_price = item.get("current_price")
                    current_price_val: Optional[float]
                    try:
                        current_price_val = float(current_price) if current_price is not None else None
                    except (TypeError, ValueError):
                        current_price_val = None
                    if current_price_val is not None and (not math.isfinite(current_price_val)):
                        current_price_val = None
                    self._upsert_holding(
                        session,
                        code=item["code"],
                        name=item.get("name") or item["code"],
                        quantity=float(item.get("quantity") or 0.0),
                        avg_cost=float(item.get("avg_cost") or 0.0),
                        current_price=current_price_val,
                        market_value=float(item.get("market_value") or 0.0),
                        status=item.get("status") or ("OPEN" if float(item.get("quantity") or 0.0) > 0 else "CLOSED"),
                    )
                for trade_kwargs in pending_trades:
                    self._log_trade(session, **trade_kwargs)
                self._refresh_holdings_weights_and_snapshot(session=session, cash=cash, snapshot_date=sim_time.date())
                state.last_simulation_time = sim_time
                session.commit()

        return self.db.get_paper_portfolio_overview()

    def _resolve_target_qty(
        self,
        *,
        working_holdings: Dict[str, Dict[str, Any]],
        cash: float,
        payload: Mapping[str, Any],
        code: str,
        price: float,
    ) -> Optional[float]:
        target_quantity = payload.get("target_quantity")
        if target_quantity is not None:
            try:
                resolved = float(target_quantity)
            except (TypeError, ValueError):
                return None
            if not math.isfinite(resolved):
                return None
            return resolved

        target_weight = payload.get("target_weight")
        if target_weight is None:
            return None
        try:
            tw = float(target_weight)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(tw):
            return None
        if tw < 0:
            return None
        total_value = self._compute_total_value_in_session(
            working_holdings=working_holdings,
            cash=cash,
            repriced_code=code,
            repriced_price=price,
        )
        if total_value <= 0 or price <= 0:
            return 0.0
        return round((total_value * tw) / price, 6)

    @staticmethod
    def _compute_total_value_in_session(
        *,
        working_holdings: Dict[str, Dict[str, Any]],
        cash: float,
        repriced_code: Optional[str] = None,
        repriced_price: Optional[float] = None,
    ) -> float:
        equity_value = 0.0
        for p in working_holdings.values():
            status = str(p.get("status") or "CLOSED").upper()
            qty = float(p.get("quantity") or 0.0)
            if status != "OPEN" or qty <= 0:
                continue
            if repriced_code and repriced_price is not None and p.get("code") == repriced_code:
                equity_value += round(qty * float(repriced_price), 2)
            else:
                equity_value += float(p.get("market_value") or 0.0)
        equity_value = round(equity_value, 2)
        return round(float(cash) + equity_value, 2)

    @staticmethod
    def _load_working_holdings_in_session(session) -> Dict[str, Dict[str, Any]]:
        rows = session.execute(select(PaperPortfolioHolding)).scalars().all()
        data: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            data[row.code] = {
                "code": row.code,
                "name": row.name or row.code,
                "quantity": float(row.quantity or 0.0),
                "avg_cost": float(row.avg_cost or 0.0),
                "current_price": float(row.current_price) if row.current_price is not None else None,
                "market_value": float(row.market_value or 0.0),
                "status": row.status or ("OPEN" if float(row.quantity or 0.0) > 0 else "CLOSED"),
            }
        return data

    @staticmethod
    def _extract_price(payload: Mapping[str, Any]) -> Optional[float]:
        price = payload.get("current_price")
        if price is not None:
            try:
                return float(price)
            except (TypeError, ValueError):
                pass
        market_snapshot = payload.get("market_snapshot") or {}
        close = market_snapshot.get("close") if isinstance(market_snapshot, Mapping) else None
        if close is None:
            return None
        try:
            return float(close)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _log_trade(
        session,
        *,
        simulation_time: datetime,
        code: str,
        action: str,
        analysis_status: str,
        executed: bool,
        before_qty: float,
        after_qty: float,
        price: Optional[float],
        cash_before: float,
        cash_after: float,
        reason: str,
        target_weight: Optional[float],
        target_quantity: Optional[float],
    ) -> None:
        safe_target_weight = PaperPortfolioService._safe_to_float(target_weight)
        safe_target_quantity = PaperPortfolioService._safe_to_float(target_quantity)
        session.add(
            PaperPortfolioTrade(
                simulation_time=simulation_time,
                code=code,
                action=action,
                analysis_status=analysis_status,
                executed=executed,
                target_weight=safe_target_weight,
                target_quantity=safe_target_quantity,
                before_quantity=before_qty,
                after_quantity=after_qty,
                price=price,
                cash_before=cash_before,
                cash_after=cash_after,
                reason=reason,
                created_at=datetime.now(),
            )
        )

    @staticmethod
    def _safe_to_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(parsed):
            return None
        return parsed

    @staticmethod
    def _upsert_holding(
        session,
        *,
        code: str,
        name: str,
        quantity: float,
        avg_cost: float,
        current_price: Optional[float],
        market_value: Optional[float] = None,
        status: str,
    ) -> None:
        session.flush()
        row = session.execute(
            select(PaperPortfolioHolding).where(PaperPortfolioHolding.code == code).limit(1)
        ).scalar_one_or_none()
        now = datetime.now()
        if market_value is None:
            if current_price is None:
                market_value_val = round(float(row.market_value or 0.0), 2) if row is not None else 0.0
            else:
                market_value_val = round(max(quantity, 0.0) * current_price, 2)
        else:
            market_value_val = round(float(market_value), 2)
        if row is None:
            row = PaperPortfolioHolding(
                code=code,
                name=name,
                quantity=max(quantity, 0.0),
                avg_cost=max(avg_cost, 0.0),
                current_price=current_price,
                market_value=market_value_val,
                weight=0.0,
                status=status,
                opened_at=now if quantity > 0 else None,
                closed_at=now if quantity <= 0 else None,
                updated_at=now,
            )
            session.add(row)
            return

        row.name = name or row.name
        row.quantity = max(quantity, 0.0)
        row.avg_cost = max(avg_cost, 0.0) if quantity > 0 else 0.0
        row.current_price = current_price
        row.market_value = market_value_val
        row.status = status
        if quantity > 0:
            row.closed_at = None
            if row.opened_at is None:
                row.opened_at = now
        else:
            if row.closed_at is None:
                row.closed_at = now
        row.updated_at = now

    def _refresh_holdings_weights_and_snapshot(self, *, session, cash: float, snapshot_date: date) -> None:
        session.flush()
        open_positions = session.execute(
            select(PaperPortfolioHolding).where(PaperPortfolioHolding.status == "OPEN")
        ).scalars().all()
        equity_value = round(sum(float(p.market_value or 0.0) for p in open_positions), 2)
        total_value = round(cash + equity_value, 2)
        for row in open_positions:
            mv = float(row.market_value or 0.0)
            row.weight = round(mv / total_value, 6) if total_value > 0 else 0.0

        snapshot = session.execute(
            select(PaperPortfolioSnapshot).where(PaperPortfolioSnapshot.snapshot_date == snapshot_date).limit(1)
        ).scalar_one_or_none()
        if snapshot is None:
            snapshot = PaperPortfolioSnapshot(snapshot_date=snapshot_date, created_at=datetime.now())
            session.add(snapshot)
        snapshot.cash = round(cash, 2)
        snapshot.equity_value = equity_value
        snapshot.total_value = total_value
        snapshot.note = "paper_simulation"
