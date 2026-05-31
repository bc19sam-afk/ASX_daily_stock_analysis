# -*- coding: utf-8 -*-
"""Side-effect-free ledger v2 dry-run backfill diagnostics."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional

from sqlalchemy import select

from src.stock_code import canonical_stock_code
from src.storage import AccountSnapshot, DatabaseManager, PortfolioPosition, TradeJournal

_SAFE_REASON_KEYS = {
    "action_type",
    "cash_amount",
    "corporate_action",
    "corporate_action_type",
    "currency",
    "custody_metadata_present",
    "dedup_duplicate",
    "dedup_reason",
    "dividend",
    "event_type",
    "fee",
    "franking_credit",
    "franking_percent",
    "income_type",
    "parser",
    "payment_date",
    "quantity_ratio",
    "ratio",
    "settlement_date",
    "trade_date",
}
_SENSITIVE_MARKERS = (
    "hin",
    "account_number",
    "account number",
    "account_no",
    "account no",
    "custody_reference",
    "custody reference",
    "secret",
    "token",
    "password",
    "broker_token",
    "order_id",
    "fill_id",
    "real_order",
)
_QUANTITY_TOLERANCE = 1e-6
_CASH_TOLERANCE = 0.01
_INCOME_EVENT_TYPES = {"dividend", "franking_credit"}
_CORPORATE_ACTION_EVENT_TYPES = {"drp", "split", "consolidation", "return_of_capital"}


@dataclass(frozen=True)
class _TradeCandidate:
    payload: Dict[str, Any]
    supported: bool


class AsxLedgerV2DryRunService:
    """Build ledger v2 candidate rows without touching ledger v2 storage."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    def build_dry_run(self) -> Dict[str, Any]:
        """Return dry-run candidate entries and a v1/v2 diagnostic comparison."""
        with self.db.get_session() as session:
            journal_rows = (
                session.execute(
                    select(TradeJournal).order_by(TradeJournal.action_date, TradeJournal.created_at, TradeJournal.id)
                )
                .scalars()
                .all()
            )
            snapshot_rows = (
                session.execute(
                    select(AccountSnapshot).order_by(AccountSnapshot.snapshot_date, AccountSnapshot.created_at)
                )
                .scalars()
                .all()
            )
            positions = (
                session.execute(
                    select(PortfolioPosition).where(PortfolioPosition.status == "OPEN")
                )
                .scalars()
                .all()
            )

        candidates: List[Dict[str, Any]] = []
        supported_trade_candidates: List[Dict[str, Any]] = []
        unsupported_count = 0

        for row in journal_rows:
            candidate = self._candidate_from_trade_journal(row)
            candidates.append(candidate.payload)
            if candidate.supported:
                supported_trade_candidates.append(candidate.payload)
            else:
                unsupported_count += 1

        for row in snapshot_rows:
            candidates.append(self._candidate_from_account_snapshot(row))
            unsupported_count += 1

        aggregation = _aggregate_supported_trades(supported_trade_candidates)
        comparison = self._compare_with_v1(
            positions=positions,
            snapshots=snapshot_rows,
            aggregation=aggregation,
            unsupported_count=unsupported_count,
        )

        warnings = _dedupe_strings(
            [
                *comparison.get("warnings", []),
                *[
                    warning
                    for candidate in candidates
                    for warning in candidate.get("warnings", [])
                ],
            ]
        )

        return {
            "status": "available",
            "mode": "ledger_v2_dry_run_backfill",
            "is_dry_run": True,
            "will_write": False,
            "candidate_count": len(candidates),
            "supported_candidate_count": len(supported_trade_candidates),
            "unsupported_candidate_count": unsupported_count,
            "candidates": candidates,
            "aggregation": aggregation,
            "comparison": comparison,
            "warnings": warnings,
            "boundaries": {
                "v1_authoritative": True,
                "migration_cutover": False,
                "writes_ledger_v2": False,
                "broker_or_order_execution": False,
            },
        }

    def build_diagnostics(self) -> Dict[str, Any]:
        """Return operator-facing shadow-read diagnostics grouped for manual review."""
        dry_run = self.build_dry_run()
        comparison = dict(dry_run.get("comparison") or {})
        mismatched = _diagnostic_items(comparison.get("mismatched"))
        missing = _diagnostic_items(comparison.get("missing"))
        unsupported = _unsupported_diagnostic_items(dry_run.get("candidates") or [])
        warnings = _warning_diagnostic_items(dry_run.get("warnings") or [])
        summary = {
            "matched_count": int(comparison.get("matched_count") or 0),
            "mismatched_count": len(mismatched),
            "missing_count": len(missing),
            "unsupported_count": len(unsupported),
            "warning_count": len(warnings),
            "requires_manual_review": bool(mismatched or missing or unsupported or warnings),
            "v1_authoritative": True,
        }
        summary["groups"] = [
            _diagnostic_group("mismatched", "V1 / ledger v2 mismatch", len(mismatched), "manual_review"),
            _diagnostic_group("missing", "Missing from ledger v2 dry-run", len(missing), "manual_review"),
            _diagnostic_group(
                "unsupported",
                "Unsupported or cash-only placeholder",
                len(unsupported),
                "manual_review",
            ),
            _diagnostic_group("warnings", "Dry-run warning", len(warnings), "info"),
        ]
        return {
            "status": dry_run.get("status") or "available",
            "mode": "ledger_v2_shadow_read_diagnostics",
            "is_dry_run": True,
            "will_write": False,
            "summary": summary,
            "details": {
                "mismatched": mismatched,
                "missing": missing,
                "unsupported": unsupported,
                "warnings": warnings,
            },
            "warnings": [item["message"] for item in warnings],
            "boundaries": dict(dry_run.get("boundaries") or {}),
            "links": {
                "dry_run": "/api/v1/portfolio-events/ledger-v2/dry-run",
                "workbench": "/api/v1/workbench/summary",
            },
        }

    def _candidate_from_trade_journal(self, row: TradeJournal) -> _TradeCandidate:
        metadata = _safe_reason_metadata(row.reason)
        source_event_id = f"trade_journal:{_stable_trade_source_key(row)}"
        symbol = canonical_stock_code(row.code)
        trade_date = row.action_date.isoformat() if row.action_date else None
        settlement_date = _clean_optional(metadata.get("settlement_date"))
        side = _infer_trade_side(row)
        quantity_delta = _round_optional(
            _float_or_zero(row.target_quantity) - _float_or_zero(row.current_quantity),
            6,
        )
        cash_delta = _round_optional(
            _float_or_zero(row.available_cash_after) - _float_or_zero(row.available_cash_before),
            2,
        )
        fee = _round_optional(_safe_float(metadata.get("fee")), 2)
        currency = str(metadata.get("currency") or "AUD").strip().upper() or "AUD"
        income, corporate_action, event_warnings = _ledger_v2_event_placeholders(
            row=row,
            metadata=metadata,
            currency=currency,
        )

        warnings: List[str] = list(event_warnings)
        supported = side in {"BUY", "SELL"} and abs(float(quantity_delta or 0.0)) > _QUANTITY_TOLERANCE
        has_dividend_or_franking = (
            income.get("status") == "partial_placeholder"
            or _looks_like_dividend_or_franking(row)
        )
        if supported:
            event_type = "trade_buy" if side == "BUY" else "trade_sell"
        else:
            event_type = "unsupported"
            warnings.append(
                "unsupported trade journal row: only buy/sell trade rows are converted in this dry-run"
            )

        if has_dividend_or_franking:
            warnings.append(
                "dividend/franking event is explicit unsupported groundwork; ledger v2 dry-run "
                "does not backfill cash, tax, or franking rows yet"
            )
            if supported:
                warnings.append(
                    "trade candidate keeps dividend/franking as placeholders instead of synthesizing cash or tax rows"
                )

        signed_quantity = _signed_quantity(side=side, quantity_delta=quantity_delta)
        franking_amount = _round_optional(_safe_float(metadata.get("franking_credit")), 2)
        payload = {
            "source_event_id": source_event_id,
            "source_hash": "",
            "event_type": event_type,
            "trade_date": trade_date,
            "settlement_date": settlement_date,
            "symbol": symbol,
            "quantity_delta": signed_quantity,
            "cash_delta": cash_delta,
            "cash_balance_after": _round_optional(row.available_cash_after, 2),
            "currency": currency,
            "fees": {
                "total": fee,
                "brokerage": fee,
                "gst": None,
                "other": None,
                "status": "placeholder",
            },
            "tax": {
                "status": "placeholder" if supported else "unsupported",
                "amount": None,
            },
            "income": income,
            "franking": {
                "status": "placeholder" if supported or franking_amount is not None else "unsupported",
                "amount": franking_amount,
                "currency": currency,
                "supported_in_dry_run": False,
                "will_create_tax_event": False,
                "requires_manual_review": franking_amount is not None,
            },
            "corporate_action": corporate_action,
            "confidence": "high" if supported and settlement_date else ("medium" if supported else "low"),
            "warnings": _dedupe_strings(warnings),
            "is_dry_run": True,
        }
        payload["source_hash"] = _trade_source_hash(row=row, metadata=metadata)
        return _TradeCandidate(payload=payload, supported=supported)

    def _candidate_from_account_snapshot(self, row: AccountSnapshot) -> Dict[str, Any]:
        source_hash = _snapshot_source_hash(row)
        snapshot_date = row.snapshot_date.isoformat() if row.snapshot_date else "unknown"
        payload = {
            "source_event_id": f"account_snapshot:{snapshot_date}:{source_hash[:16]}",
            "source_hash": source_hash,
            "event_type": "unsupported",
            "trade_date": row.snapshot_date.isoformat() if row.snapshot_date else None,
            "settlement_date": None,
            "symbol": None,
            "quantity_delta": None,
            "cash_delta": _round_optional(row.cash, 2),
            "currency": "AUD",
            "fees": {
                "total": None,
                "brokerage": None,
                "gst": None,
                "other": None,
                "status": "unsupported",
            },
            "tax": {
                "status": "unsupported",
                "amount": None,
            },
            "income": _empty_income_placeholder(currency="AUD"),
            "franking": {
                "status": "unsupported",
                "amount": None,
                "currency": "AUD",
                "supported_in_dry_run": False,
                "will_create_tax_event": False,
                "requires_manual_review": False,
            },
            "corporate_action": _empty_corporate_action_placeholder(currency="AUD"),
            "confidence": "low",
            "warnings": [
                "cash-only account snapshot is included for comparison but not transformed "
                "into ledger v2 cash events yet"
            ],
            "is_dry_run": True,
        }
        return payload

    def _compare_with_v1(
        self,
        *,
        positions: Iterable[PortfolioPosition],
        snapshots: Iterable[AccountSnapshot],
        aggregation: Mapping[str, Any],
        unsupported_count: int,
    ) -> Dict[str, Any]:
        latest_snapshot = _latest_snapshot(snapshots)
        existing_cash = _round_optional(latest_snapshot.cash, 2) if latest_snapshot else 0.0
        dry_run_cash = _round_optional(aggregation.get("cash_balance"), 2)
        matched: List[Dict[str, Any]] = []
        mismatched: List[Dict[str, Any]] = []
        missing: List[Dict[str, Any]] = []
        warnings: List[str] = []

        if dry_run_cash is None:
            missing.append({"type": "cash", "v1_cash": existing_cash, "dry_run_cash": None})
            warnings.append("dry-run ledger v2 aggregation could not derive a cash balance from supported trades")
        elif abs(float(existing_cash or 0.0) - float(dry_run_cash or 0.0)) <= _CASH_TOLERANCE:
            matched.append({"type": "cash", "symbol": None, "v1_cash": existing_cash, "dry_run_cash": dry_run_cash})
        else:
            mismatched.append({"type": "cash", "symbol": None, "v1_cash": existing_cash, "dry_run_cash": dry_run_cash})

        dry_run_positions = {
            str(symbol): payload
            for symbol, payload in dict(aggregation.get("positions") or {}).items()
        }
        seen_symbols: set[str] = set()
        for row in positions:
            symbol = canonical_stock_code(row.code)
            seen_symbols.add(symbol)
            existing_quantity = _round_optional(row.quantity, 6)
            dry_run_position = dry_run_positions.get(symbol)
            if dry_run_position is None:
                missing.append(
                    {
                        "type": "holding",
                        "symbol": symbol,
                        "v1_quantity": existing_quantity,
                        "dry_run_quantity": None,
                    }
                )
                continue
            dry_run_quantity = _round_optional(dry_run_position.get("quantity"), 6)
            if abs(float(existing_quantity or 0.0) - float(dry_run_quantity or 0.0)) <= _QUANTITY_TOLERANCE:
                matched.append(
                    {
                        "type": "holding",
                        "symbol": symbol,
                        "v1_quantity": existing_quantity,
                        "dry_run_quantity": dry_run_quantity,
                    }
                )
            else:
                mismatched.append(
                    {
                        "type": "holding",
                        "symbol": symbol,
                        "v1_quantity": existing_quantity,
                        "dry_run_quantity": dry_run_quantity,
                    }
                )

        for symbol, dry_run_position in sorted(dry_run_positions.items()):
            if symbol in seen_symbols:
                continue
            dry_run_quantity = _round_optional(dry_run_position.get("quantity"), 6)
            if abs(float(dry_run_quantity or 0.0)) <= _QUANTITY_TOLERANCE:
                continue
            mismatched.append(
                {
                    "type": "dry_run_only_holding",
                    "symbol": symbol,
                    "v1_quantity": None,
                    "dry_run_quantity": dry_run_quantity,
                }
            )

        if unsupported_count:
            warnings.append(
                f"{unsupported_count} v1 row(s) are explicit unsupported/cash-only placeholders in ledger v2 dry-run"
            )
        if mismatched or missing:
            warnings.append("v1 portfolio summary differs from ledger v2 dry-run aggregation; v1 remains authoritative")

        return {
            "matched_count": len(matched),
            "mismatched_count": len(mismatched),
            "missing_count": len(missing),
            "unsupported_count": unsupported_count,
            "matched": matched,
            "mismatched": mismatched,
            "missing": missing,
            "warnings": _dedupe_strings(warnings),
            "v1_authoritative": True,
        }


