# Reference: Roadmap Status And PR Log

Category: reference
Tags: roadmap, status, prs, history

## Purpose

This page is a compressed index of durable roadmap state. Detailed historical
logs remain in `docs/codex_execution_log.md`; this page should keep only the
facts needed for future planning.

## Current Phase Snapshot

- Phase 1 is complete enough to close the upstream catch-up and infrastructure
  chain: P0-P2 established report/evidence safety, PR0/PR1 established the
  control plane and low-sensitive context, and PR2-PR16 delivered the ASX
  capability foundation through provider-cache telemetry v0.
- Numbering note: in this control-plane chain, PR0 maps to GitHub PR #184
  control-plane wiki/maintainer skill, PR1 maps to GitHub PR #185
  AnalysisContextPack low-sensitivity summary, PR8 maps to GitHub PR #198
  provider quota/status dashboard, and PR9 maps to GitHub PR #200 alert-rule
  presets. GitHub PR #211 and #217 are status/documentation PRs, not additional
  implementation milestones. PR23 landed as GitHub PR #227 plus review-fix
  follow-up #229. PR24 landed as GitHub PR #231.
- GitHub PR #210 fixed the final date-stability audit issue, #211 recorded that
  audit status, #216 delivered PR16 provider-cache telemetry, #217 recorded
  PR16 status on `main`, #218 selected Phase 2 boundaries, #219 delivered PR18
  Workbench diagnostics productization, #220 recorded PR18 status on `main`,
  #222 selected the PR21 ledger v2 rehearsal gate, #223 delivered PR21, #224
  recorded PR21 status, #225 delivered PR22 Morning Review Card, #227 tuned
  Morning Review Card readability after the first real email, #229 closed
  the follow-up readability label review comments, and #231 fixed the 2026-06-03
  daily stock report notification failure on malformed report data.
- The next stage is a Phase 2 option menu, not an automatic continuation chain.
  PR19 added a docs/wiki selection gate so PR20 could select one lane before
  implementation. Pick one direction per PR:
  A. Workbench productization.
  B. Ledger v2 migration rehearsal or deeper shadow-read.
  C. Alert worker or notification attempt, default-off and manual-review only.
  D. Broker-ready draft/paper boundary, no real broker.
  E. Live provider quota telemetry, only with explicit external-call scope.
- PR18 used the lowest-risk Workbench productization lane. PR19 landed the
  docs-backed selection gate. PR20 selects ledger v2 rehearsal/deeper
  shadow-read for PR21 and keeps PR21 read-only/dry-run only, with v1
  authoritative and no storage writes, migration/cutover, broker/execution,
  worker, notification, or live-provider-call work. PR21 landed the selected
  rehearsal report without changing those boundaries. PR22 added the display
  only Morning Review Card, PR23 tuned its real-email first-screen readability,
  and PR24 added malformed report-data notification resilience without changing
  action, provider, worker, broker, or ledger semantics.

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
  account, order, or fill detail exposure.
- PR7 completed as GitHub PR #196, "Add disabled ASX ledger v2 migration
  scaffold", merged at `c370055c95382e2763c38793d1c5db4601358433`.
  Scope: disabled-by-default ledger v2 shadow schema spec, DDL planner, guarded
  execution scaffold, scaffold tests, and ledger v2 plan update. Verification:
  GitHub checks passed for backend gate, Docker build, change detection,
  security, static checks, AI review, and review reporting; desktop gate was
  skipped by change detection. Local verification covered
  `tests/test_portfolio_ledger_v2_contract.py`,
  `tests/test_portfolio_ledger_v2_migration_scaffold.py`,
  `tests/test_asx_portfolio_import.py`,
  `tests/test_manual_portfolio_workflows.py`,
  `tests/test_portfolio_events_api.py`, `tests/test_workbench_api.py`,
  `git diff --check`, `py_compile` for the new scaffold module, and
  `./scripts/ci_gate.sh` with the project virtualenv plus bundled Node on
  `PATH`. Review handling: GitHub AI review and automated review report passed
  without actionable review threads; the only PR comment was the generated
  summary report. Boundary: no production migration, no startup v2 table
  creation, no active `Base.metadata` registration, no storage schema change, no
  v1 portfolio/import/events/workbench replacement, no runtime endpoint, no
  worker, no broker integration, no real orders/fills, no notifications, and no
  secrets, HIN originals, account credentials, account numbers, order details,
  or fill detail persistence. Next candidate PR: PR10 ledger v2 dry-run backfill
  transformer and dual-read comparison groundwork, with v1 still authoritative
  and no production migration.
