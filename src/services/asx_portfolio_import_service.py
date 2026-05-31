# -*- coding: utf-8 -*-
"""Read-only preview and explicit apply support for ASX portfolio CSV imports."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import desc, select

from src.stock_code import canonical_stock_code
from src.storage import AccountSnapshot, DatabaseManager, PortfolioPosition, TradeJournal

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
DEFAULT_PARSER_ID = "generic_asx"
DEDUP_HASH_FIELDS = (
    "parser_id",
    "trade_date",
    "settlement_date",
    "code",
    "side",
    "quantity",
    "price",
    "fee",
    "currency",
    "broker",
    "account_label",
)


def _normalize_header(value: str) -> str:
    return (
        str(value or "")
        .strip()
        .lower()
        .replace("/", "_")
        .replace("-", "_")
        .replace(" ", "_")
    )


@dataclass(frozen=True)
class CsvParserSpec:
    id: str
    display_name: str
    aliases: Tuple[str, ...]
    required_fields: Tuple[str, ...]
    column_aliases: Dict[str, Tuple[str, ...]]

    def alias_map(self) -> Dict[str, str]:
        aliases: Dict[str, str] = {}
        for canonical, values in self.column_aliases.items():
            aliases[_normalize_header(canonical)] = canonical
            for value in values:
                aliases[_normalize_header(value)] = canonical
        return aliases

    def canonical_field(self, header: str) -> str:
        normalized = _normalize_header(header)
        return self.alias_map().get(normalized, normalized)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "aliases": list(self.aliases),
            "required_fields": list(self.required_fields),
            "column_aliases": {
                field_name: list(aliases)
                for field_name, aliases in self.column_aliases.items()
            },
        }


GENERIC_ASX_PARSER = CsvParserSpec(
    id=DEFAULT_PARSER_ID,
    display_name="Generic ASX CSV",
    aliases=("generic", "asx", "generic-asx", "generic asx"),
    required_fields=tuple(sorted(REQUIRED_COLUMNS)) + ("fee",),
    column_aliases={
        "trade_date": ("trade_date", "trade date", "transaction_date", "transaction date", "date"),
        "settlement_date": ("settlement_date", "settlement date", "settle_date", "settle date"),
        "code": ("code", "symbol", "ticker", "asx_code", "asx code"),
        "side": ("side", "buy_sell", "buy/sell", "transaction_type", "transaction type", "action"),
        "quantity": ("quantity", "qty", "units", "shares"),
        "price": ("price", "unit_price", "unit price", "trade_price", "trade price"),
        "fee": FEE_COLUMNS,
        "currency": ("currency", "ccy"),
        "broker": ("broker", "broker_name", "broker name"),
        "account_label": ("account_label", "account label", "account", "portfolio", "portfolio_name"),
        "custody_metadata": HIN_COLUMNS,
        "dividend": DIVIDEND_COLUMNS,
        "franking_credit": FRANKING_COLUMNS,
    },
)
PARSER_REGISTRY = {GENERIC_ASX_PARSER.id: GENERIC_ASX_PARSER}
PARSER_ALIAS_MAP = {
    _normalize_header(alias): GENERIC_ASX_PARSER.id
    for alias in (GENERIC_ASX_PARSER.id, *GENERIC_ASX_PARSER.aliases)
}


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
    parser_id: str
    custody_metadata: str = ""
    dividend: Optional[float] = None
    franking_credit: Optional[float] = None
    dedup_hash: str = ""
    duplicate: bool = False
    duplicate_reason: Optional[str] = None
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
            "parser_id": self.parser_id,
            "dedup_hash": self.dedup_hash or None,
            "dedup": {
                "hash": self.dedup_hash or None,
                "duplicate": bool(self.duplicate),
                "reason": self.duplicate_reason,
            },
            "skipped": bool(self.duplicate),
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

    def preview_csv(self, csv_path: str | Path, parser_id: str = DEFAULT_PARSER_ID) -> Dict[str, Any]:
        return self._run(csv_path=csv_path, apply=False, parser_id=parser_id)

    def apply_csv(self, csv_path: str | Path, parser_id: str = DEFAULT_PARSER_ID) -> Dict[str, Any]:
        return self._run(csv_path=csv_path, apply=True, parser_id=parser_id)

    def _run(self, *, csv_path: str | Path, apply: bool, parser_id: str) -> Dict[str, Any]:
        parser_spec = self._resolve_parser_spec(parser_id)
        path = Path(csv_path)
        rows, parse_errors, parse_warnings = self._parse_rows(path, parser_spec)
        self._mark_file_duplicates(rows)
        base_result = self._build_base_result(
            path=path,
            parser_spec=parser_spec,
            rows=rows,
            parse_errors=parse_errors,
            parse_warnings=parse_warnings,
            apply=apply,
        )

        if base_result["errors"]:
            base_result["status"] = "invalid"
            return base_result

        try:
            state, existing_hashes = self._load_state_and_existing_hashes(
                row.dedup_hash for row in rows if row.dedup_hash and not row.duplicate
            )
        except ValueError as exc:
            base_result["errors"].append(str(exc))
            self._refresh_result_counts(base_result, rows)
            return base_result

        self._mark_existing_duplicates(rows, existing_hashes)
        base_result = self._build_base_result(
            path=path,
            parser_spec=parser_spec,
            rows=rows,
            parse_errors=parse_errors,
            parse_warnings=parse_warnings,
            apply=apply,
        )
        active_count = len(self._active_rows(rows))

        try:
            simulated_state, simulation_rows, integrity_hint = self._simulate_rows(state.clone(), rows)
        except Exception as exc:
            result = {
                **base_result,
                "status": "invalid",
                "errors": base_result["errors"] + [str(exc)],
            }
            self._refresh_result_counts(result, rows, would_apply_count=active_count)
            return result
        base_result["rows"] = simulation_rows
        base_result["totals"] = self._build_totals(rows, state=state, simulated_state=simulated_state)
        base_result["can_apply"] = True
        base_result["warnings"] = self._dedupe_strings(base_result["warnings"] + integrity_hint["warnings"])
        self._refresh_result_counts(base_result, rows, would_apply_count=active_count)

        if not apply:
            base_result["status"] = "preview"
            return base_result

        try:
            integrity, applied_count = self._apply_rows(rows)
        except Exception as exc:
            logger.warning("ASX CSV import failed: %s", exc)
            result = {
                **base_result,
                "status": "invalid",
                "errors": base_result["errors"] + [str(exc)],
                "integrity": {"is_valid": False, "errors": [str(exc)], "warnings": []},
            }
            self._refresh_result_counts(result, rows, would_apply_count=active_count)
            return result

        result = {
            **base_result,
            "status": "applied",
            "applied_count": applied_count,
            "integrity": integrity,
        }
        self._refresh_result_counts(result, rows, applied_count=applied_count)
        return result

    def _parse_rows(
        self,
        path: Path,
        parser_spec: CsvParserSpec,
    ) -> Tuple[List[ImportedTradeRow], List[str], List[str]]:
        if not path.exists():
            raise FileNotFoundError(f"CSV file not found: {path}")

        raw_text = path.read_text(encoding="utf-8-sig")
        reader = csv.DictReader(io.StringIO(raw_text))
        if not reader.fieldnames:
            return [], ["CSV header row is missing"], []

        normalized_headers = [_normalize_header(field) for field in reader.fieldnames]
        header_map = {
            parser_spec.canonical_field(normalized_headers[index]): reader.fieldnames[index]
            for index in range(len(reader.fieldnames))
        }
        missing_required = sorted(
            column for column in parser_spec.required_fields
            if column != "fee" and column not in header_map
        )
        fee_header_present = "fee" in header_map
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
                parser_spec.canonical_field(_normalize_header(key)): str(value or "").strip()
                for key, value in raw_row.items()
            }
            row = self._parse_row(
                normalized_row,
                line_number=line_number,
                parser_id=parser_spec.id,
            )
            rows.append(row)
            warnings.extend(row.warnings)
        return rows, [], self._dedupe_strings(warnings)

    def _parse_row(self, row: Dict[str, str], *, line_number: int, parser_id: str) -> ImportedTradeRow:
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

        imported = ImportedTradeRow(
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
            parser_id=parser_id,
            custody_metadata=custody_metadata,
            dividend=dividend,
            franking_credit=franking_credit,
            warnings=self._dedupe_strings(warnings),
            errors=self._dedupe_strings(errors),
        )
        if not imported.errors:
            imported.dedup_hash = self._build_dedup_hash(imported)
        return imported

    def _load_state(self) -> LedgerState:
        with self.db.get_session() as session:
            return LedgerState.from_session(session)

    def _load_state_and_existing_hashes(
        self,
        hashes: Iterable[str],
    ) -> Tuple[LedgerState, set[str]]:
        with self.db.get_session() as session:
            state = LedgerState.from_session(session)
            existing_hashes = self._existing_dedup_hashes_in_session(session, hashes)
            return state, existing_hashes

    def _existing_dedup_hashes_in_session(self, session, hashes: Iterable[str]) -> set[str]:
        values = sorted({str(value or "").strip() for value in hashes if str(value or "").strip()})
        if not values:
            return set()
        rows = session.execute(
            select(TradeJournal.query_id).where(TradeJournal.query_id.in_(values))
        ).scalars().all()
        return {str(value) for value in rows if value}

    def _simulate_rows(
        self,
        state: LedgerState,
        rows: List[ImportedTradeRow],
    ) -> Tuple[LedgerState, List[Dict[str, Any]], Dict[str, List[str]]]:
        simulated_rows: List[Dict[str, Any]] = []
        warnings: List[str] = []
        for row in sorted(rows, key=lambda item: (item.trade_date, item.settlement_date, item.line_number)):
            if row.duplicate:
                row_result = self._build_skipped_row_result(row)
                simulated_rows.append(row_result)
                warnings.extend(row_result.get("warnings", []))
                continue
            row_result, _ = self._apply_trade(state, row, write=False)
            simulated_rows.append(row_result)
            warnings.extend(row_result.get("warnings", []))
        return state, simulated_rows, {"warnings": self._dedupe_strings(warnings)}

    def _apply_rows(self, rows: List[ImportedTradeRow]) -> Tuple[Dict[str, Any], int]:
        with self.db.get_portfolio_write_lock():
            with self.db.get_session() as session:
                self.db.begin_portfolio_write_transaction(session)
                state = LedgerState.from_session(session)
                applied_rows: List[Dict[str, Any]] = []
                for row in sorted(rows, key=lambda item: (item.trade_date, item.settlement_date, item.line_number)):
                    if row.duplicate:
                        continue
                    row_result, _ = self._apply_trade(state, row, write=True, session=session)
                    applied_rows.append(row_result)

                integrity = self.db.check_portfolio_account_integrity(session=session)
                if not integrity["is_valid"]:
                    detail = "; ".join(integrity["errors"])
                    raise ValueError(f"Import aborted by integrity check: {detail}")

                session.commit()
                return integrity, len(applied_rows)

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
            "parser_id": row.parser_id,
            "dedup_hash": row.dedup_hash or None,
            "dedup": {
                "hash": row.dedup_hash or None,
                "duplicate": False,
                "reason": None,
            },
            "skipped": False,
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
                query_id=row.dedup_hash or f"csv_import_{row.line_number}",
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
    def _resolve_parser_spec(parser_id: str) -> CsvParserSpec:
        normalized = _normalize_header(parser_id or DEFAULT_PARSER_ID)
        resolved_id = PARSER_ALIAS_MAP.get(normalized, normalized)
        parser_spec = PARSER_REGISTRY.get(resolved_id)
        if parser_spec is None:
            supported = ", ".join(sorted(PARSER_ALIAS_MAP))
            raise ValueError(f"Unsupported ASX CSV parser_id '{parser_id}'. Supported values: {supported}")
        return parser_spec

    def _build_base_result(
        self,
        *,
        path: Path,
        parser_spec: CsvParserSpec,
        rows: List[ImportedTradeRow],
        parse_errors: List[str],
        parse_warnings: List[str],
        apply: bool,
    ) -> Dict[str, Any]:
        warnings = self._dedupe_strings(parse_warnings + [warning for row in rows for warning in row.warnings])
        errors = self._dedupe_strings(parse_errors + [error for row in rows for error in row.errors])
        result = {
            "source_path": str(path),
            "parser": parser_spec.to_dict(),
            "row_count": len(rows),
            "valid_row_count": sum(1 for row in rows if not row.errors),
            "invalid_row_count": sum(1 for row in rows if row.errors),
            "rows": [row.to_preview_dict() for row in rows],
            "warnings": warnings,
            "errors": errors,
            "totals": self._build_totals(rows),
            "can_apply": False,
            "status": "preview" if not apply else "invalid",
            "applied_count": 0,
            "integrity": {"is_valid": False, "errors": [], "warnings": []},
        }
        self._refresh_result_counts(result, rows)
        return result

    def _refresh_result_counts(
        self,
        result: Dict[str, Any],
        rows: List[ImportedTradeRow],
        *,
        applied_count: int = 0,
        would_apply_count: int = 0,
    ) -> None:
        result["warnings"] = self._dedupe_strings(result.get("warnings", []))
        result["errors"] = self._dedupe_strings(result.get("errors", []))
        result["row_count"] = len(rows)
        result["valid_row_count"] = sum(1 for row in rows if not row.errors)
        result["invalid_row_count"] = sum(1 for row in rows if row.errors)
        result["applied_count"] = applied_count
        result["dedup"] = self._build_dedup_info(rows)
        result["counters"] = self._build_counters(
            rows,
            warnings=result["warnings"],
            errors=result["errors"],
            applied_count=applied_count,
            would_apply_count=would_apply_count,
        )

    @staticmethod
    def _build_counters(
        rows: List[ImportedTradeRow],
        *,
        warnings: List[str],
        errors: List[str],
        applied_count: int,
        would_apply_count: int,
    ) -> Dict[str, int]:
        duplicate_count = sum(1 for row in rows if row.duplicate)
        invalid_count = sum(1 for row in rows if row.errors)
        return {
            "parsed_count": len(rows),
            "valid_count": sum(1 for row in rows if not row.errors),
            "error_count": len(errors),
            "warning_count": len(warnings),
            "duplicate_count": duplicate_count,
            "applied_count": applied_count,
            "would_apply_count": would_apply_count,
            "skipped_count": duplicate_count + invalid_count,
        }

    def _build_dedup_info(self, rows: List[ImportedTradeRow]) -> Dict[str, Any]:
        duplicate_rows = [row for row in rows if row.duplicate]
        return {
            "hash_algorithm": "sha256",
            "hash_fields": list(DEDUP_HASH_FIELDS),
            "duplicate_count": len(duplicate_rows),
            "file_duplicate_count": sum(
                1 for row in duplicate_rows if row.duplicate_reason == "duplicate_in_file"
            ),
            "existing_duplicate_count": sum(
                1 for row in duplicate_rows if row.duplicate_reason == "already_imported"
            ),
            "skipped_hashes": self._dedupe_strings(row.dedup_hash for row in duplicate_rows),
        }

    @staticmethod
    def _active_rows(rows: List[ImportedTradeRow]) -> List[ImportedTradeRow]:
        return [row for row in rows if not row.errors and not row.duplicate]

    def _mark_file_duplicates(self, rows: List[ImportedTradeRow]) -> None:
        first_line_by_hash: Dict[str, int] = {}
        for row in rows:
            if row.errors or not row.dedup_hash:
                continue
            first_line = first_line_by_hash.get(row.dedup_hash)
            if first_line is None:
                first_line_by_hash[row.dedup_hash] = row.line_number
                continue
            row.duplicate = True
            row.duplicate_reason = "duplicate_in_file"
            row.warnings = self._dedupe_strings(
                [
                    *row.warnings,
                    f"line {row.line_number}: duplicate trade row skipped; matches line {first_line}",
                ]
            )

    def _mark_existing_duplicates(
        self,
        rows: List[ImportedTradeRow],
        existing_hashes: set[str],
    ) -> None:
        for row in rows:
            if row.errors or row.duplicate or not row.dedup_hash:
                continue
            if row.dedup_hash not in existing_hashes:
                continue
            row.duplicate = True
            row.duplicate_reason = "already_imported"
            row.warnings = self._dedupe_strings(
                [
                    *row.warnings,
                    f"line {row.line_number}: duplicate imported trade skipped; dedup hash already exists",
                ]
            )

    @staticmethod
    def _build_skipped_row_result(row: ImportedTradeRow) -> Dict[str, Any]:
        result = row.to_preview_dict()
        result.update(
            {
                "action": "SKIP",
                "final_decision": "SKIP",
                "skipped": True,
            }
        )
        return result

    @classmethod
    def _build_dedup_hash(cls, row: ImportedTradeRow) -> str:
        trade_date = row.trade_date.isoformat() if row.trade_date else ""
        settlement_date = row.settlement_date.isoformat() if row.settlement_date else trade_date
        payload = {
            "parser_id": row.parser_id,
            "trade_date": trade_date,
            "settlement_date": settlement_date,
            "code": row.code,
            "side": row.side,
            "quantity": cls._format_hash_float(row.quantity),
            "price": cls._format_hash_float(row.price),
            "fee": cls._format_hash_float(row.fee),
            "currency": row.currency,
            "broker": row.broker.strip().lower(),
            "account_label": row.account_label.strip().lower(),
        }
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    def _format_hash_float(value: float) -> str:
        return f"{round(float(value or 0.0), 6):.6f}"

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
            parts.append("custody_metadata_present=true")
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
        active_rows = [row for row in rows if not row.errors and not row.duplicate]
        buy_notional = round(sum(row.gross_amount for row in active_rows if row.side == "BUY"), 2)
        sell_notional = round(sum(row.gross_amount for row in active_rows if row.side == "SELL"), 2)
        fees = round(sum(row.fee for row in active_rows), 2)
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
