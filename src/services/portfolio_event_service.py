# -*- coding: utf-8 -*-
"""Read-only unified portfolio event facade."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select

from src.stock_code import canonical_stock_code, stock_code_aliases
from src.storage import (
    AccountSnapshot,
    DatabaseManager,
    PaperPortfolioTrade,
    PortfolioPosition,
    TradeJournal,
)

SENSITIVE_MARKERS = (
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
    "order_id",
    "fill_id",
)
SAFE_REASON_KEYS = {
    "parser",
    "settlement_date",
    "custody_metadata_present",
    "dedup_duplicate",
    "dedup_reason",
}


@dataclass(frozen=True)
class PortfolioEventFilters:
    source: Optional[str] = None
    event_type: Optional[str] = None
    code: Optional[str] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    page: int = 1
    page_size: int = 50


class PortfolioEventService:
    """Build a read-only event view from existing portfolio tables."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    def list_events(self, filters: PortfolioEventFilters) -> Dict[str, Any]:
        page = max(int(filters.page or 1), 1)
        page_size = min(max(int(filters.page_size or 50), 1), 200)
        normalized = PortfolioEventFilters(
            source=_clean_optional(filters.source),
            event_type=_clean_optional(filters.event_type),
            code=_clean_optional(filters.code),
            date_from=filters.date_from,
            date_to=filters.date_to,
            page=page,
            page_size=page_size,
        )

        with self.db.get_session() as session:
            events: List[Dict[str, Any]] = []
            events.extend(self._position_events(session))
            events.extend(self._trade_journal_events(session))
            events.extend(self._account_snapshot_events(session))
            events.extend(self._paper_trade_events(session))

        events = [event for event in events if self._matches(event, normalized)]
        events.sort(key=_event_sort_key, reverse=True)
        total = len(events)
        start = (page - 1) * page_size
        end = start + page_size
        return {
            "events": events[start:end],
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_next": end < total,
        }

    def _position_events(self, session) -> List[Dict[str, Any]]:
        rows = session.execute(select(PortfolioPosition)).scalars().all()
        events: List[Dict[str, Any]] = []
        for row in rows:
            code = canonical_stock_code(row.code)
            status = str(row.status or "OPEN").upper()
            events.append(
                _base_event(
                    event_id=f"portfolio_position:{row.id}",
                    event_type="portfolio_position",
                    source="portfolio",
                    code=code,
                    event_date=_date_part(row.updated_at or row.opened_at or row.closed_at),
                    created_at=row.updated_at or row.opened_at or row.closed_at,
                    action="POSITION",
                    status=status,
                    quantity=row.quantity,
                    price=row.current_price or row.avg_cost,
                    cash=None,
                    equity=row.market_value,
                    total_value=None,
                    summary=f"{status.lower()} position {code}",
                    metadata={
                        "name": _safe_note(row.name),
                        "avg_cost": row.avg_cost,
                        "weight": row.weight,
                        "unrealized_pnl": row.unrealized_pnl,
                    },
                )
            )
        return events

    def _trade_journal_events(self, session) -> List[Dict[str, Any]]:
        rows = session.execute(select(TradeJournal)).scalars().all()
        events: List[Dict[str, Any]] = []
        for row in rows:
            metadata = _safe_reason_metadata(row.reason)
            source = "portfolio_import" if _looks_like_import(row) else "portfolio"
            event_date = row.action_date
            created_at = row.created_at
            quantity = _quantity_delta(row.current_quantity, row.target_quantity)
            summary_action = str(row.action or "portfolio action").lower()
            code = canonical_stock_code(row.code)
            events.append(
                _base_event(
                    event_id=f"trade_journal:{row.id}",
                    event_type="trade_journal",
                    source=source,
                    code=code,
                    event_date=event_date,
                    created_at=created_at,
                    action=row.action,
                    status=row.final_decision,
                    quantity=quantity,
                    price=row.current_price,
                    cash=row.available_cash_after,
                    equity=None,
                    total_value=None,
                    summary=f"{summary_action} {code}",
                    metadata={
                        **metadata,
                        "final_decision": row.final_decision,
                        "market_regime": row.market_regime,
                        "event_risk": row.event_risk,
                        "data_quality_flag": row.data_quality_flag,
                        "current_weight": row.current_weight,
                        "target_weight": row.target_weight,
                        "delta_amount": row.delta_amount,
                    },
                )
            )
        return events

    def _account_snapshot_events(self, session) -> List[Dict[str, Any]]:
        rows = session.execute(select(AccountSnapshot)).scalars().all()
        events: List[Dict[str, Any]] = []
        for row in rows:
            events.append(
                _base_event(
                    event_id=f"account_snapshot:{row.id}",
                    event_type="account_snapshot",
                    source="portfolio",
                    code=None,
                    event_date=row.snapshot_date,
                    created_at=row.created_at,
                    action="SNAPSHOT",
                    status=None,
                    quantity=None,
                    price=None,
                    cash=row.cash,
                    equity=row.equity_value,
                    total_value=row.total_value,
                    summary=f"portfolio snapshot {row.snapshot_date.isoformat()}",
                    metadata={"daily_pnl": row.daily_pnl, "note": _safe_note(row.note)},
                )
            )
        return events

    def _paper_trade_events(self, session) -> List[Dict[str, Any]]:
        rows = session.execute(select(PaperPortfolioTrade)).scalars().all()
        events: List[Dict[str, Any]] = []
        for row in rows:
            code = canonical_stock_code(row.code)
            quantity = _quantity_delta(row.before_quantity, row.after_quantity)
            events.append(
                _base_event(
                    event_id=f"paper_portfolio_trade:{row.id}",
                    event_type="paper_portfolio_trade",
                    source="paper_portfolio",
                    code=code,
                    event_date=_date_part(row.simulation_time),
                    created_at=row.created_at or row.simulation_time,
                    action=row.action,
                    status="executed" if row.executed else "skipped",
                    quantity=quantity,
                    price=row.price,
                    cash=row.cash_after,
                    equity=None,
                    total_value=None,
                    summary=f"paper {str(row.action or '').lower()} {code}",
                    metadata={
                        "analysis_status": row.analysis_status,
                        "executed": bool(row.executed),
                        "target_weight": row.target_weight,
                        "target_quantity": row.target_quantity,
                        "before_quantity": row.before_quantity,
                        "after_quantity": row.after_quantity,
                        "cash_before": row.cash_before,
                        "cash_after": row.cash_after,
                        "reason": _safe_note(row.reason),
                    },
                )
            )
        return events

    def _matches(self, event: Dict[str, Any], filters: PortfolioEventFilters) -> bool:
        if filters.source and event.get("source") != filters.source:
            return False
        if filters.event_type and event.get("event_type") != filters.event_type:
            return False
        if filters.code:
            aliases = set(_event_filter_code_aliases(filters.code))
            if not aliases:
                return False
            if event.get("code") not in aliases:
                return False
        event_date = _parse_event_date(event.get("event_date"))
        if filters.date_from and (event_date is None or event_date < filters.date_from):
            return False
        if filters.date_to and (event_date is None or event_date > filters.date_to):
            return False
        return True