- Parallel provider/status dashboard completed as GitHub PR #198, "Add provider
  quota status to ASX workbench", merged at
  `0c8a9cfc59aa067fb1b85fd787bc41491a463e07`. Scope: read-only ASX Workbench
  provider/cache status in the workbench summary and static UI, including
  low-sensitive configured booleans for Tavily, Gemini, and SerpAPI; Gemini
  grounding/model status; provider order; `news_intel` cache
  enabled/days/min_results; and quota-safe/search-fallback notes. Verification:
  GitHub checks passed for backend gate, Docker build, change detection,
  security, static checks, AI review, and review reporting; desktop gate was
  skipped by change detection. Local verification covered
  `tests/test_workbench_api.py`, `tests/test_search_asx_localisation.py`,
  `tests/test_news_intel_cache_reuse.py`, `./scripts/ci_gate.sh` with the
  project virtualenv plus bundled Node on `PATH`, and a local Workbench browser
  smoke. Review handling: Codex Review P2 copy feedback on fallback/rotation
  wording was fixed before merge, with the thread outdated/resolved and final
  review checks passing. Boundary: no broker connection, real orders/fills,
  automatic execution, notifications, external search calls, provider order
  changes, cache clearing, secrets/raw key/token exposure, ledger v2,
  `portfolio_ledger_*`, or `docs/portfolio-ledger-v2-plan.md` changes. Next
  candidate remains PR10 ledger v2 dry-run backfill transformer and dual-read
  comparison groundwork; provider/cache counters or live quota telemetry require
  explicit separate scope.
- Alert-rule preset selector completed as GitHub PR #200, "Add ASX alert rule
  presets to workbench", merged at
  `3fb1b9e89d4591cbc65351f9cc8fcbcb662db49f`. Scope: reusable read-only
  alert-rule preset catalog, `/api/v1/alert-rules/presets`, context-aware
  workbench preset selector, one-click dry-run result rendering, empty-watchlist
  skip handling, and manual-review/no-trade-instruction preset contracts.
  Verification: GitHub checks passed for backend gate, Docker build, change
  detection, security, static checks, AI review, and review reporting; desktop
  gate was skipped by change detection. Local verification covered
  `tests/test_asx_alert_rule_presets.py`,
  `tests/test_asx_alert_rule_dry_run_api.py`, `tests/test_workbench_api.py`,
  `tests/test_workbench_alert_rule_ui.py`, `tests/test_alert_center.py`,
  `git diff --check`, `./scripts/ci_gate.sh` with the project virtualenv plus
  bundled Node on `PATH`, and a local Workbench browser smoke for selector,
  dry-run result rendering, `is_trade_instruction=false`, and narrow-viewport
  overflow. Review handling: Codex Review P2 watchlist gating feedback was
  fixed by disabling watchlist presets without configured `STOCK_LIST`, adding
  direct dry-run skip behavior for empty watchlists, rerunning checks, and
  resolving the review thread. Boundary: dry-run/manual review only; no
  background worker, notification delivery, broker integration, real order
  submission, paper simulation, DB write from presets, secrets, HIN originals,
  account credentials, account numbers, order details, or fill detail exposure.
  Next candidate remains PR10 ledger v2 dry-run backfill transformer and
  dual-read comparison groundwork; alert-rule workers, notification attempts,
  broker execution, or live quota telemetry require explicit separate scope.
