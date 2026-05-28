# -*- coding: utf-8 -*-
"""Read-only preview and explicit apply support for ASX portfolio CSV imports."""

from __future__ import annotations

import csv
import io
import logging
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import desc, select

from src.stock_code import canonical_stock_code
from src.storage import AccountSnapshot, DatabaseManager, PortfolioPosition

logger = logging.getLogger(__name__)


REQUIRED_COLUMNS = {
    "trade_date",
    "settlement_date",
    "code",
    "side",
    "quantity",
    "price",
    "currency",
    "broker",
    "account_label",
}

FEE_COLUMNS = ("brokerage", "fees", "fee", "brokerage_fees")
HIN_COLUMNS = ("hin", "custody", "custody_metadata", "account_hin", "custody_reference")
DIVIDEND_COLUMNS = ("dividend", "dividend_amount")
FRANKING_COLUMNS = ("franking", "franking_credit", "franking_credit_amount")


def _normalize_header(value: str) -> str:
    return (
        str(value or "")
        .strip()
        .lower()
        .replace("/", "_")
        .replace("-", "_")
        .replace(" ", "_")
    )


def _parse_date(raw: str, *, field_name: str) -> date:
    value = str(raw or "").strip()
    if not value:
        raise ValueError(f"{field_name} is required")
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD") from exc


def _parse_float(raw: str, *, field_name: str, allow_zero: bool = False) -> float:
    try:
        value = float(str(raw or "").replace(",", "").strip())
    except ValueError as exc:
        raise ValueError(f"{field_name} must be numeric") from exc
    if allow_zero:
        if value < 0:
            raise ValueError(f"{field_name} must be >= 0")
    elif value <= 0:
        raise ValueError(f"{field_name} must be > 0")
    return round(value, 6)


def _first_value(row: Dict[str, str], keys: Iterable[str]) -> str:
    for key in keys:
        value = str(row.get(key, "")).strip()
        if value:
            return value
    return ""


def _normalize_asx_code(raw: str) -> str:
    code = str(raw or "").strip().upper()
    if not code:
        raise ValueError("code is required")
    if code.endswith(".ASX"):
        code = f"{code[:-4]}.AX"
    elif "." not in code:
        code = f"{code}.AX"
    if not code.endswith(".AX"):
        raise ValueError("code must normalize to an ASX .AX symbol")
    return canonical_stock_code(code)


