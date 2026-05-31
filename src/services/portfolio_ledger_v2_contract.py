# -*- coding: utf-8 -*-
"""Planned ledger v2 schema contract.

This module is intentionally declarative. It names the proposed ledger v2
tables and fields for design/test scaffolding, but it does not create tables,
open database sessions, or migrate stored data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Tuple

LEDGER_V2_CONTRACT_VERSION = "portfolio-ledger-v2-plan"


@dataclass(frozen=True)
class PlannedLedgerField:
    name: str
    value_type: str
    required: bool
    purpose: str


@dataclass(frozen=True)
class PlannedLedgerTable:
    name: str
    purpose: str
    fields: Tuple[PlannedLedgerField, ...]


def _field(name: str, value_type: str, purpose: str, *, required: bool = True) -> PlannedLedgerField:
    return PlannedLedgerField(
        name=name,
        value_type=value_type,
        required=required,
        purpose=purpose,
    )


PLANNED_LEDGER_V2_TABLES: Tuple[PlannedLedgerTable, ...] = (
    PlannedLedgerTable(
        name="portfolio_ledger_accounts",
        purpose="Sanitized account labels and ASX/AU/US market scope for manual review ledgers.",
        fields=(
            _field("account_uid", "string", "Internal stable account row id."),
            _field("account_label", "string", "User-facing sanitized portfolio label."),
            _field("broker_label", "string", "Sanitized broker display label.", required=False),
            _field("market_scope", "string", "Allowed market scope such as ASX, AU, or US."),
            _field("base_currency", "string", "Ledger base currency, default AUD."),
            _field("account_kind", "string", "Manual, paper, imported, or review-only account kind."),
            _field("custody_metadata_present", "boolean", "Whether an import indicated custody metadata."),
            _field("custody_reference_hash", "string", "Optional one-way custody reference digest.", required=False),
            _field("review_status", "string", "Manual review status for this account row."),
            _field("created_at", "datetime", "Contract row creation timestamp."),
            _field("updated_at", "datetime", "Contract row update timestamp."),
        ),
    ),
    PlannedLedgerTable(
        name="portfolio_ledger_trades",
        purpose="Normalized buy/sell trade events imported or entered for review.",
        fields=(
            _field("ledger_trade_uid", "string", "Internal stable trade event id."),
            _field("account_uid", "string", "Account row foreign key."),
            _field("symbol", "string", "Canonical symbol such as BHP.AX or AAPL."),
            _field("market", "string", "Market code, with ASX as the default local path."),
            _field("currency", "string", "Trade currency, usually AUD for ASX."),
            _field("side", "string", "BUY or SELL."),
            _field("trade_date", "date", "Trade date in exchange-local terms."),
            _field("settlement_date", "date", "Expected or actual settlement date."),
            _field("quantity", "decimal", "Trade quantity."),
            _field("price", "decimal", "Unit trade price."),
            _field("gross_amount", "decimal", "Quantity multiplied by price."),
            _field("brokerage", "decimal", "Brokerage amount.", required=False),
            _field("gst", "decimal", "GST component where applicable.", required=False),
            _field("fees", "decimal", "Other fees.", required=False),
            _field("import_batch_uid", "string", "Sanitized import batch id.", required=False),
            _field("source_row_hash", "string", "Dedup digest for the sanitized source row."),
            _field("review_status", "string", "Manual review status for the event."),
            _field("notes_sanitized", "text", "Optional sanitized review note.", required=False),
        ),
    ),
    PlannedLedgerTable(
        name="portfolio_ledger_cash_events",
        purpose="Cash movements such as deposits, withdrawals, fees, dividends, and settlements.",
        fields=(
            _field("cash_event_uid", "string", "Internal stable cash event id."),
            _field("account_uid", "string", "Account row foreign key."),
            _field("event_date", "date", "Cash event date."),
            _field("settlement_date", "date", "Settlement date when applicable.", required=False),
            _field("cash_amount", "decimal", "Signed cash amount."),
            _field("currency", "string", "Cash event currency."),
            _field("event_type", "string", "Deposit, withdrawal, dividend, fee, tax, or settlement."),
            _field("related_trade_uid", "string", "Related trade event id.", required=False),
            _field("related_action_uid", "string", "Related corporate-action id.", required=False),
            _field("tax_year", "string", "AU tax year marker where applicable.", required=False),
            _field("source_row_hash", "string", "Dedup digest for the sanitized source row.", required=False),
            _field("notes_sanitized", "text", "Optional sanitized review note.", required=False),
        ),
    ),
    PlannedLedgerTable(
        name="portfolio_ledger_corporate_actions",
        purpose="Splits, DRP, return of capital, and manual adjustment events.",
        fields=(
            _field("corporate_action_uid", "string", "Internal stable corporate-action id."),
            _field("symbol", "string", "Canonical symbol affected by the action."),
            _field("market", "string", "Market code."),
            _field("corporate_action_type", "string", "Split, DRP, return of capital, or adjustment."),
            _field("effective_date", "date", "Action effective date."),
            _field("ex_date", "date", "Ex date when applicable.", required=False),
            _field("settlement_date", "date", "Settlement or payment date when applicable.", required=False),
            _field("quantity_ratio", "decimal", "Quantity multiplier for splits or consolidations.", required=False),
            _field("cash_amount", "decimal", "Related cash amount.", required=False),
            _field("cost_base_adjustment", "decimal", "Cost-base adjustment amount.", required=False),
            _field("source_reference_hash", "string", "Digest of sanitized external reference.", required=False),
            _field("review_status", "string", "Manual review status for the action."),
        ),
    ),
    PlannedLedgerTable(
        name="portfolio_ledger_lots",
        purpose="Tax lot and cost-base slices derived from reviewed events.",
        fields=(
            _field("lot_uid", "string", "Internal stable lot id."),
            _field("account_uid", "string", "Account row foreign key."),
            _field("symbol", "string", "Canonical symbol."),
            _field("market", "string", "Market code."),
            _field("opened_trade_uid", "string", "Opening trade event id."),
            _field("open_date", "date", "Lot open date."),
            _field("lot_quantity", "decimal", "Original lot quantity."),
            _field("remaining_quantity", "decimal", "Remaining lot quantity."),
            _field("cost_base", "decimal", "Remaining cost base."),
            _field("currency", "string", "Lot currency."),
            _field("close_date", "date", "Lot close date if fully depleted.", required=False),
            _field("status", "string", "OPEN or CLOSED."),
            _field("tax_lot_method", "string", "Manual FIFO/LIFO/specific-id marker.", required=False),
        ),
    ),
    PlannedLedgerTable(
        name="portfolio_ledger_snapshots",
        purpose="Read-optimized daily account and position snapshot outputs.",
        fields=(
            _field("snapshot_uid", "string", "Internal stable snapshot id."),
            _field("account_uid", "string", "Account row foreign key."),
            _field("snapshot_date", "date", "Snapshot date."),
            _field("cash_balance", "decimal", "Cash balance."),
            _field("equity_value", "decimal", "Total holdings value."),
            _field("total_value", "decimal", "Cash plus equity value."),
            _field("base_currency", "string", "Snapshot base currency."),
            _field("generated_from_event_seq", "integer", "Last event sequence included."),
            _field("reconciliation_status", "string", "Clean, warning, or blocked reconciliation state."),
            _field("source", "string", "Generated, imported, paper, or manual review source."),
        ),
    ),
    PlannedLedgerTable(
        name="portfolio_ledger_franking_credits",
        purpose="Australian dividend and franking credit details for review and tax context.",
        fields=(
            _field("franking_credit_uid", "string", "Internal stable franking row id."),
            _field("account_uid", "string", "Account row foreign key."),
            _field("symbol", "string", "Canonical symbol."),
            _field("dividend_date", "date", "Dividend ex or entitlement date."),
            _field("payment_date", "date", "Dividend payment date."),
            _field("cash_amount", "decimal", "Cash dividend amount."),
            _field("franking_credit_amount", "decimal", "Franking credit amount."),
            _field("franking_percent", "decimal", "Franking percentage.", required=False),
            _field("tax_year", "string", "AU tax year marker."),
            _field("source_row_hash", "string", "Dedup digest for the sanitized source row.", required=False),
            _field("related_cash_event_uid", "string", "Related cash event id.", required=False),
        ),
    ),
    PlannedLedgerTable(
        name="portfolio_ledger_settlements",
        purpose="Settlement lifecycle rows derived from trades and cash events.",
        fields=(
            _field("settlement_uid", "string", "Internal stable settlement id."),
            _field("account_uid", "string", "Account row foreign key."),
            _field("related_trade_uid", "string", "Related trade event id."),
            _field("settlement_date", "date", "Expected or actual settlement date."),
            _field("settlement_status", "string", "Pending, settled, failed, or manually reconciled."),
            _field("cash_amount", "decimal", "Cash amount to settle."),
            _field("currency", "string", "Settlement currency."),
            _field("brokerage", "decimal", "Brokerage amount.", required=False),
            _field("gst", "decimal", "GST component where applicable.", required=False),
            _field("fees", "decimal", "Other fees.", required=False),
        ),
    ),
    PlannedLedgerTable(
        name="portfolio_ledger_audit_log",
        purpose="Manual-review audit trail for future migration and replay tooling.",
        fields=(
            _field("audit_event_uid", "string", "Internal stable audit event id."),
            _field("audit_actor", "string", "System, user, import, or migration actor label."),
            _field("action", "string", "Create, update, replay, validate, or rollback action."),
            _field("occurred_at", "datetime", "Audit event timestamp."),
            _field("reason_code", "string", "Machine-readable reason code."),
            _field("before_hash", "string", "Digest of prior sanitized row state.", required=False),
            _field("after_hash", "string", "Digest of new sanitized row state.", required=False),
            _field("request_id", "string", "Request or batch correlation id.", required=False),
            _field("is_dry_run", "boolean", "Whether the action was dry-run only."),
        ),
    ),
    PlannedLedgerTable(
        name="portfolio_ledger_idempotency_keys",
        purpose="Duplicate protection for imports, replay, and future migration batches.",
        fields=(
            _field("idempotency_key_hash", "string", "Digest key for duplicate protection."),
            _field("source_system", "string", "Import, manual, replay, or migration source."),
            _field("import_batch_uid", "string", "Sanitized import batch id.", required=False),
            _field("source_row_hash", "string", "Dedup digest for the sanitized source row.", required=False),
            _field("action_scope", "string", "Scope where this key applies."),
            _field("first_seen_at", "datetime", "First accepted timestamp."),
            _field("last_seen_at", "datetime", "Most recent duplicate check timestamp."),
            _field("status", "string", "Accepted, duplicate, ignored, or rolled back."),
        ),
    ),
)


def planned_table_names(tables: Iterable[PlannedLedgerTable] = PLANNED_LEDGER_V2_TABLES) -> set[str]:
    """Return planned ledger v2 table names."""
    return {table.name for table in tables}


def planned_field_names(tables: Iterable[PlannedLedgerTable] = PLANNED_LEDGER_V2_TABLES) -> set[str]:
    """Return all planned ledger v2 field names."""
    return {field.name for table in tables for field in table.fields}


def planned_contract_summary() -> dict[str, object]:
    """Return a serializable read-only summary for docs or future status helpers."""
    return {
        "version": LEDGER_V2_CONTRACT_VERSION,
        "tables": [
            {
                "name": table.name,
                "purpose": table.purpose,
                "fields": [
                    {
                        "name": field.name,
                        "value_type": field.value_type,
                        "required": field.required,
                        "purpose": field.purpose,
                    }
                    for field in table.fields
                ],
            }
            for table in PLANNED_LEDGER_V2_TABLES
        ],
    }