def _base_event(
    *,
    event_id: str,
    event_type: str,
    source: str,
    code: Optional[str],
    event_date: Optional[date],
    created_at: Optional[datetime],
    action: Optional[str],
    status: Optional[str],
    quantity: Optional[float],
    price: Optional[float],
    cash: Optional[float],
    equity: Optional[float],
    total_value: Optional[float],
    summary: str,
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "id": event_id,
        "event_type": event_type,
        "source": source,
        "code": code,
        "symbol": code,
        "event_date": event_date.isoformat() if event_date else None,
        "created_at": created_at.isoformat() if created_at else None,
        "action": action,
        "status": status,
        "quantity": _round_optional(quantity, 6),
        "price": _round_optional(price, 6),
        "cash": _round_optional(cash, 2),
        "equity": _round_optional(equity, 2),
        "total_value": _round_optional(total_value, 2),
        "summary": summary,
        "metadata": _clean_metadata(metadata),
    }


def _clean_optional(value: Optional[str]) -> Optional[str]:
    cleaned = str(value or "").strip()
    return cleaned or None


def _event_filter_code_aliases(value: str) -> Tuple[str, ...]:
    code = str(value or "").strip().upper()
    canonical = canonical_stock_code(code)
    if not canonical:
        return ()
    aliases = list(stock_code_aliases(canonical))
    if "." not in canonical:
        aliases.extend(stock_code_aliases(f"{canonical}.AX"))
    return tuple(dict.fromkeys(aliases))


def _event_sort_key(event: Dict[str, Any]) -> Tuple[datetime, str]:
    created_at = _parse_datetime(event.get("created_at"))
    event_date = _parse_event_date(event.get("event_date"))
    if created_at:
        return created_at, str(event.get("id") or "")
    if event_date:
        return datetime.combine(event_date, time.min, tzinfo=timezone.utc), str(event.get("id") or "")
    return datetime.min.replace(tzinfo=timezone.utc), str(event.get("id") or "")


def _parse_event_date(value: Any) -> Optional[date]:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text[:10]).date()
    except ValueError:
        return None


def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _date_part(value: Optional[datetime]) -> Optional[date]:
    return value.date() if value else None


def _quantity_delta(before: Any, after: Any) -> Optional[float]:
    if before is None or after is None:
        return None
    return abs(float(after or 0.0) - float(before or 0.0))


def _round_optional(value: Any, places: int) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), places)


def _looks_like_import(row: TradeJournal) -> bool:
    text = f"{row.query_id or ''} {row.reason or ''}".lower()
    return "csv_import" in text or "parser=" in text or "settlement_date=" in text


def _safe_reason_metadata(reason: Any) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {}
    for key, value in re.findall(r"([A-Za-z_][A-Za-z0-9_]*)=([^\s]+)", str(reason or "")):
        lowered = key.lower()
        if lowered not in SAFE_REASON_KEYS:
            continue
        if _is_sensitive(lowered) or _is_sensitive(value):
            continue
        metadata[lowered] = _coerce_metadata_value(value)
    return metadata


def _safe_note(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    if not text or _is_sensitive(text):
        return None
    return text[:255]


def _clean_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    cleaned: Dict[str, Any] = {}
    for key, value in metadata.items():
        if value is None or _is_sensitive(key) or _is_sensitive(value):
            continue
        cleaned[key] = value
    return cleaned


def _coerce_metadata_value(value: str) -> Any:
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return value


def _is_sensitive(value: Any) -> bool:
    text = str(value or "").lower()
    return any(marker in text for marker in SENSITIVE_MARKERS)