- PR10 completed as GitHub PR #202, "Add ASX ledger v2 dry-run backfill
  comparison", merged at `c3e7979ea7ec6a203bf176664e0d99dc5a7f6dbf`.
  Scope: side-effect-free ASX ledger v2 dry-run transformer over existing
  portfolio journal/snapshot state, stable source hashes and source event IDs,
  explicit unsupported placeholders for corporate action/dividend/franking and
  cash-only rows, dual-read comparison counts and warnings, read-only
  `/api/v1/portfolio-events/ledger-v2/dry-run`, and compact Workbench summary
  metadata/link. Verification: GitHub checks passed for backend gate, Docker
  build, change detection, security, static checks, AI review, and review
  reporting; desktop gate was skipped by change detection. Local verification
  covered `tests/test_asx_ledger_v2_dry_run.py`,
  `tests/test_asx_portfolio_import.py`, `tests/test_portfolio_events_api.py`,
  `tests/test_workbench_api.py`, `tests/test_portfolio_ledger_v2_contract.py`,
  `tests/test_portfolio_ledger_v2_migration_scaffold.py`, `git diff --check`,
  and `./scripts/ci_gate.sh` with 846 tests plus 5 subtests passing. Review
  handling: Codex Review P2 feedback about repeated manual
  `query_id="manual_trade_workflow"` source IDs was fixed by appending a stable
  source-hash suffix and adding a regression test; the original thread became
  outdated before merge. Boundary: dry-run/comparison groundwork only; no
  production ledger v2 writes, migration cutover, v1 portfolio authority change,
  broker connection, real orders/fills, paper simulation writes, worker,
  notification, secrets, HIN originals, account credentials, account numbers,
  order details, or fill detail exposure. Next candidate: a separately scoped
  follow-up can add operator-facing ledger v2 shadow-read diagnostics after
  manual review of dry-run mismatches; v1 remains authoritative until a future
  migration/cutover PR is explicitly authorized.
- PR11 completed as GitHub PR #204, "Add ledger v2 shadow diagnostics", merged
  at `fb24c823e165a4db4fbbed6e80149f3052f5af04`.
  Scope: read-only `/api/v1/portfolio-events/ledger-v2/diagnostics` shadow-read
  diagnostics over the PR10 dry-run comparison, grouped operator-facing
  summaries for mismatched, missing, unsupported, and warning buckets, redacted
  unsupported-placeholder details, and compact Workbench metadata/link to the
  diagnostics endpoint. Verification: GitHub checks passed for backend gate,
  Docker build, change detection, security, static checks, AI review, and review
  reporting; desktop gate was skipped by change detection. Local verification
  covered `tests/test_asx_ledger_v2_dry_run.py`,
  `tests/test_portfolio_events_api.py`, `tests/test_workbench_api.py`,
  `git diff --check`, targeted `py_compile`, and `./scripts/ci_gate.sh` with
  the project virtualenv plus bundled Node on `PATH` (`848` tests plus `5`
  subtests passing). Review handling: automated AI review and review report
  passed with no review threads; the only PR comment was the generated summary
  report. Boundary: diagnostics are dry-run/manual-review only; v1 remains
  authoritative; no ledger v2 writes, production migration, cutover,
  broker connection, real orders/fills, paper simulation writes, worker,
  notification delivery, secrets, HIN originals, account credentials, account
  numbers, order details, or fill detail exposure. Subagent note: native Codex
  subagent attempts for PR11/PR12 sidecar exploration failed with provider auth
  `503`, so implementation and verification remained leader-owned. Next
  candidate: PR12 ASX dividend/franking/corporate-action event placeholders,
  still explicit unsupported/partial where needed and still outside tax advice,
  broker statements, migration, or cutover scope.
- PR12 completed as GitHub PR #206, "Add ledger v2 income action placeholders",
  merged at `f626993d5f70ed6d32c8c07adfbaf306efb43485`.
  Scope: ASX-aware ledger v2 dry-run placeholder normalization for
  dividend/franking income and corporate-action groundwork, including dividend,
  franking credit, DRP, split, consolidation, return of capital, and unknown
  income/corporate-action rows as explicit partial or unsupported manual-review
  placeholders. Verification: GitHub checks passed for backend gate, Docker
  build, change detection, security, static checks, AI review, and review
  reporting; desktop gate was skipped by change detection. Local verification
  covered `tests/test_asx_ledger_v2_dry_run.py`,
  `tests/test_asx_portfolio_import.py`,
  `tests/test_portfolio_ledger_v2_contract.py`,
  `tests/test_portfolio_ledger_v2_migration_scaffold.py`,
  `tests/test_portfolio_events_api.py`, `tests/test_workbench_api.py`,
  `git diff --check`, targeted `py_compile`, and `./scripts/ci_gate.sh` with
  the project virtualenv plus bundled Node on `PATH` (`852` tests plus `5`
  subtests passing). Review handling: Codex Review P2 feedback was fixed by
  preventing known income/corporate-action aliases from creating unrelated
  unknown placeholders and by including parsed event aliases in dry-run source
  identity; both review threads were resolved before merge. Boundary:
  placeholder contract only; v1 remains authoritative; no tax-return
  calculation, cash-event creation, quantity/cost-base adjustment, broker
  statement import, real ledger v2 write, production migration, cutover,
  broker connection, real orders/fills, worker, notification delivery, secrets,
  HIN originals, account credentials, account numbers, order details, or fill
  detail exposure. Subagent note: a native Codex code-review lane checked the
  patched PR12 workspace and found no blocking issues; OMX team was not used
  because this Codex App session was not an OMX CLI/tmux runtime. Next
  candidate: PR13 portfolio/watchlist alert dry-run batch diagnostics, only if
  started from clean main and kept read-only with no notification worker.
