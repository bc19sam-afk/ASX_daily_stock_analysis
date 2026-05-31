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
  or secrets exposure expansion.
- PR4 completed as GitHub PR #190, "Add ASX alert rule dry-run API", merged at
  `9a5d17f39585a4915288d153dfa8736093c1b4ae`. Scope: read-only
  `/api/v1/alert-rules/dry-run` endpoint for one temporary alert rule across
  single symbols, configured watchlists, portfolio holdings, and portfolio
  account checks; responses include per-target status, counts, market context,
  explicit degraded/skipped handling, and `is_trade_instruction=false`.
  Verification: GitHub checks passed for backend gate, Docker build, change
  detection, security, static checks, AI review, and review reporting; local
  verification covered `tests/test_asx_alert_rule_dry_run_api.py`,
  `tests/test_alert_center.py`, `tests/test_workbench_api.py`,
  `tests/test_portfolio_events_api.py`, and `./scripts/ci_gate.sh` with the
  project virtualenv plus bundled Node on `PATH`. Boundary: dry-run only; no
  background worker, notification delivery, broker integration, real order
  submission, or persisted execution state.
- PR5 completed as GitHub PR #192, "Add workbench alert rule dry-run UI smoke
  path", merged at `816fbbafed45cb0be479745ee418f67cdf85ac53`. Scope:
  workbench summary exposes minimal alert-rule dry-run UI schema/templates, and
  the static ASX Workbench can run dry-run rules while rendering `status`,
  `triggered_count`, `degraded_count`, `skipped_count`, `target_results`, and
  `market_context` with manual-review wording. Verification: GitHub checks
  passed for backend gate, Docker build, change detection, security, static
  checks, AI review, and review reporting; local verification covered
  `tests/test_workbench_alert_rule_ui.py`, `tests/test_workbench_api.py`,
  `tests/test_asx_alert_rule_dry_run_api.py`, `tests/test_alert_center.py`,
  `tests/test_portfolio_events_api.py`, `./scripts/ci_gate.sh`, and a
  Playwright/Chrome local workbench smoke. Boundary: UI smoke only, dry-run
  only; no background worker, notification delivery, broker integration, real
  order submission, paper simulation, DB write, secrets, HIN, account, order, or
  fill detail exposure.
- PR6 completed as GitHub PR #194, "Add ASX ledger v2 schema plan and
  migration guard", merged at `bb5ce666618774adce5211b976e0c2c471360afb`.
  Scope: ledger v2 design plan, declarative schema contract, default-off
  migration guard, contract/guard tests, and a short portfolio-ledger wiki
  cross-reference. Verification: GitHub checks passed for backend gate, Docker
  build, change detection, security, static checks, AI review, and review
  reporting; local verification covered `tests/test_portfolio_ledger_v2_contract.py`,
  `tests/test_asx_portfolio_import.py`, `tests/test_manual_portfolio_workflows.py`,
  `tests/test_portfolio_events_api.py`, `tests/test_workbench_api.py`, and
  `./scripts/ci_gate.sh` with the project virtualenv plus bundled Node on
  `PATH`. Review handling: Codex Review P2 account scoping feedback was fixed
  by adding `account_uid` to planned corporate-action rows and resolving the
  review thread. Boundary: plan/contract/guard only; no database migration,
  SQLAlchemy table creation, broker integration, real orders/fills, automatic
  execution, alert worker or notification change, or secrets, HIN originals,
  account, order, or fill detail exposure. Next candidate PR: PR7 ASX ledger v2
  read-only tables behind the disabled migration flag.

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
