# -*- coding: utf-8 -*-
"""Ledger v2 planning contract and migration guard tests."""

from __future__ import annotations

import pytest

from src.services.portfolio_ledger_migration_guard import (
    LEDGER_V2_MIGRATION_FLAG,
    PortfolioLedgerMigrationBlocked,
    PortfolioLedgerMigrationGuard,
    get_ledger_v2_migration_status,
)
from src.services.portfolio_ledger_v2_contract import (
    LEDGER_V2_CONTRACT_VERSION,
    PLANNED_LEDGER_V2_TABLES,
    PlannedLedgerTable,
    planned_field_names,
    planned_table_names,
)


def test_v2_contract_names_core_tables_and_field_plans():
    assert LEDGER_V2_CONTRACT_VERSION == "portfolio-ledger-v2-plan"

    table_names = planned_table_names()
    assert {
        "portfolio_ledger_accounts",
        "portfolio_ledger_trades",
        "portfolio_ledger_cash_events",
        "portfolio_ledger_corporate_actions",
        "portfolio_ledger_lots",
        "portfolio_ledger_snapshots",
        "portfolio_ledger_franking_credits",
        "portfolio_ledger_settlements",
        "portfolio_ledger_audit_log",
        "portfolio_ledger_idempotency_keys",
    }.issubset(table_names)

    field_names = planned_field_names()
    for expected in (
        "account_label",
        "trade_date",
        "cash_amount",
        "corporate_action_type",
        "lot_quantity",
        "snapshot_date",
        "franking_credit_amount",
        "settlement_date",
        "audit_actor",
        "idempotency_key_hash",
    ):
        assert expected in field_names


def test_corporate_actions_are_account_scoped_for_multi_account_replay():
    corporate_actions = _planned_table("portfolio_ledger_corporate_actions")

    assert "account_uid" in {field.name for field in corporate_actions.fields}


def test_migration_guard_defaults_to_disabled():
    status = get_ledger_v2_migration_status(env={})

    assert status.enabled is False
    assert status.flag_name == LEDGER_V2_MIGRATION_FLAG
    assert "disabled" in status.reason.lower()
    assert "explicit" in status.reason.lower()


def test_migration_guard_blocks_execution_without_explicit_flag():
    guard = PortfolioLedgerMigrationGuard(env={})

    with pytest.raises(PortfolioLedgerMigrationBlocked) as exc:
        guard.require_enabled()

    assert LEDGER_V2_MIGRATION_FLAG in str(exc.value)


def test_migration_guard_allows_execution_only_with_explicit_flag():
    guard = PortfolioLedgerMigrationGuard(env={LEDGER_V2_MIGRATION_FLAG: "true"})

    status = guard.status()

    assert status.enabled is True
    assert "explicitly enabled" in status.reason.lower()
    assert guard.require_enabled() == status


def test_contract_does_not_plan_secret_or_real_execution_detail_fields():
    serialized = repr(PLANNED_LEDGER_V2_TABLES).lower()

    forbidden_markers = {
        "api_key",
        "auth_token",
        "password",
        "secret",
        "credential",
        "hin_raw",
        "raw_hin",
        "account_number",
        "account_credentials",
        "broker_token",
        "order_id",
        "fill_id",
        "fill_details",
        "real_order",
    }
    assert not any(marker in serialized for marker in forbidden_markers)


def _planned_table(name: str) -> PlannedLedgerTable:
    for table in PLANNED_LEDGER_V2_TABLES:
        if table.name == name:
            return table
    raise AssertionError(f"Missing planned table: {name}")
