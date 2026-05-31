# ASX Portfolio Ledger V2 Plan

## Purpose

Ledger v2 is a planned event-oriented portfolio ledger for ASX/AU/US manual
review workflows. PR6 is only the schema plan, declarative contract, and
default-off migration guard. It does not create tables, migrate data, expose a
mutation endpoint, or replace current portfolio overview, ASX CSV import, paper
portfolio, workbench, alert-rule, or review-journal behavior.

## Goals

- Define a stable ledger v2 vocabulary before adding storage.
- Preserve the current human-in-the-loop product boundary.
- Make ASX/AUD handling first class while keeping AU/US extension points.
- Separate trades, cash, lots, settlements, franking credits, corporate
  actions, snapshots, audit rows, and idempotency keys.
- Keep dual-read and rollback boundaries explicit before any database work.
- Provide a default-off guard that future migration runners must call.

## Non-Goals

- No production database migration.
- No SQLAlchemy model additions or storage schema changes.
- No broker connection, real-account read/write, order submission, automatic
  execution, notification worker change, or alert worker change.
- No replacement for current `get_portfolio_overview`, ASX CSV import, paper
  portfolio, workbench, or portfolio event facade behavior.
- No persistence of API keys, broker credentials, HIN originals, account
  numbers, real order details, or fill confirmations.

## Current Baseline

Current portfolio state is snapshot-oriented:

- `portfolio_positions` holds the current position per symbol.
- `account_snapshots` holds daily cash/equity/total snapshots.
- `trade_journal` records manual or import-driven trade journal entries.
- Paper portfolio tables are independent simulation state.
- `portfolio_events` is a read-only facade over existing tables.

Ledger v2 should adapt this baseline instead of overwriting it.

## Planned Tables

The executable contract lives in
`src/services/portfolio_ledger_v2_contract.py`. The planned tables are:

- `portfolio_ledger_accounts`: sanitized account labels, market scope, base
  currency, custody metadata presence, and review status.
- `portfolio_ledger_trades`: normalized buy/sell trade events with trade date,
  settlement date, symbol, market, currency, quantity, price, brokerage, GST,
  fees, source-row digest, and manual review status.
- `portfolio_ledger_cash_events`: deposits, withdrawals, dividends, fees, tax,
  and settlement cash movements.
- `portfolio_ledger_corporate_actions`: splits, DRP, return of capital, and
  manual adjustments.
- `portfolio_ledger_lots`: tax-lot and cost-base slices derived from reviewed
  events.
- `portfolio_ledger_snapshots`: read-optimized account snapshots generated from
  reviewed events.
- `portfolio_ledger_franking_credits`: Australian dividend/franking metadata
  for review and tax context.
- `portfolio_ledger_settlements`: expected or actual settlement lifecycle rows.
- `portfolio_ledger_audit_log`: sanitized replay, validation, rollback, and
  migration audit rows.
- `portfolio_ledger_idempotency_keys`: duplicate protection for imports,
  replay, and future migrations.

## ASX And AUD Handling

- ASX symbols should keep the canonical `.AX` suffix used elsewhere in the
  project.
- AUD is the default base currency for ASX ledger rows.
- Trade date and settlement date are separate fields; reports must not infer
  settlement from trade date.
- Brokerage, GST, and other fees remain explicit decimal fields.
- US symbols can remain bare symbols where existing code already allows that,
  but ASX flows should not lose ASX/AUD semantics.

## HIN And Account Identifier Boundary

Ledger v2 may record that custody metadata was present and may use one-way
digests for deduplication or reconciliation. It must not persist HIN originals,
raw account numbers, broker login material, or any value that can identify or
operate a real account. Display labels remain sanitized manual-review labels.

## Franking, Dividends, And Corporate Actions

Franking credits and dividends should be modeled separately from trade events.
Corporate actions should be reviewed events that can adjust quantity, cash, and
cost base without pretending to be broker fills. DRP, splits, consolidations,
return of capital, and manual adjustments need explicit action types and
effective dates.

## Migration Phases

1. **Plan and guard**: ship this document, the declarative contract, and a
   default-off guard. No data changes.
2. **Read-only tables behind disabled migration flag**: introduce table models
   and migration scaffolding that cannot run unless the guard is explicitly
   enabled.
3. **Backfill dry run**: build a dry-run transformer from current
   `portfolio_positions`, `trade_journal`, `account_snapshots`, and paper
   rows into ledger v2 candidate rows.
4. **Dual-read comparison**: compare v1 overview/event outputs with v2
   generated snapshots in tests and diagnostics, while production reads stay on
   v1.
5. **Shadow read**: optionally expose read-only v2 diagnostics for manual
   review after tests prove parity.
6. **Cutover decision**: only after separate approval, switch selected read
   paths to v2.

## Dual-Read Boundary

Before any cutover, v1 remains authoritative. Dual-read may compute v2
snapshots and compare them with v1 outputs, but it must not change current API
responses unless a later PR explicitly opts in. Differences should be reported
as diagnostics, not silently reconciled.

## Rollback

Rollback for future phases should be simple because v1 tables remain intact
until an explicit cutover. A rollback should:

- Disable the migration flag.
- Stop any v2 migration or shadow-read runner.
- Keep v1 portfolio overview, import, workbench, and events paths active.
- Preserve v2 diagnostic rows for audit unless a later maintenance task
  explicitly purges them.
- Record rollback status in the audit table if the table exists.

## Migration Guard

`src/services/portfolio_ledger_migration_guard.py` defines the default-off
guard. Future migration code must call `PortfolioLedgerMigrationGuard.require_enabled()`
before touching database state. The enabling flag is
`ASX_LEDGER_V2_MIGRATION_ENABLED=true`. PR6 does not add a migration runner.

## Verification Scope

PR6 is verified by tests for the declarative contract and guard plus regression
tests for ASX CSV import, manual portfolio workflows, portfolio event API,
workbench API, and the existing CI gate. Passing those checks proves only that
the plan/contract/guard are present and current behavior remains unchanged; it
does not prove ledger v2 storage or migration readiness.

## Related Control-Plane Pages

- `omx_wiki/architecture-portfolio-ledger-review-journal.md`
- `omx_wiki/reference-roadmap-status-and-pr-log.md`
- `omx_wiki/pattern-broker-execution-scope-gate.md`