- PR13 completed as GitHub PR #208, "Add alert rule batch dry-run
  diagnostics", merged at `0111f1e63bebede72d4029565c4f4ca66debca9e`.
  Scope: read-only `POST /api/v1/alert-rules/dry-run/batch` diagnostics for
  multiple temporary portfolio/watchlist alert-rule dry-runs, target-level
  summary counts, no parameter echo in batch results, and compact Workbench
  metadata/link to the batch diagnostics endpoint. Verification: GitHub checks
  passed for backend gate, Docker build, change detection, security, static
  checks, AI review, and review reporting; desktop gate was skipped by change
  detection. Local verification covered targeted batch dry-run and Workbench
  tests, broader alert/workbench pytest, `git diff --check`, targeted
  `py_compile`, and `./scripts/ci_gate.sh` with the project virtualenv plus
  bundled Node on `PATH` (`856` tests plus `5` subtests passing). Review
  handling: pre-merge sidecar review risk about sensitive rule-parameter echo
  was fixed with regression coverage, and Codex Review P2 feedback about
  evaluation-error summary counts was fixed by counting target-level
  `evaluation_error` results with regression coverage; the review thread was
  resolved before merge. Boundary: dry-run/manual-review diagnostics only; no
  notification delivery, background worker, broker integration, order
  submission, paper simulation write, persisted execution state, secrets, HIN
  originals, account credentials, account numbers, order details, or fill
  detail exposure. Subagent note: native Codex PR13 review-risk sidecar found
  the parameter-echo issue; coordinated OMX runtime was not used because this
  Codex App session was not an OMX CLI/tmux runtime. A final audit fix followed
  in PR #210 to stabilize date-sensitive alert-center verification without
  expanding the roadmap chain. Leave future alert workers, notification
  attempts, broker execution, persistence, or live quota telemetry for separate
  explicit scope.
- Final audit fix completed as GitHub PR #210, "Fix alert center date-stable
  manual review checks", merged at
  `c06ab26230d3f165b43b20e90ad9e1800ebb0d9a`. Scope: fixed alert-center
  verification stability across the 2026-06-01 date rollover by controlling the
  workbench alert route test date and keeping report-freshness action hints
  explicit about manual review. Verification: local `./scripts/ci_gate.sh`
  passed with `856` tests plus `5` subtests passing; GitHub checks passed for
  backend gate, Docker build, change detection, security, static checks, AI
  review, and review reporting; desktop gate was skipped by change detection.
  Boundary: no new alert worker, notification delivery, broker integration,
  order submission, paper simulation write, persisted execution state, secrets,
  HIN originals, account credentials, account numbers, order details, or fill
  detail exposure. Next candidate: no further PR in this chain; future alert
  workers, notification attempts, broker execution, persistence, live quota
  telemetry, or ledger v2 cutover require separate explicit scope.