@dataclass
class ImportedTradeRow:
    line_number: int
    trade_date: Optional[date]
    settlement_date: Optional[date]
    code: str
    side: str
    quantity: float
    price: float
    fee: float
    currency: str
    broker: str
    account_label: str
    custody_metadata: str = ""
    dividend: Optional[float] = None
    franking_credit: Optional[float] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def gross_amount(self) -> float:
        return round(self.quantity * self.price, 2)

    @property
    def has_reserved_fields(self) -> bool:
        return self.dividend is not None or self.franking_credit is not None

    def to_preview_dict(self) -> Dict[str, Any]:
        return {
            "line_number": self.line_number,
            "trade_date": self.trade_date.isoformat() if self.trade_date else None,
            "settlement_date": self.settlement_date.isoformat() if self.settlement_date else None,
            "code": self.code,
            "side": self.side,
            "quantity": self.quantity,
            "price": self.price,
            "fee": self.fee,
            "currency": self.currency,
            "broker": self.broker,
            "account_label": self.account_label,
            "custody_metadata": self.custody_metadata or None,
            "dividend": self.dividend,
            "franking_credit": self.franking_credit,
            "gross_amount": self.gross_amount,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


@dataclass
class LedgerPositionState:
    code: str
    name: str
    quantity: float = 0.0
    avg_cost: float = 0.0
    current_price: Optional[float] = None
    market_value: float = 0.0
    weight: float = 0.0
    status: str = "CLOSED"
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None

    @classmethod
    def from_model(cls, row: PortfolioPosition) -> "LedgerPositionState":
        return cls(
            code=canonical_stock_code(row.code),
            name=row.name or canonical_stock_code(row.code),
            quantity=float(row.quantity or 0.0),
            avg_cost=float(row.avg_cost or 0.0),
            current_price=row.current_price,
            market_value=float(row.market_value or 0.0),
            weight=float(row.weight or 0.0),
            status=str(row.status or "CLOSED").upper(),
            opened_at=row.opened_at,
            closed_at=row.closed_at,
        )

    def to_model_kwargs(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "quantity": self.quantity,
            "avg_cost": self.avg_cost,
            "current_price": self.current_price,
            "weight": self.weight,
            "market_value": self.market_value,
        }


@dataclass
class LedgerState:
    cash: float
    positions: Dict[str, LedgerPositionState]
    snapshot_date: Optional[date]

    @classmethod
    def from_session(cls, session) -> "LedgerState":
        latest = session.execute(
            select(AccountSnapshot)
            .order_by(desc(AccountSnapshot.snapshot_date), desc(AccountSnapshot.created_at))
            .limit(1)
        ).scalar_one_or_none()
        if latest is None:
            raise ValueError(
                "Portfolio is not initialized yet. Please run Init Portfolio workflow first."
            )
        positions = {
            canonical_stock_code(row.code): LedgerPositionState.from_model(row)
            for row in session.execute(select(PortfolioPosition)).scalars().all()
        }
        return cls(
            cash=round(float(latest.cash or 0.0), 2),
            positions=positions,
            snapshot_date=latest.snapshot_date,
        )

    @property
    def equity_value(self) -> float:
        return round(
            sum(float(position.market_value or 0.0) for position in self.positions.values() if position.status == "OPEN"),
            2,
        )

    @property
    def total_value(self) -> float:
        return round(self.cash + self.equity_value, 2)

    def open_positions(self) -> List[LedgerPositionState]:
        return [position for position in self.positions.values() if position.status == "OPEN"]

    def get_or_create_position(self, code: str, *, fallback_name: Optional[str] = None) -> LedgerPositionState:
        position = self.positions.get(code)
        if position is None:
            position = LedgerPositionState(code=code, name=fallback_name or code)
            self.positions[code] = position
        return position

    def recompute_weights(self) -> None:
        total = self.total_value
        for position in self.positions.values():
            if position.status != "OPEN" or total <= 0:
                position.weight = 0.0
                continue
            position.weight = round(float(position.market_value or 0.0) / total, 6)

    def clone(self) -> "LedgerState":
        return LedgerState(
            cash=self.cash,
            positions={code: deepcopy(position) for code, position in self.positions.items()},
            snapshot_date=self.snapshot_date,
        )


class AsxPortfolioImportService:
    """Parse, preview, and optionally apply ASX portfolio trade CSV rows."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    def preview_csv(self, csv_path: str | Path) -> Dict[str, Any]:
        return self._run(csv_path=csv_path, apply=False)

    def apply_csv(self, csv_path: str | Path) -> Dict[str, Any]:
        return self._run(csv_path=csv_path, apply=True)

    def _run(self, *, csv_path: str | Path, apply: bool) -> Dict[str, Any]:
        path = Path(csv_path)
        rows, parse_errors, parse_warnings = self._parse_rows(path)

        base_result = {
            "source_path": str(path),
            "row_count": len(rows),
            "valid_row_count": sum(1 for row in rows if not row.errors),
            "invalid_row_count": sum(1 for row in rows if row.errors),
            "rows": [row.to_preview_dict() for row in rows],
            "warnings": parse_warnings + [warning for row in rows for warning in row.warnings],
            "errors": parse_errors + [error for row in rows for error in row.errors],
            "totals": self._build_totals(rows),
            "can_apply": False,
            "status": "preview" if not apply else "invalid",
            "applied_count": 0,
            "integrity": {"is_valid": False, "errors": [], "warnings": []},
        }

        if base_result["errors"]:
            base_result["status"] = "invalid"
            return base_result

        try:
            state = self._load_state()
        except ValueError as exc:
            base_result["errors"].append(str(exc))
            return base_result

        try:
            simulated_state, simulation_rows, integrity_hint = self._simulate_rows(state.clone(), rows)
        except Exception as exc:
            return {
                **base_result,
                "status": "invalid",
                "errors": base_result["errors"] + [str(exc)],
            }
        base_result["rows"] = simulation_rows
        base_result["totals"] = self._build_totals(rows, state=state, simulated_state=simulated_state)
        base_result["can_apply"] = True
        base_result["warnings"] = self._dedupe_strings(base_result["warnings"] + integrity_hint["warnings"])

        if not apply:
            base_result["status"] = "preview"
            return base_result

        try:
            integrity = self._apply_rows(rows)
        except Exception as exc:
            logger.warning("ASX CSV import failed: %s", exc)
            return {
                **base_result,
                "status": "invalid",
                "errors": base_result["errors"] + [str(exc)],
                "integrity": {"is_valid": False, "errors": [str(exc)], "warnings": []},
            }

        return {
            **base_result,
            "status": "applied",
            "applied_count": len(rows),
            "integrity": integrity,
        }

    def _parse_rows(self, path: Path) -> Tuple[List[ImportedTradeRow], List[str], List[str]]:
        if not path.exists():
            raise FileNotFoundError(f"CSV file not found: {path}")

        raw_text = path.read_text(encoding="utf-8-sig")
        reader = csv.DictReader(io.StringIO(raw_text))
        if not reader.fieldnames:
            return [], ["CSV header row is missing"], []

        normalized_headers = [_normalize_header(field) for field in reader.fieldnames]
        header_map = {
            normalized_headers[index]: reader.fieldnames[index]
            for index in range(len(reader.fieldnames))
        }
        missing_required = sorted(
            column for column in REQUIRED_COLUMNS if column not in header_map
        )
        fee_header_present = any(alias in header_map for alias in FEE_COLUMNS)
        if missing_required:
            errors = [f"Missing required column: {column}" for column in missing_required]
            return [], errors, []
        if not fee_header_present:
            # Fee column is allowed to be blank but should exist in the schema so imports stay explicit.
            return [], ["Missing required fee column: brokerage / fees"], []

        rows: List[ImportedTradeRow] = []
        warnings: List[str] = []
        for line_number, raw_row in enumerate(reader, start=2):
            normalized_row = {
                _normalize_header(key): str(value or "").strip()
                for key, value in raw_row.items()
            }
            row = self._parse_row(normalized_row, line_number=line_number)
            rows.append(row)
            warnings.extend(row.warnings)
        return rows, [], self._dedupe_strings(warnings)

    def _parse_row(self, row: Dict[str, str], *, line_number: int) -> ImportedTradeRow:
        errors: List[str] = []
        warnings: List[str] = []

        trade_date: Optional[date] = None
        try:
            trade_date = _parse_date(row.get("trade_date", ""), field_name="trade_date")
        except ValueError as exc:
            errors.append(f"line {line_number}: {exc}")

        settlement_date: Optional[date] = None
        try:
            settlement_date = _parse_date(row.get("settlement_date", ""), field_name="settlement_date")
        except ValueError as exc:
            errors.append(f"line {line_number}: {exc}")

        if trade_date and settlement_date and settlement_date < trade_date:
            warnings.append(
                f"line {line_number}: settlement_date is earlier than trade_date; keeping imported values as-is"
            )

        code = ""
        try:
            code = _normalize_asx_code(row.get("code", ""))
        except ValueError as exc:
            errors.append(f"line {line_number}: {exc}")

        side_raw = str(row.get("side", "")).strip().upper()
        side = {"B": "BUY", "S": "SELL"}.get(side_raw, side_raw)
        if side not in {"BUY", "SELL"}:
            errors.append(f"line {line_number}: side must be BUY or SELL")

        quantity = 0.0
        try:
            quantity = _parse_float(row.get("quantity", ""), field_name="quantity")
        except ValueError as exc:
            errors.append(f"line {line_number}: {exc}")

        price = 0.0
        try:
            price = _parse_float(row.get("price", ""), field_name="price")
        except ValueError as exc:
            errors.append(f"line {line_number}: {exc}")

        currency = str(row.get("currency", "")).strip().upper()
        if not currency:
            errors.append(f"line {line_number}: currency is required")
        elif currency != "AUD":
            errors.append(f"line {line_number}: currency must be AUD for ASX imports")

        broker = str(row.get("broker", "")).strip()
        if not broker:
            errors.append(f"line {line_number}: broker is required")

        account_label = str(row.get("account_label", "")).strip()
        if not account_label:
            errors.append(f"line {line_number}: account_label is required")

        fee_raw = _first_value(row, FEE_COLUMNS)
        fee = 0.0
        if fee_raw:
            try:
                fee = _parse_float(fee_raw, field_name="fee", allow_zero=True)
            except ValueError as exc:
                errors.append(f"line {line_number}: {exc}")
        else:
            warnings.append(f"line {line_number}: brokerage/fees missing; assuming 0.00")

        custody_metadata = _first_value(row, HIN_COLUMNS)
        dividend_value = _first_value(row, DIVIDEND_COLUMNS)
        franking_value = _first_value(row, FRANKING_COLUMNS)
        dividend = None
        if dividend_value:
            try:
                dividend = _parse_float(dividend_value, field_name="dividend", allow_zero=True)
            except ValueError as exc:
                errors.append(f"line {line_number}: {exc}")

        franking_credit = None
        if franking_value:
            try:
                franking_credit = _parse_float(franking_value, field_name="franking_credit", allow_zero=True)
            except ValueError as exc:
                errors.append(f"line {line_number}: {exc}")
        if dividend is not None or franking_credit is not None:
            warnings.append(
                f"line {line_number}: dividend/franking fields are reserved in v1 and are not applied to cash"
            )

        if not errors and quantity <= 0:
            errors.append(f"line {line_number}: quantity must be > 0")
        if not errors and price <= 0:
            errors.append(f"line {line_number}: price must be > 0")

        return ImportedTradeRow(
            line_number=line_number,
            trade_date=trade_date,
            settlement_date=settlement_date,
            code=code,
            side=side,
            quantity=quantity,
            price=price,
            fee=fee,
            currency=currency or "AUD",
            broker=broker,
            account_label=account_label,
            custody_metadata=custody_metadata,
            dividend=dividend,
            franking_credit=franking_credit,
            warnings=self._dedupe_strings(warnings),
            errors=self._dedupe_strings(errors),
        )

    def _load_state(self) -> LedgerState:
        with self.db.get_session() as session:
            return LedgerState.from_session(session)

    def _simulate_rows(
        self,
        state: LedgerState,
        rows: List[ImportedTradeRow],
    ) -> Tuple[LedgerState, List[Dict[str, Any]], Dict[str, List[str]]]:
        simulated_rows: List[Dict[str, Any]] = []
        warnings: List[str] = []
        for row in sorted(rows, key=lambda item: (item.trade_date, item.settlement_date, item.line_number)):
            row_result, _ = self._apply_trade(state, row, write=False)
            simulated_rows.append(row_result)
            warnings.extend(row_result.get("warnings", []))
        return state, simulated_rows, {"warnings": self._dedupe_strings(warnings)}

    def _apply_rows(self, rows: List[ImportedTradeRow]) -> Dict[str, Any]:
        with self.db.get_portfolio_write_lock():
            with self.db.get_session() as session:
                self.db.begin_portfolio_write_transaction(session)
                state = LedgerState.from_session(session)
                applied_rows: List[Dict[str, Any]] = []
                for row in sorted(rows, key=lambda item: (item.trade_date, item.settlement_date, item.line_number)):
                    row_result, _ = self._apply_trade(state, row, write=True, session=session)
                    applied_rows.append(row_result)

                integrity = self.db.check_portfolio_account_integrity(session=session)
                if not integrity["is_valid"]:
                    detail = "; ".join(integrity["errors"])
                    raise ValueError(f"Import aborted by integrity check: {detail}")

                session.commit()
                return integrity

    def _apply_trade(
        self,
        state: LedgerState,
        row: ImportedTradeRow,
        *,
        write: bool,
        session=None,
    ) -> Tuple[Dict[str, Any], LedgerState]:
        trade_date = row.trade_date or date.min
        settlement_date = row.settlement_date or trade_date
        position = state.get_or_create_position(row.code)
        cash_before = state.cash
        if position.status == "OPEN":
            before_qty = float(position.quantity or 0.0)
            before_avg = float(position.avg_cost or 0.0)
            before_price = float(position.current_price or row.price)
            before_value = round(before_qty * before_price, 2)
        else:
            before_qty = 0.0
            before_avg = 0.0
            before_price = row.price
            before_value = 0.0

        total_before = state.total_value
        current_weight = round(before_value / total_before, 6) if total_before > 0 else 0.0
        equity_before = state.equity_value

        if row.side == "BUY":
            required_cash = round(row.gross_amount + row.fee, 2)
            if state.cash + 1e-9 < required_cash:
                raise ValueError(
                    f"line {row.line_number}: BUY rejected because cash would go negative "
                    f"(required {required_cash:.2f}, available {state.cash:.2f})"
                )
            cash_after = round(state.cash - required_cash, 2)
            after_qty = round(before_qty + row.quantity, 6)
            total_cost = round((before_qty * before_avg) + row.gross_amount + row.fee, 6)
            after_avg = round(total_cost / after_qty, 6) if after_qty > 0 else 0.0
            action = "OPEN" if before_qty <= 0 < after_qty else "ADD"
            final_decision = "BUY"
        else:
            if row.quantity > before_qty + 1e-9:
                raise ValueError(
                    f"line {row.line_number}: cannot sell {row.quantity:.6f} shares from a {before_qty:.6f} share holding"
                )
            cash_after = round(state.cash + row.gross_amount - row.fee, 2)
            after_qty = round(before_qty - row.quantity, 6)
            after_avg = 0.0 if after_qty <= 0 else before_avg
            action = "CLOSE" if after_qty <= 0 else "REDUCE"
            final_decision = "SELL"

        after_value = round(after_qty * row.price, 2)
        position.quantity = after_qty
        position.avg_cost = after_avg
        position.current_price = row.price
        position.market_value = after_value
        position.status = "OPEN" if after_qty > 0 else "CLOSED"
        if after_qty > 0 and before_qty <= 0:
            position.opened_at = datetime.combine(trade_date, datetime.min.time())
        if after_qty > 0:
            position.closed_at = None
        if after_qty <= 0:
            position.closed_at = datetime.combine(trade_date, datetime.min.time())
        position.name = position.name or row.code
        state.cash = cash_after
        state.recompute_weights()
        equity_after = state.equity_value
        total_after = state.total_value
        target_weight = position.weight
        delta_amount = round(after_value - before_value, 2)

        reason = self._build_reason(row)
        row_result = {
            "line_number": row.line_number,
            "trade_date": trade_date.isoformat(),
            "settlement_date": settlement_date.isoformat(),
            "code": row.code,
            "side": row.side,
            "action": action,
            "final_decision": final_decision,
            "quantity": row.quantity,
            "price": row.price,
            "fee": row.fee,
            "gross_amount": row.gross_amount,
            "cash_before": cash_before,
            "cash_after": cash_after,
            "equity_before": equity_before,
            "equity_after": equity_after,
            "total_before": total_before,
            "total_after": total_after,
            "current_weight": current_weight,
            "target_weight": target_weight,
            "delta_amount": delta_amount,
            "warnings": list(row.warnings),
            "errors": list(row.errors),
        }

        if write and session is not None:
            snapshot_date = max(
                trade_date,
                state.snapshot_date or trade_date,
            )
            self.db.upsert_portfolio_position_in_session(
                session=session,
                code=row.code,
                name=position.name,
                quantity=position.quantity,
                avg_cost=position.avg_cost,
                current_price=position.current_price,
                weight=position.weight,
                market_value=position.market_value,
            )
            self._refresh_open_position_weights_in_session(session=session, total_value=total_after)
            # Refresh the state copy so later rows see the same weights as the database.
            for stored in state.positions.values():
                if stored.code == position.code:
                    stored.weight = position.weight
            state.recompute_weights()
            self.db.save_trade_journal_in_session(
                session=session,
                query_id=f"csv_import_{row.line_number}",
                code=row.code,
                action_date=trade_date,
                action=action,
                final_decision=final_decision,
                market_regime="MANUAL",
                event_risk="NA",
                data_quality_flag="MANUAL",
                current_weight=current_weight,
                target_weight=target_weight,
                delta_amount=delta_amount,
                current_quantity=before_qty,
                target_quantity=position.quantity,
                current_price=row.price,
                available_cash_before=round(total_before - equity_before, 2),
                available_cash_after=cash_after,
                reason=reason,
            )
            self.db.save_account_snapshot_in_session(
                session=session,
                snapshot_date=snapshot_date,
                cash=cash_after,
                equity_value=equity_after,
                total_value=total_after,
                note="updated_by_asx_csv_import",
            )
            state.snapshot_date = snapshot_date

        return row_result, state

    @staticmethod
    def _build_reason(row: ImportedTradeRow) -> str:
        trade_date = row.trade_date or date.min
        settlement_date = row.settlement_date or trade_date
        parts = [
            "csv_import",
            f"trade_date={trade_date.isoformat()}",
            f"settlement_date={settlement_date.isoformat()}",
            f"broker={row.broker}",
            f"account_label={row.account_label}",
            f"currency={row.currency}",
            f"fee={row.fee:.2f}",
        ]
        if row.custody_metadata:
            parts.append(f"hin={row.custody_metadata}")
        if row.dividend is not None:
            parts.append(f"dividend={row.dividend:.2f}")
        if row.franking_credit is not None:
            parts.append(f"franking_credit={row.franking_credit:.2f}")
        return "; ".join(parts)

    def _refresh_open_position_weights_in_session(self, *, session, total_value: float) -> None:
        rows = session.execute(
            select(PortfolioPosition).where(PortfolioPosition.status == "OPEN")
        ).scalars().all()
        for row in rows:
            market_value = float(row.market_value or 0.0)
            row.weight = round(market_value / total_value, 6) if total_value > 0 else 0.0

    def _build_totals(
        self,
        rows: List[ImportedTradeRow],
        *,
        state: Optional[LedgerState] = None,
        simulated_state: Optional[LedgerState] = None,
    ) -> Dict[str, Any]:
        buy_notional = round(sum(row.gross_amount for row in rows if not row.errors and row.side == "BUY"), 2)
        sell_notional = round(sum(row.gross_amount for row in rows if not row.errors and row.side == "SELL"), 2)
        fees = round(sum(row.fee for row in rows if not row.errors), 2)
        net_cash_impact = round(sell_notional - buy_notional - fees, 2)
        return {
            "buy_notional": buy_notional,
            "sell_notional": sell_notional,
            "fees": fees,
            "net_cash_impact": net_cash_impact,
            "starting_cash": state.cash if state else None,
            "ending_cash": simulated_state.cash if simulated_state else (state.cash if state else None),
            "starting_total_value": state.total_value if state else None,
            "ending_total_value": simulated_state.total_value if simulated_state else (state.total_value if state else None),
        }

    @staticmethod
    def _dedupe_strings(values: Iterable[str]) -> List[str]:
        seen: set[str] = set()
        result: List[str] = []
        for value in values:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result


__all__ = ["AsxPortfolioImportService"]
