# ASX Portfolio Ledger V2 Plan

## Purpose

Ledger v2 is a planned event-oriented portfolio ledger for ASX/AU/US manual
review workflows. PR6 introduced the schema plan, declarative contract, and
default-off migration guard; PR7, PR10, PR11, and PR12 later added disabled
scaffold, dry-run comparison, shadow diagnostics, and placeholder groundwork.
These phases still do not create production tables, migrate data, expose a
mutation endpoint, cut over reads, or replace current portfolio overview, ASX
CSV import, paper portfolio, workbench, alert-rule, or review-journal behavior.

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
- `portfolio_ledger_corporate_actions`: account-scoped splits, DRP, return of
  capital, and manual adjustments.
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

1. **Plan and guard**: shipped in PR6 with this document, the declarative
   contract, and a default-off guard. No data changes.
2. **Disabled shadow migration scaffold**: shipped in PR7 as a side-effect-free
   shadow schema spec and DDL planner that returns a blocked/dry-run plan by
   default. The scaffold must not register ledger v2 models on active storage
   metadata, create tables during normal startup, or run without the explicit
   migration guard.
3. **Backfill dry run**: shipped in PR10 as a dry-run transformer from current
   `portfolio_positions`, `trade_journal`, `account_snapshots`, and paper rows
   into ledger v2 candidate rows.
4. **Dual-read comparison**: shipped in PR10/PR11 as comparison diagnostics
   while production reads stay on v1.
5. **Shadow read diagnostics**: shipped in PR11 as read-only diagnostics for
   manual review. PR12 added dividend/franking and corporate-action
   placeholders as explicit unsupported or partial review metadata.
6. **Cutover decision**: not started. Only after separate approval may selected
   read paths switch to v2.

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

## PR7 Disabled Migration Scaffold

PR7 adds `src/services/portfolio_ledger_v2_migration.py` as a disabled
migration scaffold for future shadow tables. It can:

- Build a side-effect-free shadow schema spec from the ledger v2 contract.
- Render `CREATE TABLE IF NOT EXISTS` DDL for review and future migration
  tooling.
- Return a blocked/dry-run migration plan when the migration flag is absent.
- Require both explicit execution parameters and the default-off migration guard
  before any future caller can write database state.

PR7 still does not run a production migration, create ledger v2 tables during
startup, attach v2 models to `src.storage.Base.metadata`, expose a runtime
endpoint, replace current portfolio overview/import/events/workbench behavior,
connect a broker, or store raw HIN/account/order/fill details.

The PR7 shadow schema follows the contract tables for accounts, trades, cash
events, corporate actions, lots, snapshots, franking credits, settlements,
audit, and idempotency. Corporate actions remain account-scoped via
`account_uid`. Account custody metadata is represented only as presence or
one-way reference fields, not raw identifiers.

## Migration Guard

`src/services/portfolio_ledger_migration_guard.py` defines the default-off
guard. Future migration code must call `PortfolioLedgerMigrationGuard.require_enabled()`
before touching database state. The enabling flag is
`ASX_LEDGER_V2_MIGRATION_ENABLED=true`. PR6 does not add a migration runner;
PR7 adds only a disabled scaffold and DDL planner.

## Verification Scope

PR6 is verified by tests for the declarative contract and guard plus regression
tests for ASX CSV import, manual portfolio workflows, portfolio event API,
workbench API, and the existing CI gate. PR7 adds scaffold tests for blocked
default execution, dry-run non-mutation, contract-aligned shadow schema,
account-scoped corporate actions, sensitive-field exclusion, active metadata
isolation, and unchanged v1 storage behavior. PR10-PR12 add dry-run comparison,
shadow diagnostics, and placeholder regression coverage. Passing those checks
proves only that the plan/contract/guard/scaffold/diagnostics are present and
current behavior remains unchanged; it does not prove ledger v2 storage,
production migration, or cutover readiness.

## PR12 Income And Corporate-Action Placeholders

PR12 extends the dry-run candidate contract with explicit ASX-aware placeholder
metadata for dividend, franking credit, DRP, split, consolidation, return of
capital, and unknown income or corporate-action rows. It can normalize safe
metadata already present on manual/import journal rows into review-only
`income`, `franking`, and `corporate_action` placeholder objects.

PR12 still does not create cash events, franking-credit rows, tax-return
calculations, lot/cost-base adjustments, broker-statement imports, ledger v2
storage rows, migrations, or cutover behavior. Unknown income or
corporate-action rows must remain explicit unsupported placeholders instead of
being treated as supported ledger events.

## Related Control-Plane Pages

- `omx_wiki/architecture-portfolio-ledger-review-journal.md`
- `omx_wiki/reference-roadmap-status-and-pr-log.md`
- `omx_wiki/pattern-broker-execution-scope-gate.md`