- PR14 completed as GitHub PR #212, "Add workbench diagnostics hub", merged at
  `45e3708207733a6a3506a255fc8df4116f31527e`. Scope: read-only Workbench
  Diagnostics Hub at `/api/v1/workbench/diagnostics`, compact hub metadata in
  `/api/v1/workbench/summary`, and a static Workbench panel linking existing
  low-sensitive provider/cache status, alert-rule presets, alert-rule batch
  dry-run, ledger v2 dry-run, and ledger v2 diagnostics surfaces. Verification:
  GitHub checks passed for backend gate, Docker build, change detection,
  security, static checks, AI review, and review reporting; desktop gate was
  skipped by change detection. Local verification covered new diagnostics hub
  contract tests, broader workbench/alert/ledger API tests, `git diff --check`,
  `./scripts/ci_gate.sh` with the project virtualenv plus bundled Node on
  `PATH` (`858` tests plus `5` subtests passing), and a local Chrome Workbench
  smoke for desktop and 390px mobile hub rendering with no horizontal overflow.
  Review handling: a native Codex code-review sidecar found no blocking issues;
  GitHub PR review checks passed. Boundary: summary/link aggregation only; no
  external provider calls, cache clearing, DB writes, background worker,
  notification delivery, broker integration, order submission, paper simulation
  write, ledger v2 storage write, migration/cutover, v2 authority replacement,
  secrets, HIN originals, account credentials, account numbers, order details,
  or fill detail exposure. Next candidate: PR15 Workbench diagnostics smoke
  hardening, limited to stable smoke/test coverage for diagnostics hub and the
  static workbench entry.
- PR15 completed as GitHub PR #214, "Harden workbench diagnostics smoke
  coverage", merged at `42adf68bb9b12e4c933ea825d98556ce1419a739`. Scope:
  stable smoke coverage for the PR14 diagnostics hub and static Workbench entry,
  including smoke selectors for the Workbench navigation, diagnostics hub,
  alert-rule dry-run panel, provider/cache panel, diagnostics card list, and
  narrow-screen overflow guardrails. Verification: GitHub checks passed for
  backend gate, Docker build, change detection, security, static checks, AI
  review, and review reporting; desktop gate was skipped by change detection.
  Local verification covered new diagnostics smoke tests, broader
  workbench/alert/ledger API tests, `git diff --check`, `./scripts/ci_gate.sh`
  with the project virtualenv plus bundled Node on `PATH` (`861` tests plus
  `5` subtests passing), and a local Chrome Workbench smoke for desktop and
  390px mobile smoke-hook rendering with no horizontal overflow. Review
  handling: a native Codex code-review sidecar approved the scoped static/test
  hardening diff; GitHub PR review checks passed. Boundary: smoke/test
  hardening only; no new business capability, external provider calls, cache
  clearing, DB writes, background worker, notification delivery, broker
  integration, order submission, paper simulation write, ledger v2 storage
  write, migration/cutover, v2 authority replacement, secrets, HIN originals,
  account credentials, account numbers, order details, or fill detail exposure.
  Next candidate: PR16 provider/cache usage telemetry v0, only if started from
  clean main and kept low-sensitive/local-status only without active external
  provider calls or secret reads.
- PR16 completed as GitHub PR #216, "Expose provider cache usage telemetry",
  merged at `0ca7eb68e660d678847c3fb42da64210ebcda1e8`. Scope: local-only
  provider/cache usage telemetry v0 under
  `config_status.provider_status.usage_telemetry`, compact diagnostics hub
  provider-card telemetry, and static Workbench display of cache observation
  count, observed dimensions, and last observed provider/dimension/timestamp.
  Verification: GitHub checks passed for backend gate, Docker build, change
  detection, security, static checks, AI review, and review reporting; desktop
  gate was skipped by change detection. Local verification covered red-first
  targeted tests for missing telemetry, `tests/test_workbench_api.py`,
  `tests/test_workbench_diagnostics_smoke.py`,
  `tests/test_news_intel_cache_reuse.py`, `git diff --check`,
  `./scripts/ci_gate.sh` with the project virtualenv plus bundled Node on
  `PATH` (`862` tests plus `5` subtests passing), and a local Chrome Workbench
  smoke for desktop and 390px mobile telemetry rendering with no horizontal
  overflow. Review handling: GitHub PR AI/review checks passed; a native Codex
  exploratory sidecar mapped the implementation surface, a native test sidecar
  mapped the expected tests, and a later native code-review sidecar was stopped
  after timing out without blocking the already-green local and GitHub gates.
  Boundary: metadata-only local cache status; no live provider/quota polling,
  external search/AI provider calls, secret reads, raw key/token exposure,
  cache clearing, DB writes, background worker, notification delivery, broker
  integration, order submission, paper simulation write, ledger v2 storage
  write, migration/cutover, v2 authority replacement, secrets, HIN originals,
  account credentials, account numbers, order details, query/title/snippet/URL,
  requester fields, or fill detail exposure. Next candidate: no further PR in
  this chain; future live provider telemetry, quota probes, workers,
  notification attempts, broker execution, persistence, or ledger v2 cutover
  require separate explicit scope.
