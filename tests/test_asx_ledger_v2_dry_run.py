# -*- coding: utf-8 -*-
"""Ledger v2 dry-run transformer and dual-read comparison tests."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from api.app import create_app
from api.deps import get_database_manager
from scripts.manual_portfolio_workflows import HoldingInput, init_portfolio
from src.services.asx_ledger_v2_dry_run import AsxLedgerV2DryRunService
from src.storage import AccountSnapshot, DatabaseManager, PortfolioPosition, TradeJournal


SENSITIVE_MARKERS = (
    "HIN-001",
    "account_number",
    "123456",
    "broker_token",
    "real_order",
    "fill_id",
)


def _make_db(tmp_path: Path) -> DatabaseManager:
    DatabaseManager.reset_instance()
    return DatabaseManager(db_url=f"sqlite:///{tmp_path / 'ledger_v2_dry_run.db'}")


def _table_counts(db: DatabaseManager) -> dict[str, int]:
    with db.get_session() as session:
        return {
            "snapshots": session.query(AccountSnapshot).count(),
            "positions": session.query(PortfolioPosition).count(),
            "journal": session.query(TradeJournal).count(),
        }


def _seed_v1_buy_sell(db: DatabaseManager) -> None:
    with db.get_session() as session:
        session.add(
            AccountSnapshot(
                snapshot_date=date(2026, 5, 19),
                cash=1000.0,
                equity_value=0.0,
                total_value=1000.0,
                note="initial manual snapshot",
                created_at=datetime(2026, 5, 19, 8, 0, tzinfo=timezone.utc),
            )
        )
        session.add(
            TradeJournal(
                query_id="import-buy-hash",
                code="BHP.AX",
                action_date=date(2026, 5, 20),
                action="OPEN",
                final_decision="BUY",
                current_quantity=0.0,
                target_quantity=4.0,
                current_price=25.0,
                available_cash_before=1000.0,
                available_cash_after=897.0,
                reason=(
                    "csv_import parser=generic_asx settlement_date=2026-05-22 "
                    "currency=AUD fee=3.00 custody_metadata_present=true HIN-001"
                ),
                created_at=datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc),
            )
        )
        session.add(
            TradeJournal(
                query_id="import-sell-hash",
                code="BHP.AX",
                action_date=date(2026, 5, 21),
                action="REDUCE",
                final_decision="SELL",
                current_quantity=4.0,
                target_quantity=3.0,
                current_price=26.0,
                available_cash_before=897.0,
                available_cash_after=921.0,
                reason=(
                    "csv_import parser=generic_asx settlement_date=2026-05-25 "
                    "currency=AUD fee=2.00 custody_metadata_present=true HIN-001"
                ),
                created_at=datetime(2026, 5, 21, 8, 0, tzinfo=timezone.utc),
            )
        )
        session.add(
            PortfolioPosition(
                code="BHP.AX",
                name="BHP Group",
                quantity=3.0,
                avg_cost=25.75,
                current_price=26.0,
                market_value=78.0,
                weight=0.078078,
                status="OPEN",
                opened_at=datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc),
                updated_at=datetime(2026, 5, 21, 8, 1, tzinfo=timezone.utc),
            )
        )
        session.add(
            AccountSnapshot(
                snapshot_date=date(2026, 5, 21),
                cash=921.0,
                equity_value=78.0,
                total_value=999.0,
                note="updated_by_asx_csv_import HIN-001 account_number=123456",
                created_at=datetime(2026, 5, 21, 8, 2, tzinfo=timezone.utc),
            )
        )
        session.commit()


def test_trade_rows_convert_to_stable_dry_run_candidates_without_writing_db(tmp_path: Path):
    db = _make_db(tmp_path)
    _seed_v1_buy_sell(db)
    before = _table_counts(db)

    result = AsxLedgerV2DryRunService(db).build_dry_run()
    repeat = AsxLedgerV2DryRunService(db).build_dry_run()

    assert result["is_dry_run"] is True
    assert result["will_write"] is False
    assert result["status"] == "available"
    trade_candidates = [
        item for item in result["candidates"] if item["event_type"] in {"trade_buy", "trade_sell"}
    ]
    assert len(trade_candidates) == 2
    assert all(item["is_dry_run"] is True for item in trade_candidates)
    assert [item["source_hash"] for item in trade_candidates] == [
        item["source_hash"]
        for item in repeat["candidates"]
        if item["event_type"] in {"trade_buy", "trade_sell"}
    ]
    assert all(len(item["source_hash"]) == 64 for item in trade_candidates)
    assert trade_candidates[0]["source_event_id"].startswith("trade_journal:import-buy-hash:")
    assert trade_candidates[1]["source_event_id"].startswith("trade_journal:import-sell-hash:")
    assert trade_candidates[0]["source_event_id"] != trade_candidates[1]["source_event_id"]

    buy = next(item for item in trade_candidates if item["event_type"] == "trade_buy")
    sell = next(item for item in trade_candidates if item["event_type"] == "trade_sell")
    assert buy["symbol"] == "BHP.AX"
    assert buy["trade_date"] == "2026-05-20"
    assert buy["settlement_date"] == "2026-05-22"
    assert buy["quantity_delta"] == 4.0
    assert buy["cash_delta"] == -103.0
    assert buy["currency"] == "AUD"
    assert buy["fees"]["total"] == 3.0
    assert buy["tax"]["status"] == "placeholder"
    assert buy["franking"]["status"] == "placeholder"
    assert sell["quantity_delta"] == -1.0
    assert sell["cash_delta"] == 24.0
    assert sell["fees"]["total"] == 2.0

    comparison = result["comparison"]
    assert comparison["matched_count"] == 2
    assert comparison["mismatched_count"] == 0
    assert comparison["missing_count"] == 0
    assert comparison["unsupported_count"] >= 1
    assert _table_counts(db) == before
    serialized = str(result)
    assert not any(marker in serialized for marker in SENSITIVE_MARKERS)
    DatabaseManager.reset_instance()


def test_unsupported_rows_and_dividend_franking_placeholders_are_explicit(tmp_path: Path):
    db = _make_db(tmp_path)
    init_portfolio(
        db,
        cash=1000.0,
        holdings=[HoldingInput(code="BHP.AX", quantity=4.0, avg_cost=25.0)],
    )
    with db.get_session() as session:
        session.add(
            TradeJournal(
                query_id="manual-dividend-row",
                code="BHP.AX",
                action_date=date(2026, 5, 24),
                action="DIVIDEND",
                final_decision="DIVIDEND",
                current_quantity=4.0,
                target_quantity=4.0,
                current_price=25.0,
                available_cash_before=1000.0,
                available_cash_after=1012.0,
                reason="HIN-001 account_number=123456",
            )
        )
        session.commit()

    result = AsxLedgerV2DryRunService(db).build_dry_run()

    unsupported = [
        item
        for item in result["candidates"]
        if item["source_event_id"].startswith("trade_journal:")
        and item["event_type"] == "unsupported"
    ]
    assert unsupported
    assert any("unsupported" in warning.lower() for warning in unsupported[0]["warnings"])
    assert unsupported[0]["franking"]["status"] == "unsupported"
    assert any("dividend" in warning.lower() for warning in unsupported[0]["warnings"])
    assert any("franking" in warning.lower() for warning in unsupported[0]["warnings"])
    assert any("cash-only" in warning.lower() for warning in result["comparison"]["warnings"])
    serialized = str(result)
    assert not any(marker in serialized for marker in SENSITIVE_MARKERS)
    DatabaseManager.reset_instance()


def test_income_placeholders_normalize_aud_dividend_and_franking_without_cash_or_tax_rows(tmp_path: Path):
    db = _make_db(tmp_path)
    init_portfolio(
        db,
        cash=1000.0,
        holdings=[HoldingInput(code="BHP.AX", quantity=4.0, avg_cost=25.0)],
    )
    with db.get_session() as session:
        session.add(
            TradeJournal(
                query_id="income-dividend-row",
                code="BHP.AX",
                action_date=date(2026, 5, 24),
                action="DIVIDEND",
                final_decision="DIVIDEND",
                current_quantity=4.0,
                target_quantity=4.0,
                current_price=25.0,
                available_cash_before=1000.0,
                available_cash_after=1012.0,
                reason=(
                    "event_type=dividend currency=AUD dividend=12.34 "
                    "franking_credit=5.67 custody_metadata_present=true"
                ),
            )
        )
        session.commit()
    before = _table_counts(db)

    result = AsxLedgerV2DryRunService(db).build_dry_run()
    candidate = next(
        item
        for item in result["candidates"]
        if item["source_event_id"].startswith("trade_journal:income-dividend-row")
    )

    assert candidate["event_type"] == "unsupported"
    assert candidate["currency"] == "AUD"
    assert candidate["income"]["status"] == "partial_placeholder"
    assert candidate["income"]["income_type"] == "dividend"
    assert candidate["income"]["cash_amount"] == 12.34
    assert candidate["income"]["currency"] == "AUD"
    assert candidate["income"]["supported_in_dry_run"] is False
    assert candidate["income"]["will_create_cash_event"] is False
    assert candidate["corporate_action"]["status"] == "none"
    assert candidate["corporate_action"]["action_type"] is None
    assert candidate["corporate_action"]["requires_manual_review"] is False
    assert candidate["franking"]["status"] == "placeholder"
    assert candidate["franking"]["amount"] == 5.67
    assert candidate["franking"]["currency"] == "AUD"
    assert candidate["franking"]["supported_in_dry_run"] is False
    assert candidate["tax"]["status"] == "unsupported"
    assert any("franking" in warning.lower() for warning in candidate["warnings"])
    assert any("tax return" in warning.lower() for warning in candidate["warnings"])
    assert _table_counts(db) == before
    serialized = str(result)
    assert not any(marker in serialized for marker in SENSITIVE_MARKERS)
    DatabaseManager.reset_instance()


def test_corporate_action_placeholders_warn_for_drp_split_consolidation_and_return_of_capital(tmp_path: Path):
    db = _make_db(tmp_path)
    init_portfolio(
        db,
        cash=1000.0,
        holdings=[HoldingInput(code="BHP.AX", quantity=4.0, avg_cost=25.0)],
    )
    with db.get_session() as session:
        for index, action_type in enumerate(("DRP", "split", "consolidation", "return_of_capital"), start=1):
            session.add(
                TradeJournal(
                    query_id=f"corporate-action-{index}",
                    code="BHP.AX",
                    action_date=date(2026, 6, index),
                    action=action_type,
                    final_decision=action_type,
                    current_quantity=4.0,
                    target_quantity=4.0,
                    current_price=25.0,
                    available_cash_before=1000.0,
                    available_cash_after=1000.0,
                    reason=(
                        f"corporate_action_type={action_type} currency=AUD "
                        "ratio=2.0 cash_amount=1.23 custody_metadata_present=true"
                    ),
                )
            )
        session.commit()

    result = AsxLedgerV2DryRunService(db).build_dry_run()
    candidates = [
        item
        for item in result["candidates"]
        if item["source_event_id"].startswith("trade_journal:corporate-action-")
    ]
    placeholders = [item["corporate_action"] for item in candidates]

    assert [item["action_type"] for item in placeholders] == [
        "drp",
        "split",
        "consolidation",
        "return_of_capital",
    ]
    for placeholder in placeholders:
        assert placeholder["status"] == "unsupported_placeholder"
        assert placeholder["currency"] == "AUD"
        assert placeholder["supported_in_dry_run"] is False
        assert placeholder["will_adjust_quantity"] is False
        assert placeholder["will_adjust_cost_base"] is False
        assert placeholder["requires_manual_review"] is True
    assert all(item["income"]["status"] == "none" for item in candidates)
    assert any("corporate action" in warning.lower() for warning in result["warnings"])
    serialized = str(result)
    assert not any(marker in serialized for marker in SENSITIVE_MARKERS)
    DatabaseManager.reset_instance()


def test_event_aliases_are_not_unknown_and_feed_source_identity(tmp_path: Path):
    db = _make_db(tmp_path)
    init_portfolio(
        db,
        cash=1000.0,
        holdings=[HoldingInput(code="BHP.AX", quantity=4.0, avg_cost=25.0)],
    )
    with db.get_session() as session:
        for action_type in ("split", "consolidation"):
            session.add(
                TradeJournal(
                    query_id="same-action-alias-row",
                    code="BHP.AX",
                    action_date=date(2026, 6, 7),
                    action="HOLD",
                    final_decision="HOLD",
                    current_quantity=4.0,
                    target_quantity=4.0,
                    current_price=25.0,
                    available_cash_before=1000.0,
                    available_cash_after=1000.0,
                    reason=f"action_type={action_type} currency=AUD ratio=2.0",
                )
            )
        session.commit()

    result = AsxLedgerV2DryRunService(db).build_dry_run()
    candidates = [
        item
        for item in result["candidates"]
        if item["source_event_id"].startswith("trade_journal:same-action-alias-row")
    ]

    assert [item["corporate_action"]["action_type"] for item in candidates] == ["split", "consolidation"]
    assert all(item["income"]["status"] == "none" for item in candidates)
    assert all(item["corporate_action"]["status"] == "unsupported_placeholder" for item in candidates)
    assert len({item["source_event_id"] for item in candidates}) == 2
    assert len({item["source_hash"] for item in candidates}) == 2
    DatabaseManager.reset_instance()


def test_unknown_income_or_corporate_action_is_not_reported_as_supported(tmp_path: Path):
    db = _make_db(tmp_path)
    init_portfolio(
        db,
        cash=1000.0,
        holdings=[HoldingInput(code="BHP.AX", quantity=4.0, avg_cost=25.0)],
    )
    with db.get_session() as session:
        session.add(
            TradeJournal(
                query_id="unknown-action-row",
                code="BHP.AX",
                action_date=date(2026, 6, 10),
                action="BONUS_ENTITLEMENT",
                final_decision="BONUS_ENTITLEMENT",
                current_quantity=4.0,
                target_quantity=4.0,
                current_price=25.0,
                available_cash_before=1000.0,
                available_cash_after=1000.0,
                reason="event_type=bonus_entitlement currency=AUD custody_metadata_present=true",
            )
        )
        session.commit()

    result = AsxLedgerV2DryRunService(db).build_dry_run()
    candidate = next(
        item
        for item in result["candidates"]
        if item["source_event_id"].startswith("trade_journal:unknown-action-row")
    )

    assert candidate["event_type"] == "unsupported"
    assert candidate["income"]["status"] == "unsupported"
    assert candidate["income"]["income_type"] == "unknown"
    assert candidate["income"]["supported_in_dry_run"] is False
    assert candidate["corporate_action"]["status"] == "unsupported"
    assert candidate["corporate_action"]["action_type"] == "unknown"
    assert candidate["corporate_action"]["supported_in_dry_run"] is False
    assert any("unknown" in warning.lower() for warning in candidate["warnings"])
    serialized = str(candidate)
    assert not any(marker in serialized for marker in SENSITIVE_MARKERS)
    DatabaseManager.reset_instance()


def test_dual_read_comparison_reports_mismatched_and_missing_holdings(tmp_path: Path):
    db = _make_db(tmp_path)
    _seed_v1_buy_sell(db)
    db.upsert_portfolio_position(
        code="BHP.AX",
        name="BHP Group",
        quantity=5.0,
        avg_cost=25.0,
        current_price=25.0,
        weight=0.1,
        market_value=125.0,
    )
    db.upsert_portfolio_position(
        code="CBA.AX",
        name="CBA",
        quantity=2.0,
        avg_cost=100.0,
        current_price=100.0,
        weight=0.2,
        market_value=200.0,
    )

    comparison = AsxLedgerV2DryRunService(db).build_dry_run()["comparison"]

    assert comparison["matched_count"] == 1
    assert comparison["mismatched_count"] == 1
    assert comparison["missing_count"] == 1
    assert any(item["symbol"] == "BHP.AX" for item in comparison["mismatched"])
    assert any(item["symbol"] == "CBA.AX" for item in comparison["missing"])
    DatabaseManager.reset_instance()


def test_shadow_read_diagnostics_groups_mismatches_missing_unsupported_and_warnings(tmp_path: Path):
    db = _make_db(tmp_path)
    _seed_v1_buy_sell(db)
    db.upsert_portfolio_position(
        code="BHP.AX",
        name="BHP Group",
        quantity=5.0,
        avg_cost=25.0,
        current_price=25.0,
        weight=0.1,
        market_value=125.0,
    )
    db.upsert_portfolio_position(
        code="CBA.AX",
        name="CBA",
        quantity=2.0,
        avg_cost=100.0,
        current_price=100.0,
        weight=0.2,
        market_value=200.0,
    )
    before = _table_counts(db)

    diagnostics = AsxLedgerV2DryRunService(db).build_diagnostics()

    assert diagnostics["status"] == "available"
    assert diagnostics["mode"] == "ledger_v2_shadow_read_diagnostics"
    assert diagnostics["is_dry_run"] is True
    assert diagnostics["will_write"] is False
    assert diagnostics["summary"]["v1_authoritative"] is True
    assert diagnostics["summary"]["requires_manual_review"] is True
    assert diagnostics["summary"]["mismatched_count"] == 1
    assert diagnostics["summary"]["missing_count"] == 1
    assert diagnostics["summary"]["unsupported_count"] >= 1
    assert diagnostics["summary"]["warning_count"] >= 2
    groups = {item["group"]: item for item in diagnostics["summary"]["groups"]}
    assert groups["mismatched"]["count"] == 1
    assert groups["missing"]["count"] == 1
    assert groups["unsupported"]["count"] >= 1
    assert groups["warnings"]["count"] >= 2
    assert groups["unsupported"]["severity"] == "manual_review"
    assert any(item["symbol"] == "BHP.AX" for item in diagnostics["details"]["mismatched"])
    assert any(item["symbol"] == "CBA.AX" for item in diagnostics["details"]["missing"])
    assert diagnostics["details"]["unsupported"][0]["event_type"] == "unsupported"
    assert diagnostics["details"]["unsupported"][0]["reason"] == "unsupported_or_cash_only_placeholder"
    assert any("v1 remains authoritative" in item["message"] for item in diagnostics["details"]["warnings"])
    assert diagnostics["boundaries"]["v1_authoritative"] is True
    assert diagnostics["links"]["dry_run"] == "/api/v1/portfolio-events/ledger-v2/dry-run"
    assert _table_counts(db) == before
    serialized = str(diagnostics)
    assert not any(marker in serialized for marker in SENSITIVE_MARKERS)
    DatabaseManager.reset_instance()


def test_rehearsal_report_summarizes_shadow_diagnostics_for_manual_review(tmp_path: Path):
    db = _make_db(tmp_path)
    _seed_v1_buy_sell(db)
    db.upsert_portfolio_position(
        code="BHP.AX",
        name="BHP Group",
        quantity=5.0,
        avg_cost=25.0,
        current_price=25.0,
        weight=0.1,
        market_value=125.0,
    )
    db.upsert_portfolio_position(
        code="CBA.AX",
        name="CBA",
        quantity=2.0,
        avg_cost=100.0,
        current_price=100.0,
        weight=0.2,
        market_value=200.0,
    )
    with db.get_session() as session:
        session.add(
            TradeJournal(
                query_id="income-dividend-row",
                code="BHP.AX",
                action_date=date(2026, 5, 24),
                action="DIVIDEND",
                final_decision="DIVIDEND",
                current_quantity=4.0,
                target_quantity=4.0,
                current_price=25.0,
                available_cash_before=1000.0,
                available_cash_after=1012.0,
                reason=(
                    "event_type=dividend currency=AUD dividend=12.34 "
                    "franking_credit=5.67 custody_metadata_present=true HIN-001 account_number=123456"
                ),
            )
        )
        session.add(
            TradeJournal(
                query_id="corporate-action-row",
                code="BHP.AX",
                action_date=date(2026, 6, 1),
                action="SPLIT",
                final_decision="SPLIT",
                current_quantity=4.0,
                target_quantity=4.0,
                current_price=25.0,
                available_cash_before=1000.0,
                available_cash_after=1000.0,
                reason="corporate_action_type=split currency=AUD ratio=2.0 custody_metadata_present=true",
            )
        )
        session.commit()
    before = _table_counts(db)

    report = AsxLedgerV2DryRunService(db).build_rehearsal_report()

    assert report["status"] == "available"
    assert report["mode"] == "ledger_v2_rehearsal_report"
    assert report["is_dry_run"] is True
    assert report["will_write"] is False
    assert report["v1_authoritative"] is True
    assert report["manual_review_required"] is True
    assert report["readiness"]["non_cutover_ready"] is True
    assert "not migration evidence" in report["readiness"]["not_migration_evidence"].lower()
    assert "v1 remains authoritative" in report["readiness"]["authority_wording"].lower()
    assert report["source_summary"]["dry_run"]["candidate_count"] >= 4
    assert report["source_summary"]["diagnostics"]["mode"] == "ledger_v2_shadow_read_diagnostics"
    assert report["counts"]["matched"] == 1
    assert report["counts"]["mismatched"] == 1
    assert report["counts"]["missing"] == 1
    assert report["counts"]["unsupported"] >= 3
    assert report["counts"]["warnings"] >= 2
    assert report["top_mismatch_categories"][0]["category"] in {"holding", "cash"}
    assert report["unsupported_placeholder_summary"]["total"] >= 3
    assert report["unsupported_placeholder_summary"]["income_partial"] >= 1
    assert report["unsupported_placeholder_summary"]["corporate_action_unsupported"] >= 1
    assert report["details"]["mismatched"][0]["type"] == "holding"
    assert report["links"]["dry_run"] == "/api/v1/portfolio-events/ledger-v2/dry-run"
    assert report["links"]["diagnostics"] == "/api/v1/portfolio-events/ledger-v2/diagnostics"
    assert _table_counts(db) == before
    serialized = str(report)
    assert not any(marker in serialized for marker in SENSITIVE_MARKERS)
    DatabaseManager.reset_instance()


def test_dual_read_comparison_reports_dry_run_only_holdings(tmp_path: Path):
    db = _make_db(tmp_path)
    with db.get_session() as session:
        session.add(
            AccountSnapshot(
                snapshot_date=date(2026, 5, 19),
                cash=1000.0,
                equity_value=0.0,
                total_value=1000.0,
                created_at=datetime(2026, 5, 19, 8, 0, tzinfo=timezone.utc),
            )
        )
        session.add(
            AccountSnapshot(
                snapshot_date=date(2026, 5, 20),
                cash=897.0,
                equity_value=0.0,
                total_value=897.0,
                created_at=datetime(2026, 5, 20, 8, 2, tzinfo=timezone.utc),
            )
        )
        session.add(
            TradeJournal(
                query_id="v2-only-buy",
                code="BHP.AX",
                action_date=date(2026, 5, 20),
                action="OPEN",
                final_decision="BUY",
                current_quantity=0.0,
                target_quantity=4.0,
                current_price=25.0,
                available_cash_before=1000.0,
                available_cash_after=897.0,
                reason="csv_import settlement_date=2026-05-22 currency=AUD fee=3.00",
                created_at=datetime(2026, 5, 20, 8, 1, tzinfo=timezone.utc),
            )
        )
        session.commit()

    comparison = AsxLedgerV2DryRunService(db).build_dry_run()["comparison"]

    assert comparison["matched_count"] == 1
    assert comparison["mismatched_count"] == 1
    assert comparison["missing_count"] == 0
    assert any(
        item["type"] == "dry_run_only_holding" and item["symbol"] == "BHP.AX"
        for item in comparison["mismatched"]
    )
    DatabaseManager.reset_instance()


def test_repeated_manual_trade_query_ids_keep_unique_stable_source_event_ids(tmp_path: Path):
    db = _make_db(tmp_path)
    with db.get_session() as session:
        session.add(
            AccountSnapshot(
                snapshot_date=date(2026, 5, 19),
                cash=1000.0,
                equity_value=0.0,
                total_value=1000.0,
                created_at=datetime(2026, 5, 19, 8, 0, tzinfo=timezone.utc),
            )
        )
        for index, code in enumerate(("BHP.AX", "CBA.AX"), start=1):
            session.add(
                TradeJournal(
                    query_id="manual_trade_workflow",
                    code=code,
                    action_date=date(2026, 5, 20 + index),
                    action="OPEN",
                    final_decision="BUY",
                    current_quantity=0.0,
                    target_quantity=float(index),
                    current_price=25.0,
                    available_cash_before=1000.0 - (index - 1) * 25.0,
                    available_cash_after=1000.0 - index * 25.0,
                    reason="manual trade settlement_date=2026-05-25 currency=AUD fee=0.00",
                    created_at=datetime(2026, 5, 20 + index, 8, 0, tzinfo=timezone.utc),
                )
            )
        session.commit()

    result = AsxLedgerV2DryRunService(db).build_dry_run()
    trade_ids = [
        item["source_event_id"]
        for item in result["candidates"]
        if item["event_type"] == "trade_buy"
    ]

    assert len(trade_ids) == 2
    assert len(set(trade_ids)) == 2
    assert all(source_id.startswith("trade_journal:manual_trade_workflow:") for source_id in trade_ids)
    assert trade_ids == [
        item["source_event_id"]
        for item in AsxLedgerV2DryRunService(db).build_dry_run()["candidates"]
        if item["event_type"] == "trade_buy"
    ]
    DatabaseManager.reset_instance()


def test_ledger_v2_dry_run_endpoint_is_read_only(tmp_path: Path):
    db = _make_db(tmp_path)
    _seed_v1_buy_sell(db)
    before = _table_counts(db)
    app = create_app(static_dir=tmp_path / "empty-static")
    app.dependency_overrides[get_database_manager] = lambda: db

    response = TestClient(app).get("/api/v1/portfolio-events/ledger-v2/dry-run")

    assert response.status_code == 200
    payload = response.json()
    assert payload["is_dry_run"] is True
    assert payload["will_write"] is False
    assert payload["comparison"]["matched_count"] == 2
    assert payload["candidates"][0]["source_event_id"].startswith("trade_journal:")
    assert _table_counts(db) == before
    app.dependency_overrides.clear()
    DatabaseManager.reset_instance()


def test_ledger_v2_diagnostics_endpoint_is_read_only_and_redacted(tmp_path: Path):
    db = _make_db(tmp_path)
    _seed_v1_buy_sell(db)
    before = _table_counts(db)
    app = create_app(static_dir=tmp_path / "empty-static")
    app.dependency_overrides[get_database_manager] = lambda: db

    response = TestClient(app).get("/api/v1/portfolio-events/ledger-v2/diagnostics")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "ledger_v2_shadow_read_diagnostics"
    assert payload["is_dry_run"] is True
    assert payload["will_write"] is False
    assert payload["summary"]["unsupported_count"] >= 1
    assert payload["details"]["unsupported"]
    assert _table_counts(db) == before
    serialized = str(payload)
    assert not any(marker in serialized for marker in SENSITIVE_MARKERS)
    app.dependency_overrides.clear()
    DatabaseManager.reset_instance()
