# -*- coding: utf-8 -*-
"""Disabled-by-default ledger v2 shadow migration scaffold.

This module can describe the planned shadow schema and produce DDL, but it
does not attach SQLAlchemy models to the active storage metadata. Execution is
blocked unless a future caller explicitly opts in through the migration guard.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

from sqlalchemy.engine import Engine
from sqlalchemy import text

from src.services.portfolio_ledger_migration_guard import (
    PortfolioLedgerMigrationBlocked,
    PortfolioLedgerMigrationGuard,
)
from src.services.portfolio_ledger_v2_contract import (
    LEDGER_V2_CONTRACT_VERSION,
    PLANNED_LEDGER_V2_TABLES,
    PlannedLedgerField,
    PlannedLedgerTable,
)

_SAFE_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")

_SQL_TYPE_BY_CONTRACT_TYPE = {
    "boolean": "INTEGER",
    "date": "TEXT",
    "datetime": "TEXT",
    "decimal": "NUMERIC",
    "integer": "INTEGER",
    "string": "TEXT",
    "text": "TEXT",
}

_PRIMARY_KEY_FIELDS = {
    "account_uid",
    "ledger_trade_uid",
    "cash_event_uid",
    "corporate_action_uid",
    "lot_uid",
    "snapshot_uid",
    "franking_credit_uid",
    "settlement_uid",
    "audit_event_uid",
    "idempotency_key_hash",
}


class PortfolioLedgerV2MigrationExecutionBlocked(RuntimeError):
    """Raised when a shadow migration request is not explicitly allowed."""


@dataclass(frozen=True)
class LedgerV2ShadowColumnSpec:
    name: str
    sql_type: str
    nullable: bool
    purpose: str
    primary_key: bool = False
    references: Optional[str] = None


@dataclass(frozen=True)
class LedgerV2ShadowTableSpec:
    name: str
    purpose: str
    columns: tuple[LedgerV2ShadowColumnSpec, ...]


@dataclass(frozen=True)
class LedgerV2ShadowSchemaSpec:
    version: str
    tables: tuple[LedgerV2ShadowTableSpec, ...]


@dataclass(frozen=True)
class LedgerV2ShadowMigrationPlan:
    status: str
    dry_run: bool
    will_write: bool
    reason: str
    guard: dict[str, object]
    tables: tuple[LedgerV2ShadowTableSpec, ...]
    ddl_statements: tuple[str, ...]


def build_ledger_v2_shadow_schema_spec(
    tables: Iterable[PlannedLedgerTable] = PLANNED_LEDGER_V2_TABLES,
) -> LedgerV2ShadowSchemaSpec:
    """Build a side-effect-free shadow schema spec from the v2 contract."""
    return LedgerV2ShadowSchemaSpec(
        version=LEDGER_V2_CONTRACT_VERSION,
        tables=tuple(_shadow_table_from_contract(table) for table in tables),
    )


def render_ledger_v2_shadow_schema_sql(
    spec: Optional[LedgerV2ShadowSchemaSpec] = None,
) -> tuple[str, ...]:
    """Render CREATE TABLE statements for the shadow schema spec."""
    schema = spec or build_ledger_v2_shadow_schema_spec()
    return tuple(_render_create_table(table) for table in schema.tables)


def plan_ledger_v2_shadow_migration(
    *,
    engine: Optional[Engine] = None,
    env: Optional[Mapping[str, str]] = None,
    dry_run: bool = True,
    execute: bool = False,
) -> LedgerV2ShadowMigrationPlan:
    """Return a migration plan, and only execute when explicitly opted in.

    Defaults are intentionally non-mutating. Supplying an engine is safe while
    ``dry_run`` and ``execute`` remain at their defaults.
    """
    spec = build_ledger_v2_shadow_schema_spec()
    ddl_statements = render_ledger_v2_shadow_schema_sql(spec)
    guard = PortfolioLedgerMigrationGuard(env=env)
    status = guard.status()
    guard_payload = status.to_dict()

    if execute and dry_run:
        raise PortfolioLedgerV2MigrationExecutionBlocked(
            "Ledger v2 shadow migration execution requires dry_run=False."
        )
    if execute and engine is None:
        raise PortfolioLedgerV2MigrationExecutionBlocked(
            "Ledger v2 shadow migration execution requires an explicit database engine."
        )
    if execute:
        try:
            guard.require_enabled()
        except PortfolioLedgerMigrationBlocked as exc:
            raise PortfolioLedgerV2MigrationExecutionBlocked(str(exc)) from exc

        with engine.begin() as conn:
            for statement in ddl_statements:
                conn.execute(text(statement))
        return LedgerV2ShadowMigrationPlan(
            status="executed",
            dry_run=False,
            will_write=True,
            reason=status.reason,
            guard=guard_payload,
            tables=spec.tables,
            ddl_statements=ddl_statements,
        )

    return LedgerV2ShadowMigrationPlan(
        status="ready" if status.enabled else "blocked",
        dry_run=True,
        will_write=False,
        reason=status.reason,
        guard=guard_payload,
        tables=spec.tables,
        ddl_statements=ddl_statements,
    )


def _shadow_table_from_contract(table: PlannedLedgerTable) -> LedgerV2ShadowTableSpec:
    _safe_identifier(table.name)
    return LedgerV2ShadowTableSpec(
        name=table.name,
        purpose=table.purpose,
        columns=tuple(_shadow_column_from_contract(table.name, field) for field in table.fields),
    )


def _shadow_column_from_contract(
    table_name: str,
    field: PlannedLedgerField,
) -> LedgerV2ShadowColumnSpec:
    name = _safe_identifier(field.name)
    sql_type = _SQL_TYPE_BY_CONTRACT_TYPE[field.value_type]
    primary_key = name in _PRIMARY_KEY_FIELDS and not (
        name == "account_uid" and table_name != "portfolio_ledger_accounts"
    )
    references = (
        "portfolio_ledger_accounts(account_uid)"
        if name == "account_uid" and table_name != "portfolio_ledger_accounts"
        else None
    )
    return LedgerV2ShadowColumnSpec(
        name=name,
        sql_type=sql_type,
        nullable=not field.required and not primary_key,
        purpose=field.purpose,
        primary_key=primary_key,
        references=references,
    )


def _render_create_table(table: LedgerV2ShadowTableSpec) -> str:
    column_sql = ",\n    ".join(_render_column(column) for column in table.columns)
    return f"CREATE TABLE IF NOT EXISTS {table.name} (\n    {column_sql}\n);"


def _render_column(column: LedgerV2ShadowColumnSpec) -> str:
    parts: list[str] = [column.name, column.sql_type]
    if column.primary_key:
        parts.append("PRIMARY KEY")
    if not column.nullable:
        parts.append("NOT NULL")
    if column.references is not None:
        parts.append(f"REFERENCES {column.references}")
    return " ".join(parts)


def _safe_identifier(name: str) -> str:
    if not _SAFE_IDENTIFIER.match(name):
        raise ValueError(f"Unsafe ledger v2 schema identifier: {name!r}")
    return name