- PR17 completed as GitHub PR #218, "Record ASX phase-2 roadmap options",
  merged at `8f71f957b1e9d7996416b13cb5d75bc905bab0a8`. Scope: selected the
  Phase 2 option menu after PR16/status #217 and kept future work split by
  direction rather than automatic continuation. Boundary: docs/wiki roadmap
  selection only; no Workbench implementation, ledger migration/cutover,
  alert worker, notification delivery, broker connection, real orders/fills,
  live provider calls, or sensitive data exposure. Next candidate at the time:
  choose one Phase 2 direction, with Workbench productization or a docs-backed
  selection gate lower risk than worker, broker, migration/cutover,
  notification, or live-provider-call work.
- PR18 completed as GitHub PR #219, "Productize ASX workbench diagnostics",
  merged at `21a1e6ac6f1537b84ea67b85034871bac16ed177`. Scope:
  operator-facing diagnostics hub productization in the existing static
  Workbench, including stable `nav`, `quick_links`, `status_badges`, and
  `action_groups` schema fields; first-screen Diagnostics Hub placement; and
  cards for provider/cache status, alert diagnostics, ledger diagnostics, and
  the manual-review/no-trade boundary. Verification: GitHub checks passed for
  backend gate, Docker build, change detection, security, static checks, AI
  review, and review reporting; desktop gate was skipped by change detection.
  Local verification covered red/green productization tests,
  `tests/test_workbench_api.py`, `tests/test_workbench_diagnostics_smoke.py`,
  targeted alert/ledger/provider tests, `git diff --check`,
  `./scripts/ci_gate.sh` with the project virtualenv plus bundled Node on
  `PATH` (`863` tests plus `5` subtests passing), and a Chrome/Playwright
  Workbench smoke at 1280px desktop and 390px mobile with diagnostics hub,
  status badges, links, and no horizontal overflow. Review handling: GitHub AI
  review/checks passed with only the generated review report; native Codex
  read-only mapping succeeded after the spark-model `explore` lanes hit the
  known provider `502`, and a later local code-review sidecar was stopped after
  timeout without blocking the green local and GitHub gates. Boundary:
  read-only/manual-review UI and schema only; no new business capability,
  external provider calls, cache clearing, DB writes, background worker,
  notification delivery, broker integration, order submission, paper simulation
  write, ledger v2 storage write, migration/cutover, v2 authority replacement,
  live provider quota API, secrets, HIN originals, account credentials, account
  numbers, order details, fill detail, provider request payload,
  query/title/snippet/URL, or requester-field exposure. Next candidate: pick a
  separate Phase 2 direction, with ledger v2 rehearsal/deeper shadow-read or a
  docs-backed selection gate lower risk than alert workers, notification
  attempts, broker execution, persistence, live provider telemetry, or ledger v2
  cutover.
- PR19 is GitHub PR #221, "Add ASX Phase 2 selection gate". Scope: add
  [[pattern-phase2-selection-gate]], link it from the wiki index and roadmap
  decision, update the roadmap status log, and point the maintainer skill at the
  gate for future Phase 2 starts. Boundary: docs/wiki/control-plane only;
  no PR20 implementation, business code, API, tests, static UI, database,
  config, workflow, broker connection, real order, notification send, alert
  worker, ledger v2 migration/cutover, live provider API call, or sensitive
  account/order/fill/provider payload material. Next step after merge: use the
  gate to choose exactly one PR20 lane. Recommended ordering, without choosing
  for the user: ledger deeper shadow-read/rehearsal gate; broker-ready
  draft/paper gate; alert notification dry-run gate; live provider telemetry
  gate.
- PR20 selects [[decision-phase2-ledger-v2-rehearsal-gate]] as the Phase 2
  lane for PR21. Scope: docs/wiki/control-plane gate application only; record
  chosen lane B, medium risk, none/dry-run-only side effects, v1 authority,
  default-off migration controls, human-review boundaries, sensitive-data
  exclusions, and concrete PR21 acceptance criteria. Boundary: no business
  code, API, tests, static UI, database, config, workflow, broker connection,
  real order, notification send, alert worker, live provider API call, ledger
  v2 storage write, production migration, cutover, or sensitive
  account/order/fill/provider payload material. Next candidate: PR21 "Ledger
  v2 rehearsal report over shadow diagnostics", limited to a read-only
  rehearsal report or comparison export over existing dry-run, diagnostics, and
  placeholder surfaces.
