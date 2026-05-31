# -*- coding: utf-8 -*-
"""Disabled-by-default ledger v2 migration scaffold tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

from src.services.portfolio_ledger_migration_guard import LEDGER_V2_MIGRATION_FLAG
from src.services.portfolio_ledger_v2_contract import planned_table_names
from src.storage import AccountSnapshot, DatabaseManager, PortfolioPosition, TradeJournal


def test_default_plan_is_blocked_and_dry_run():
    from src.services.portfolio_ledger_v2_migration import plan_ledger_v2_shadow_migration

    plan = plan_ledger_v2_shadow_migration(env={})

    assert plan.status == "blocked"
    assert plan.dry_run is True
    assert plan.will_write is False
    assert LEDGER_V2_MIGRATION_FLAG in plan.reason
    assert planned_table_names().issubset({table.name for table in plan.tables})
    assert all(statement.startswith("CREATE TABLE IF NOT EXISTS ") for statement in plan.ddl_statements)


def test_dry_run_does_not_create_shadow_tables(tmp_path: Path):
    from src.services.portfolio_ledger_v2_migration import plan_ledger_v2_shadow_migration

    engine = create_engine(f"sqlite:///{tmp_path / 'shadow.db'}")

    plan = plan_ledger_v2_shadow_migration(
        engine=engine,
        env={LEDGER_V2_MIGRATION_FLAG: "true"},
        dry_run=True,
        execute=False,
    )

    assert plan.status == "ready"
    assert plan.dry_run is True
    assert plan.will_write is False
    assert not set(inspect(engine).get_table_names()).intersection(planned_table_names())


def test_unopted_execution_request_is_blocked_without_database_mutation(tmp_path: Path):
    from src.services.portfolio_ledger_v2_migration import (
        PortfolioLedgerV2MigrationExecutionBlocked,
        plan_ledger_v2_shadow_migration,
    )

    engine = create_engine(f"sqlite:///{tmp_path / 'blocked.db'}")

    with pytest.raises(PortfolioLedgerV2MigrationExecutionBlocked):
        plan_ledger_v2_shadow_migration(
            engine=engine,
            env={},
            dry_run=False,
            execute=True,
        )

    assert not set(inspect(engine).get_table_names()).intersection(planned_table_names())


def test_shadow_schema_spec_matches_contract_and_account_scopes_corporate_actions():
    from src.services.portfolio_ledger_v2_migration import build_ledger_v2_shadow_schema_spec

    spec = build_ledger_v2_shadow_schema_spec()
    tables_by_name = {table.name: table for table in spec.tables}

    assert set(tables_by_name) == planned_table_names()
    corporate_actions = tables_by_name["portfolio_ledger_corporate_actions"]
    assert "account_uid" in {column.name for column in corporate_actions.columns}

    accounts = tables_by_name["portfolio_ledger_accounts"]
    account_fields = {column.name for column in accounts.columns}
    assert "custody_metadata_present" in account_fields
    assert "custody_reference_hash" in account_fields
    assert "hin" not in account_fields
    assert "account_number" not in account_fields


def test_shadow_schema_spec_has_no_secret_or_real_order_detail_columns():
    from src.services.portfolio_ledger_v2_migration import build_ledger_v2_shadow_schema_spec

    serialized = repr(build_ledger_v2_shadow_schema_spec()).lower()

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


def test_shadow_migration_module_is_not_registered_on_active_storage_metadata():
    from src.services import portfolio_ledger_v2_migration  # noqa: F401
    from src.storage import Base

    assert not set(Base.metadata.tables).intersection(planned_table_names())


def test_existing_v1_storage_tables_stay_unchanged(tmp_path: Path):
    from src.services.portfolio_ledger_v2_migration import plan_ledger_v2_shadow_migration

    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'v1.db'}")
    try:
        before_tables = set(inspect(db._engine).get_table_names())

        plan = plan_ledger_v2_shadow_migration(engine=db._engine, env={})

        after_tables = set(inspect(db._engine).get_table_names())
        assert plan.status == "blocked"
        assert before_tables == after_tables
        assert not after_tables.intersection(planned_table_names())

        with db.get_session() as session:
            assert session.query(AccountSnapshot).count() == 0
            assert session.query(PortfolioPosition).count() == 0
            assert session.query(TradeJournal).count() == 0
    finally:
        DatabaseManager.reset_instance()
