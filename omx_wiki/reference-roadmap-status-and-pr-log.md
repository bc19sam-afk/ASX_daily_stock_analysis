# Reference: Roadmap Status And PR Log

Category: reference
Tags: roadmap, status, prs, history

## Purpose

This page is a compressed index of durable roadmap state. Detailed historical
logs remain in `docs/codex_execution_log.md`; this page should keep only the
facts needed for future planning.

## Stable Current State

- P0 report safety and evidence chain completed.
- P1 completed through shadow/dry-run risk sizing, structured valuation, and
  ASX search localisation.
- P2 completed through intraday review contract, offline review surfaces, ASX
  official announcement check contract, and daily review journal.
- Later ASX roadmap work delivered AnalysisContextPack v1, minimal ASX
  workbench, ASX portfolio ledger/CSV import, and ASX-aware Alert Center.
- PR2 completed as GitHub PR #186, "Add ASX CSV parser registry and dedup
  counters", merged at `f1ae4ac3945936b318bad3d179eea6971da1a76e`.
  Scope: ASX CSV parser registry, default `generic_asx` parser metadata,
  stable normalized-trade dedup hashes, preview/apply parser/counters/dedup
  result fields, duplicate-row/import skip behavior, and HIN/custody raw-value
  persistence reduction. Verification: GitHub checks passed for CI and PR
  Review; local verification covered ASX import, manual portfolio workflows,
  workbench API, AnalysisContextPack prompt tests, and `ci_gate.sh` with the
  project virtualenv plus bundled Node on `PATH`. Boundary: no broker
  connection, real execution, ledger v2 schema change, alert worker change, or
  PR3 behavior.
- PR3 completed as GitHub PR #188, "Add read-only portfolio event facade",
  merged at `e2b9bc36d45c07c979b964d98306092a9fb73c5b`.
  Scope: read-only `/api/v1/portfolio-events` facade over current portfolio
  positions, trade journal rows, import traces, account snapshots, and paper
  portfolio trades. Verification: GitHub checks passed for backend gate, Docker
  build, change detection, security, static checks, AI review, and review
  reporting; local verification covered `tests/test_portfolio_events_api.py`,
  `tests/test_manual_portfolio_workflows.py`,
  `tests/test_asx_portfolio_import.py`, `tests/test_workbench_api.py`, and
  `./scripts/ci_gate.sh`. Boundary: no ledger v2 schema, broker integration,
  real orders/fills, automatic execution, alert worker change, or HIN, account,
  or secrets exposure expansion. Next candidate PR: PR4 ASX alert rule dry-run
  API.

## Blocked Or Separately Authorized Areas

- True risk-sizing enabled mode.
- Realtime quote adapter.
- Broker integration.
- Automatic trading.
- Workflow changes.
- `close_only` default changes.
- Storage or database migrations unless scoped as an explicit PR.

## Maintenance Rule

When a major PR chain changes durable roadmap state, update this page with:

- Status.
- Scope.
- Merge or baseline reference when known.
- Verification summary.
- Boundary notes.
- Next candidate step.

Do not copy full execution logs here.