- PR21 completed as GitHub PR #223, "Add ledger v2 rehearsal report", merged
  at `059abef45231726526b379dbc7dd152a1f164cf1`. Scope: read-only
  `/api/v1/portfolio-events/ledger-v2/rehearsal-report` over existing ledger
  v2 dry-run candidates, shadow diagnostics, and income/corporate-action
  placeholders; compact Workbench metadata/link for the report; sanitized
  counts, source summary, top mismatch categories, unsupported placeholder
  summary, manual-review requirement, and explicit non-cutover/not-migration
  wording. Verification: GitHub checks passed for backend gate, Docker build,
  change detection, security, static checks, AI review, and review reporting;
  desktop gate was skipped by change detection. Local verification covered
  `tests/test_asx_ledger_v2_dry_run.py`,
  `tests/test_portfolio_events_api.py`, `tests/test_workbench_api.py`,
  `tests/test_portfolio_ledger_v2_contract.py`,
  `tests/test_portfolio_ledger_v2_migration_scaffold.py`, `git diff --check`,
  focused sensitive-sample search, and `./scripts/ci_gate.sh` with the project
  virtualenv plus bundled Node on `PATH` (`865` tests plus `5` subtests
  passing). Review handling: GitHub AI review and generated review report
  passed; thread-aware review inspection found no review threads and only the
  generated report comment. Boundary: dry-run/manual-review report only; v1
  remains authoritative; no ledger v2 storage write, table creation,
  migration/cutover, v2 authority replacement, broker connection, real
  orders/fills, paper simulation write, worker, notification delivery, live
  provider call, secrets, HIN originals, account credentials, account numbers,
  order details, or fill detail exposure. Next candidate: manually review PR21
  rehearsal outputs before selecting a separate PR22 lane; no migration,
  cutover, worker, notification, broker, persistence, or live-provider work is
  implied by PR21.
- PR22 completed as GitHub PR #225, "Add Morning Review Card to daily
  email/report", merged at `acc8033d6cd159e1bfc9bfe3f9fc486a60a3c863`.
  Scope: display-only Morning Review Card in the dashboard and legacy daily
  report bodies, reusing existing `daily_decision_summary` action/watch/blocked
  items, `triage_card`, top risk lines, `report_reliability`,
  `data_quality_snapshot`, score/evidence gaps, and risk-sizing
  preview/comparison fields. The card surfaces today's conclusion, first
  symbols to review, why, key risks, reliability/data-quality reminders,
  risk-sizing trial notes, and human-review wording before the longer report
  detail and archive appendix. Verification: GitHub checks passed for backend
  gate, Docker build, change detection, security, static checks, AI review, and
  review reporting; desktop gate was skipped by change detection. Local
  verification covered `tests/test_morning_review_card.py`,
  `tests/test_report_body_deduplication.py`,
  `tests/test_daily_decision_dashboard_archive.py`,
  `tests/test_daily_decision_summary_evidence.py`,
  `tests/test_risk_sizing_dry_run_comparison.py`,
  `tests/test_report_readability_guardrail.py`,
  `tests/test_notification_summary_format.py`,
  `tests/test_notification_validation_gate.py`,
  `tests/test_score_bucket_calibration.py`,
  `tests/test_risk_sizing_shadow_mode.py`, `git diff --check`, targeted
  `py_compile`, and `./scripts/ci_gate.sh` with the project virtualenv plus
  bundled Node on `PATH` (`870` tests plus `5` subtests passing). Review
  handling: GitHub AI review and generated review report passed. Boundary:
  display-only report/email UX; no deterministic final action, position action,
  target weight, sizing write-back, notification send timing, default worker,
  Workbench/API expansion, provider order/cache change, live provider call,
  broker/execution, database migration, ledger v2 production write/cutover,
  secrets, HIN originals, account credentials, account numbers, order details,
  or fill detail exposure. Next candidate: review the next real daily
  email/report with the Morning Review Card before choosing another small PR.
  If implementation continues, select one separate lane only: another report
  readability pass, alert notification dry-run/default-off gate, broker-ready
  draft/paper boundary, live provider telemetry with explicit external-call
  scope, or ledger v2 follow-up after manual review; no worker, broker,
  notification delivery, live-provider call, persistence, or ledger cutover is
  implied by PR22.