def _aggregate_supported_trades(candidates: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    positions: Dict[str, Dict[str, Any]] = {}
    cash_balance: Optional[float] = None
    trade_count = 0
    ordered = list(candidates)
    for candidate in ordered:
        trade_count += 1
        cash_delta = _round_optional(candidate.get("cash_delta"), 2) or 0.0
        cash_after = _round_optional(candidate.get("cash_balance_after"), 2)
        if cash_after is not None:
            cash_balance = cash_after
        elif cash_balance is None:
            cash_balance = round(cash_delta, 2)
        else:
            cash_balance = round(cash_balance + cash_delta, 2)
        symbol = str(candidate.get("symbol") or "").strip()
        if not symbol:
            continue
        row = positions.setdefault(
            symbol,
            {
                "symbol": symbol,
                "quantity": 0.0,
                "cash_delta": 0.0,
                "currency": candidate.get("currency") or "AUD",
            },
        )
        row["quantity"] = round(float(row["quantity"] or 0.0) + float(candidate.get("quantity_delta") or 0.0), 6)
        row["cash_delta"] = round(float(row["cash_delta"] or 0.0) + cash_delta, 2)

    return {
        "trade_count": trade_count,
        "cash_balance": cash_balance,
        "starting_cash": None,
        "positions": positions,
    }


def _infer_trade_side(row: TradeJournal) -> Optional[str]:
    final_decision = str(row.final_decision or "").strip().upper()
    if final_decision in {"BUY", "SELL"}:
        return final_decision
    action = str(row.action or "").strip().upper()
    if action in {"OPEN", "ADD"}:
        return "BUY"
    if action in {"REDUCE", "CLOSE"}:
        return "SELL"
    return None


def _looks_like_dividend_or_franking(row: TradeJournal) -> bool:
    text = " ".join(
        str(value or "").strip().lower()
        for value in (row.action, row.final_decision, row.reason)
    )
    return "dividend" in text or "franking" in text


def _ledger_v2_event_placeholders(
    *,
    row: TradeJournal,
    metadata: Mapping[str, Any],
    currency: str,
) -> tuple[Dict[str, Any], Dict[str, Any], List[str]]:
    event_markers = _event_markers(row=row, metadata=metadata)
    income_type = _first_known_event_type(event_markers, _INCOME_EVENT_TYPES)
    corporate_action_type = _first_known_event_type(event_markers, _CORPORATE_ACTION_EVENT_TYPES)
    has_income_amount = metadata.get("dividend") is not None or metadata.get("franking_credit") is not None
    has_income_text = _looks_like_dividend_or_franking(row)
    unknown_event = _has_unknown_event_marker(row=row, metadata=metadata, markers=event_markers)
    warnings: List[str] = []

    if income_type is None and has_income_amount:
        income_type = "dividend" if metadata.get("dividend") is not None else "franking_credit"
    if income_type is None and has_income_text:
        income_type = "dividend"

    if income_type is not None:
        income = {
            "status": "partial_placeholder",
            "income_type": income_type,
            "cash_amount": _round_optional(metadata.get("dividend") or metadata.get("cash_amount"), 2),
            "franking_credit_amount": _round_optional(metadata.get("franking_credit"), 2),
            "franking_percent": _round_optional(metadata.get("franking_percent"), 6),
            "currency": currency,
            "supported_in_dry_run": False,
            "will_create_cash_event": False,
            "will_create_tax_event": False,
            "requires_manual_review": True,
        }
        warnings.append(
            "ASX dividend/franking income placeholder is partial only; ledger v2 dry-run "
            "does not create cash events or calculate tax return values"
        )
    elif unknown_event:
        income = _unsupported_income_placeholder(currency=currency)
    else:
        income = _empty_income_placeholder(currency=currency)

    if corporate_action_type is not None:
        corporate_action = {
            "status": "unsupported_placeholder",
            "action_type": corporate_action_type,
            "quantity_ratio": _round_optional(metadata.get("quantity_ratio") or metadata.get("ratio"), 6),
            "cash_amount": _round_optional(metadata.get("cash_amount"), 2),
            "currency": currency,
            "supported_in_dry_run": False,
            "will_adjust_quantity": False,
            "will_adjust_cost_base": False,
            "requires_manual_review": True,
        }
        warnings.append(
            "ASX corporate action placeholder is explicit unsupported groundwork; ledger v2 dry-run "
            "does not adjust quantity, cash, or cost base"
        )
    elif unknown_event:
        corporate_action = _unsupported_corporate_action_placeholder(currency=currency)
    else:
        corporate_action = _empty_corporate_action_placeholder(currency=currency)

    if unknown_event and income_type is None and corporate_action_type is None:
        warnings.append(
            "unknown income/corporate-action event is explicit unsupported groundwork; "
            "ledger v2 dry-run does not treat it as supported"
        )

    return income, corporate_action, warnings


def _event_markers(*, row: TradeJournal, metadata: Mapping[str, Any]) -> List[str]:
    raw_values = [
        metadata.get("event_type"),
        metadata.get("income_type"),
        metadata.get("corporate_action_type"),
        metadata.get("corporate_action"),
        metadata.get("action_type"),
        row.action,
        row.final_decision,
    ]
    return [
        marker
        for marker in (_normalize_event_marker(value) for value in raw_values)
        if marker
    ]


def _normalize_event_marker(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    aliases = {
        "franking": "franking_credit",
        "frankingcredit": "franking_credit",
        "franking_credit_amount": "franking_credit",
        "returnofcapital": "return_of_capital",
        "return_capital": "return_of_capital",
        "roc": "return_of_capital",
        "dividend_reinvestment_plan": "drp",
        "dividend_reinvestment": "drp",
        "consolidate": "consolidation",
    }
    return aliases.get(text, text)


def _first_known_event_type(markers: Iterable[str], allowed: set[str]) -> Optional[str]:
    for marker in markers:
        if marker in allowed:
            return marker
    return None


def _has_unknown_event_marker(
    *,
    row: TradeJournal,
    metadata: Mapping[str, Any],
    markers: Iterable[str],
) -> bool:
    explicit_metadata_keys = {
        "event_type",
        "income_type",
        "corporate_action_type",
        "corporate_action",
        "action_type",
    }
    allowed_trade_actions = {"", "open", "add", "reduce", "close", "buy", "sell", "hold"}
    known_events = _INCOME_EVENT_TYPES | _CORPORATE_ACTION_EVENT_TYPES
    explicit_markers = [
        _normalize_event_marker(metadata.get(key))
        for key in explicit_metadata_keys
        if key in metadata
    ]
    values = explicit_markers or list(markers)
    return any(marker and marker not in allowed_trade_actions and marker not in known_events for marker in values)


def _empty_income_placeholder(*, currency: str) -> Dict[str, Any]:
    return {
        "status": "none",
        "income_type": None,
        "cash_amount": None,
        "franking_credit_amount": None,
        "franking_percent": None,
        "currency": currency,
        "supported_in_dry_run": False,
        "will_create_cash_event": False,
        "will_create_tax_event": False,
        "requires_manual_review": False,
    }


def _unsupported_income_placeholder(*, currency: str) -> Dict[str, Any]:
    placeholder = _empty_income_placeholder(currency=currency)
    placeholder.update(
        {
            "status": "unsupported",
            "income_type": "unknown",
            "requires_manual_review": True,
        }
    )
    return placeholder


def _empty_corporate_action_placeholder(*, currency: str) -> Dict[str, Any]:
    return {
        "status": "none",
        "action_type": None,
        "quantity_ratio": None,
        "cash_amount": None,
        "currency": currency,
        "supported_in_dry_run": False,
        "will_adjust_quantity": False,
        "will_adjust_cost_base": False,
        "requires_manual_review": False,
    }


def _unsupported_corporate_action_placeholder(*, currency: str) -> Dict[str, Any]:
    placeholder = _empty_corporate_action_placeholder(currency=currency)
    placeholder.update(
        {
            "status": "unsupported",
            "action_type": "unknown",
            "requires_manual_review": True,
        }
    )
    return placeholder


def _signed_quantity(*, side: Optional[str], quantity_delta: Optional[float]) -> Optional[float]:
    if quantity_delta is None:
        return None
    value = abs(float(quantity_delta or 0.0))
    if side == "SELL":
        return round(-value, 6)
    if side == "BUY":
        return round(value, 6)
    return _round_optional(quantity_delta, 6)


def _latest_snapshot(rows: Iterable[AccountSnapshot]) -> Optional[AccountSnapshot]:
    values = list(rows)
    if not values:
        return None
    return max(
        values,
        key=lambda row: (
            row.snapshot_date or date.min,
            row.created_at or datetime.min,
            row.id or 0,
        ),
    )


def _safe_reason_metadata(reason: Any) -> Dict[str, Any]:
    text = str(reason or "")
    metadata: Dict[str, Any] = {}
    segments = re.split(r"[;\n]", text)
    for segment in segments:
        for key, value in re.findall(r"([A-Za-z_][A-Za-z0-9_]*)=([^\s;]+)", segment):
            lowered = key.lower()
            cleaned = str(value or "").strip().strip(",;")
            if lowered not in _SAFE_REASON_KEYS:
                continue
            if _is_sensitive(lowered) or _is_sensitive(cleaned):
                continue
            metadata[lowered] = _coerce_metadata_value(cleaned)
    return metadata


def _stable_trade_source_key(row: TradeJournal) -> str:
    source_hash = _trade_source_hash(row=row, metadata=_safe_reason_metadata(row.reason))[:16]
    query_id = str(row.query_id or "").strip()
    if query_id and not _is_sensitive(query_id):
        return f"{_safe_source_key(query_id)}:{source_hash}"
    return source_hash


def _safe_source_key(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9_.:-]+", "-", str(value or "").strip())
    text = text.strip("-._:")
    return text[:64] or "unknown"


def _trade_source_hash(*, row: TradeJournal, metadata: Mapping[str, Any]) -> str:
    source_material = {
        "source": "trade_journal",
        "query_id": None if _is_sensitive(row.query_id) else str(row.query_id or "").strip() or None,
        "code": canonical_stock_code(row.code),
        "action_date": row.action_date.isoformat() if row.action_date else None,
        "action": str(row.action or "").strip().upper() or None,
        "final_decision": str(row.final_decision or "").strip().upper() or None,
        "current_quantity": _round_optional(row.current_quantity, 6),
        "target_quantity": _round_optional(row.target_quantity, 6),
        "current_price": _round_optional(row.current_price, 6),
        "available_cash_before": _round_optional(row.available_cash_before, 2),
        "available_cash_after": _round_optional(row.available_cash_after, 2),
        "settlement_date": _clean_optional(metadata.get("settlement_date")),
        "currency": _clean_optional(metadata.get("currency")) or "AUD",
        "fee": _round_optional(metadata.get("fee"), 2),
        "event_type": _clean_optional(metadata.get("event_type")),
        "income_type": _clean_optional(metadata.get("income_type")),
        "corporate_action_type": _clean_optional(metadata.get("corporate_action_type")),
        "corporate_action": _clean_optional(metadata.get("corporate_action")),
        "action_type": _clean_optional(metadata.get("action_type")),
        "dividend": _round_optional(metadata.get("dividend"), 2),
        "franking_credit": _round_optional(metadata.get("franking_credit"), 2),
        "franking_percent": _round_optional(metadata.get("franking_percent"), 6),
        "cash_amount": _round_optional(metadata.get("cash_amount"), 2),
        "quantity_ratio": _round_optional(metadata.get("quantity_ratio") or metadata.get("ratio"), 6),
    }
    serialized = json.dumps(source_material, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _snapshot_source_hash(row: AccountSnapshot) -> str:
    source_material = {
        "source": "account_snapshot",
        "snapshot_date": row.snapshot_date.isoformat() if row.snapshot_date else None,
        "cash": _round_optional(row.cash, 2),
        "equity_value": _round_optional(row.equity_value, 2),
        "total_value": _round_optional(row.total_value, 2),
        "daily_pnl": _round_optional(row.daily_pnl, 2),
    }
    serialized = json.dumps(source_material, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _float_or_zero(value: Any) -> float:
    parsed = _safe_float(value)
    return float(parsed or 0.0)


def _round_optional(value: Any, places: int) -> Optional[float]:
    parsed = _safe_float(value)
    if parsed is None:
        return None
    return round(float(parsed), places)


def _clean_optional(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return text or None


def _coerce_metadata_value(value: str) -> Any:
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    parsed = _safe_float(value)
    return parsed if parsed is not None else value


def _is_sensitive(value: Any) -> bool:
    text = str(value or "").lower()
    return any(marker in text for marker in _SENSITIVE_MARKERS)


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


def _diagnostic_group(group: str, label: str, count: int, severity: str) -> Dict[str, Any]:
    return {
        "group": group,
        "label": label,
        "count": int(count),
        "severity": severity,
    }


def _diagnostic_items(values: Any) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for value in values or []:
        if not isinstance(value, Mapping):
            continue
        item = {
            key: _redacted_diagnostic_value(value.get(key))
            for key in (
                "type",
                "symbol",
                "v1_quantity",
                "dry_run_quantity",
                "v1_cash",
                "dry_run_cash",
            )
            if key in value
        }
        if item:
            items.append(item)
    return items


def _unsupported_diagnostic_items(candidates: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for candidate in candidates:
        if str(candidate.get("event_type") or "") != "unsupported":
            continue
        items.append(
            {
                "source_event_id": _safe_diagnostic_text(candidate.get("source_event_id")),
                "event_type": "unsupported",
                "reason": "unsupported_or_cash_only_placeholder",
                "symbol": _redacted_diagnostic_value(candidate.get("symbol")),
                "trade_date": _redacted_diagnostic_value(candidate.get("trade_date")),
                "currency": _redacted_diagnostic_value(candidate.get("currency")),
                "warning_count": len(list(candidate.get("warnings") or [])),
                "warnings": _dedupe_strings(
                    _safe_diagnostic_text(warning)
                    for warning in candidate.get("warnings") or []
                ),
                "is_dry_run": True,
            }
        )
    return items


def _warning_diagnostic_items(warnings: Iterable[str]) -> List[Dict[str, Any]]:
    return [
        {
            "severity": "manual_review" if _warning_requires_manual_review(warning) else "info",
            "source": "ledger_v2_dry_run",
            "message": _safe_diagnostic_text(warning),
        }
        for warning in _dedupe_strings(warnings)
    ]


def _warning_requires_manual_review(warning: Any) -> bool:
    text = str(warning or "").lower()
    return any(marker in text for marker in ("differs", "unsupported", "missing", "mismatch"))


def _redacted_diagnostic_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return value
    return _safe_diagnostic_text(value)


def _safe_diagnostic_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if _is_sensitive(text):
        return "[redacted]"
    return text


__all__ = ["AsxLedgerV2DryRunService"]
