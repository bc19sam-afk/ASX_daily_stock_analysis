# -*- coding: utf-8 -*-
"""Read-only portfolio event facade API tests."""

from datetime import date, datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from api.app import create_app
from api.deps import get_database_manager
from src.storage import (
    AccountSnapshot,
    DatabaseManager,
    PaperPortfolioTrade,
    PortfolioPosition,
    TradeJournal,
)


def _make_client(tmp_path: Path):
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'portfolio_events.db'}")
    app = create_app(static_dir=tmp_path / "empty-static")
    app.dependency_overrides[get_database_manager] = lambda: db
    return TestClient(app), db, app


def _seed_events(db: DatabaseManager) -> None:
    with db.get_session() as session:
        session.add(
            PortfolioPosition(
                code="BHP.AX",
                name="BHP Group",
                quantity=4.0,
                avg_cost=25.0,
                market_value=104.0,
                current_price=26.0,
                weight=0.104313,
                unrealized_pnl=4.0,
                status="OPEN",
                opened_at=datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc),
                updated_at=datetime(2026, 5, 22, 9, 32, tzinfo=timezone.utc),
            )
        )
        session.add(
            AccountSnapshot(
                snapshot_date=date(2026, 5, 21),
                cash=897.0,
                equity_value=100.0,
                total_value=997.0,
                daily_pnl=-3.0,
                note="import applied; account_number=123456 HIN-001 should stay private",
                created_at=datetime(2026, 5, 21, 8, 0, tzinfo=timezone.utc),
            )
        )
        session.add(
            TradeJournal(
                query_id="dedup-secret-hash",
                code="BHP.AX",
                action_date=date(2026, 5, 20),
                action="OPEN",
                final_decision="BUY",
                current_weight=0.0,
                target_weight=0.1,
                delta_amount=103.0,
                current_quantity=0.0,
                target_quantity=4.0,
                current_price=25.0,
                available_cash_before=1000.0,
                available_cash_after=897.0,
                reason=(
                    "csv_import parser=generic_asx broker=SelfWealth account_label=Main "
                    "settlement_date=2026-05-22 custody_metadata_present=true HIN-001 account_number=123456"
                ),
                created_at=datetime(2026, 5, 21, 8, 1, tzinfo=timezone.utc),
            )
        )
        session.add(
            PaperPortfolioTrade(
                simulation_time=datetime(2026, 5, 22, 9, 30, tzinfo=timezone.utc),
                code="BHP.AX",
                action="ADD",
                analysis_status="PASS",
                executed=True,
                target_weight=0.2,
                target_quantity=6.0,
                before_quantity=4.0,
                after_quantity=6.0,
                price=26.0,
                cash_before=897.0,
                cash_after=845.0,
                reason="paper simulation from analysis result",
                created_at=datetime(2026, 5, 22, 9, 31, tzinfo=timezone.utc),
            )
        )
        session.commit()


def _table_counts(db: DatabaseManager) -> dict[str, int]:
    with db.get_session() as session:
        return {
            "snapshots": session.query(AccountSnapshot).count(),
            "journal": session.query(TradeJournal).count(),
            "paper_trades": session.query(PaperPortfolioTrade).count(),
            "positions": session.query(PortfolioPosition).count(),
        }


def test_portfolio_events_endpoint_returns_unified_read_only_events(tmp_path: Path):
    client, db, app = _make_client(tmp_path)
    _seed_events(db)
    before = _table_counts(db)

    response = client.get("/api/v1/portfolio-events", params={"page_size": 10})

    assert response.status_code == 200
    payload = response.json()
    assert payload["page"] == 1
    assert payload["page_size"] == 10
    assert payload["total"] == 4
    assert [item["source"] for item in payload["events"]] == [
        "portfolio",
        "paper_portfolio",
        "portfolio_import",
        "portfolio",
    ]

    position_event = payload["events"][0]
    assert position_event["event_type"] == "portfolio_position"
    assert position_event["code"] == "BHP.AX"
    assert position_event["status"] == "OPEN"
    assert position_event["quantity"] == 4.0
    assert position_event["price"] == 26.0
    assert position_event["equity"] == 104.0

    paper_event = payload["events"][1]
    assert paper_event["event_type"] == "paper_portfolio_trade"
    assert paper_event["code"] == "BHP.AX"
    assert paper_event["quantity"] == 2.0
    assert paper_event["price"] == 26.0
    assert paper_event["cash"] == 845.0
    assert paper_event["action"] == "ADD"

    import_event = payload["events"][2]
    assert import_event["event_type"] == "trade_journal"
    assert import_event["source"] == "portfolio_import"
    assert import_event["quantity"] == 4.0
    assert import_event["metadata"]["custody_metadata_present"] is True
    assert import_event["metadata"]["settlement_date"] == "2026-05-22"
    assert "HIN-001" not in str(import_event)
    assert "123456" not in str(import_event)
    assert "account_number" not in str(import_event)

    snapshot_event = payload["events"][3]
    assert snapshot_event["event_type"] == "account_snapshot"
    assert snapshot_event["cash"] == 897.0
    assert snapshot_event["equity"] == 100.0
    assert snapshot_event["total_value"] == 997.0
    assert "account_number" not in str(snapshot_event)
    assert _table_counts(db) == before
    app.dependency_overrides.clear()


def test_portfolio_events_filters_paginates_and_handles_empty_state(tmp_path: Path):
    client, db, app = _make_client(tmp_path)
    _seed_events(db)

    filtered = client.get(
        "/api/v1/portfolio-events",
        params={
            "source": "paper_portfolio",
            "event_type": "paper_portfolio_trade",
            "code": "bhp",
            "date_from": "2026-05-22",
            "date_to": "2026-05-22",
            "page": 1,
            "page_size": 1,
        },
    )

    assert filtered.status_code == 200
    payload = filtered.json()
    assert payload["total"] == 1
    assert payload["events"][0]["source"] == "paper_portfolio"

    empty = client.get(
        "/api/v1/portfolio-events",
        params={"event_type": "trade_journal", "code": "CBA.AX"},
    )

    assert empty.status_code == 200
    assert empty.json()["total"] == 0
    assert empty.json()["events"] == []
    app.dependency_overrides.clear()


def test_portfolio_events_code_filter_preserves_bare_us_symbols(tmp_path: Path):
    client, db, app = _make_client(tmp_path)
    with db.get_session() as session:
        session.add(
            PortfolioPosition(
                code="AAPL",
                name="Apple Inc.",
                quantity=2.0,
                avg_cost=180.0,
                market_value=370.0,
                current_price=185.0,
                status="OPEN",
                opened_at=datetime(2026, 5, 23, 8, 0, tzinfo=timezone.utc),
                updated_at=datetime(2026, 5, 23, 9, 0, tzinfo=timezone.utc),
            )
        )
        session.commit()

    response = client.get("/api/v1/portfolio-events", params={"code": "AAPL"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["events"][0]["code"] == "AAPL"
    assert payload["events"][0]["symbol"] == "AAPL"
    app.dependency_overrides.clear()