- PR23 completed as GitHub PR #227, "Tune Morning Review Card readability",
  merged at `2c76715b5ed1e804e0ae73f85045bae932741985`, with follow-up GitHub
  PR #229, "Polish Morning Review Card reliability labels", merged at
  `68edc7298f59e4dc67da115d5002bc5da1aedcf7`. Scope: display-only report/email
  readability tune after the first real daily email
  `股票智能分析报告 - 2026-06-02` (`Gmail messageId 19e85a61ef289ba5`). PR23
  separated `今日优先复核`, `先补数据再判断`, and `低优先级观察`; removed the
  legacy `今日人工复核卡片` from the pre-open first screen; shortened the
  Morning Review Card data reliability row; kept risk sizing as trial-only; and
  added regression coverage so ASX announcement gaps appear in `主要缺口` and
  non-realtime mixed price policies keep the Chinese `价格来源混用` label.
  Verification: PR #227 and #229 both passed GitHub backend gate, Docker build,
  change detection, security, static checks, AI review, and review reporting;
  local `ci_gate.sh` passed with `872` tests plus `5` subtests for #227 and
  `874` tests plus `5` subtests for #229. Boundary: display/readability and
  tests only; no deterministic action, target weight, validation block,
  risk-sizing calculation/write-back, strategy strip, portfolio card, alert
  worker, notification send, provider order/cache policy, live provider/paid
  data call, broker/execution, real account/order/fill handling, ledger v2
  migration/cutover/production write, secrets, HIN originals, account numbers,
  or strategy/AI write-back to authoritative fields. Next candidate: wait for
  another real report/email or choose one separate Phase 2 lane; no worker,
  broker, notification delivery, live-provider call, persistence, provider
  policy change, or ledger cutover is implied by PR23.
- PR24 completed as GitHub PR #231, "Fix daily report notification failure on
  malformed report data", merged at
  `33ea9fb3e9c06aa00daeae463acb5fa2bc323325`. Incident evidence: scheduled run
  `26854967085` used remote `main@c1edf3a516bf28473c0eef13053d2378fa3eb14f`,
  Gmail had the 2026-06-02 daily report but no 2026-06-03 stock daily report,
  and run artifacts had `logs/` plus `reports/market_review_20260603.md` but no
  stock daily Markdown, HTML, or `daily_decision_summary_20260603.json`. Root
  cause: malformed string-shaped report data reached `.get(...)` in the
  notification/report renderer before stock daily artifacts were saved, and the
  old notification failure log omitted traceback context. Scope: display-only
  resilience for malformed portfolio holding rows, paper portfolio rows, and
  dashboard nested blocks, plus traceback-bearing notification failure logging.
  Verification: local targeted RED/GREEN tests, the notification/dashboard/
  Morning Review Card/readability/pipeline related suite (`135` tests),
  `git diff --check`, targeted `py_compile`, and full `./scripts/ci_gate.sh`
  (`880` tests plus `5` subtests) passed; GitHub backend gate, Docker build,
  change detection, security, static checks, AI review, and review report
  passed, with desktop gate skipped by change detection. Boundary: no real
  notification send, manual `workflow_dispatch`, schedule change, deterministic
  action, position action, target weight, validation block, risk-sizing
  calculation/write-back, provider order/cache policy, live provider/paid data
  call, broker/execution, real account/order/fill handling, ledger v2
  migration/cutover/production write, secrets, HIN originals, account numbers,
  order details, or fill details. Next step: inspect the next real scheduled
  stock daily report/email and confirm stock daily Markdown, HTML, JSON, and
  email are all present; if not, start from the new traceback-bearing
  notification log.

## Blocked Or Separately Authorized Areas

- True risk-sizing enabled mode.
- Realtime quote adapter.
- Broker integration.
- Automatic trading.
- Default alert worker or production notification delivery.
- Production ledger v2 migration or cutover.
- Live provider quota probes or external-call telemetry.
- Provider request payload, raw key/token, query/title/snippet/URL, or requester
  field exposure.
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
