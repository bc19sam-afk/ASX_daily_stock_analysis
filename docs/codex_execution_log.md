# Codex Roadmap Executor Log

## Status Legend

- `pending`
- `auditing`
- `already_satisfied`
- `implemented`
- `tests_failed`
- `blocked`
- `skipped`
- `pr_opened`
- `merged`

## Current Gate

- Active phase: paused after original P2 roadmap completion.
- Active PR: none.
- P0 state: complete.
- P1 state: complete through shadow / dry-run risk sizing, structured valuation, and ASX search localisation; true risk sizing enabled mode is not implemented.
- P2 state: original roadmap complete through P2-1, P2-2, P2-3, and P2-4.
- R0/R1 state: report readability guardrails complete through PR23 real-email Morning Review Card readability tune.
- P1-3b-3, realtime quote adapter, broker integration, automatic trading, workflow changes, `close_only` changes, storage changes, and database migrations remain blocked unless separately authorized.

## PR Status

| PR | Status | Branch | PR Link | Notes |
| --- | --- | --- | --- | --- |
| P0-1 AI Role Boundary | merged | `codex/p0-1-ai-role-boundary-audit` | https://github.com/bc19sam-afk/ASX_daily_stock_analysis/pull/99 | Merged via PR #99. Do not reimplement. |
| P0-2 Conditional Plan Points v1 | merged | `codex/p0-2-conditional-plan-points-v1` | https://github.com/bc19sam-afk/ASX_daily_stock_analysis/pull/100 | Merged via squash commit `38eff38`. |
| P0-3 Evidence Matrix v1 | merged | `codex/p0-3-evidence-matrix-v1` | https://github.com/bc19sam-afk/ASX_daily_stock_analysis/pull/101 | Merged via squash commit `dc9be09`. |
| P0-4 Report Reliability Score v1 | merged | `codex/p0-4-report-reliability-score-v1` | https://github.com/bc19sam-afk/ASX_daily_stock_analysis/pull/102 | Merged via squash commit `d7050ef`. |
| P0-5 Final Action Display Contract | merged | `codex/p0-5-final-action-display-contract` | https://github.com/bc19sam-afk/ASX_daily_stock_analysis/pull/103 | Merged via squash commit `9dadbdd`. |
| P0-6 API Auth Guard v1 | merged | `codex/p0-6-api-auth-guard-v1` | https://github.com/bc19sam-afk/ASX_daily_stock_analysis/pull/104 | Merged via squash commit `dbea81f`. |
| P1-1 Backtest Confidence Panel v1 | merged | `codex/p1-1-backtest-confidence-panel-v1` | https://github.com/bc19sam-afk/ASX_daily_stock_analysis/pull/105 | Merged via squash commit `8317082`. |
| P1-2 Score Bucket Calibration | merged | `codex/p1-2-score-bucket-calibration` | https://github.com/bc19sam-afk/ASX_daily_stock_analysis/pull/106 | Merged via squash commit `f69108b`. |
| P1-3a Risk-Based Sizing Shadow Mode | merged | `codex/p1-3a-risk-sizing-shadow-mode` | https://github.com/bc19sam-afk/ASX_daily_stock_analysis/pull/107 | Shadow-only preview merged via squash commit `03c8fa9`. |
| P1-3b-1 Risk-Based Sizing Cap Calculation | merged | `codex/p1-3b-1-risk-sizing-cap-calculation` | https://github.com/bc19sam-afk/ASX_daily_stock_analysis/pull/110 | Config-gated cap candidate helper only; no write-back to deterministic action fields. |
| P1-3b-2 Risk Sizing Report Comparison / Dry Run | merged | `codex/p1-3b-2-risk-sizing-dry-run-comparison` | https://github.com/bc19sam-afk/ASX_daily_stock_analysis/pull/111 | Dry-run/report comparison only; no deterministic action or sizing write-back. |
| P1-3b-3 Risk-Based Sizing Cap Enabled Mode | blocked | not started | not started | Explicitly blocked; do not enable true cap behavior. |
| P1-4 Structured Valuation Snapshot | merged | `codex/p1-4-structured-valuation-snapshot` | https://github.com/bc19sam-afk/ASX_daily_stock_analysis/pull/108 | Merged via squash commit `58f3c93`. |
| P1-5 ASX Search Localisation | merged | `codex/p1-5-asx-search-localisation` | https://github.com/bc19sam-afk/ASX_daily_stock_analysis/pull/109 | Merged via squash commit `a21b28e`. |
| P2-1 Intraday Review Input Contract | merged | `codex/p2-1-intraday-review-input-contract` | https://github.com/bc19sam-afk/ASX_daily_stock_analysis/pull/112 | Contract-only input/decision layer; no realtime review implementation. |
| P2-2 Intraday Review v1 | complete | multiple | https://github.com/bc19sam-afk/ASX_daily_stock_analysis/pull/117 | Original v1 satisfied by contract, offline evaluator, file runner, and completion audit; no realtime quote adapter. |
| P2-3 ASX Official Announcement Check Contract | merged | `codex/p2-3-asx-official-announcement-check-contract` | https://github.com/bc19sam-afk/ASX_daily_stock_analysis/pull/118 | Contract/display/reliability only; no scraper or trading action changes. |
| P2-4 Daily Review Journal | merged | `codex/p2-4-daily-review-journal` | https://github.com/bc19sam-afk/ASX_daily_stock_analysis/pull/119 | Artifact-only review journal; no broker, account, portfolio, or daily-summary mutation. |

## Development Pause

- Status recorded on 2026-05-06 after main commit `a0a0456`.
- Pause all feature development until the next real daily report has been reviewed.
- Do not start P1-3b-3, realtime quote adapters, new roadmap items, broker integration, automatic trading, database migrations, workflow changes, or `close_only` changes without separate authorization.
- Stabilization / safety / contract / logging / date-consistency / dependency cleanup work may proceed only as small PRs from latest `origin/main`; do not submit old dirty worktree diffs directly.

## 2026-05-10 Stabilization Merge Chain

This chain closed the safety, contract, logging, dependency, date-consistency, and intraday-review visibility work without changing the automatic trading boundary, broker integration, ASX `close_only` default, or scheduling behavior.

| PR | Purpose | Merge commit |
| --- | --- | --- |
| #130 | API v1 optional auth guard | `82b26bbb092f372ef278c7f3c09849f7b4cfcbc8` |
| #128 | P0 decision safety + backtest visibility | `ecb83ebfd08f42b197e50bcbfc417c918c75374b` |
| #129 | P1 data leakage + risk controls | `4309971e6dfe04a3ac9d4782d158b030218f4b38` |
| #131 | Security-sensitive logging hardening | `0d1ddcb9dcaf4b8bff17735cb5adda17568fa68a` |
| #132 | P2 reliability and contract gaps | `abfb0ed8ce2a394bb0e523bb915f08c44c4f516c` |
| #133 | Frontend npm audit findings | `a1fadc6dcec10421e543bd002a3c1929e0be662f` |
| #134 | API auth / OpenAPI contract | `7fdff336cfd06bc54d67d5005206a0f7408c4394` |
| #135 | Report / technical basis date consistency | `858d87b3e48adc0650e56af08e39a507d5cf4ea0` |
| #136 | Intraday review manual checks | `60e43609a6360649c5852291b847f35e0d0f6f75` |

Final main after #136: `60e43609a6360649c5852291b847f35e0d0f6f75`.

Verification summary:

- Backend full pytest after the stabilization chain: `634 passed, 7 warnings`.
- Frontend npm audit after #133: `0 vulnerabilities`.
- PR3 intraday review targeted test after #136: `3 passed`.

Process notes:

- Old dirty worktree changes must be backed up and split into small PRs from latest `origin/main`.
- Do not apply old patches wholesale; inspect and migrate only the still-relevant hunks.
- Keep future stabilization PRs scoped: one task per PR, no automatic trading, no broker writes, no ASX `close_only` default changes, and no scheduling changes unless separately authorized.

## 2026-06-01 PR22 Morning Review Card

- Status: merged via GitHub PR #225, "Add Morning Review Card to daily email/report".
- Merge commit: `acc8033d6cd159e1bfc9bfe3f9fc486a60a3c863`.
- Scope: display-only Morning Review Card in the dashboard and legacy daily report bodies, reusing existing `daily_decision_summary` artifacts for conclusion, first symbols to review, reasons, key risks, report reliability, data-quality reminders, risk-sizing trial notes, and human-review wording.
- Changed files: `src/daily_decision_summary.py`, `src/notification.py`, and `tests/test_morning_review_card.py`.
- Local verification: `tests/test_morning_review_card.py`, report-body projection tests, daily-decision dashboard/archive tests, evidence integration tests, risk-sizing comparison/shadow tests, report readability guardrails, notification summary/validation tests, score bucket tests, `git diff --check`, targeted `py_compile`, and `./scripts/ci_gate.sh` with the project venv plus bundled Node on `PATH` (`870` tests plus `5` subtests passing).
- GitHub verification: backend gate, Docker build, change detection, security, static checks, AI review, and review report passed; desktop gate skipped by change detection.
- Boundary: no deterministic final action, position action, target weight, sizing write-back, notification send timing, default worker, Workbench/API expansion, provider order/cache change, live provider call, broker/execution, database migration, ledger v2 production write/cutover, secrets, HIN originals, account credentials, account numbers, order details, or fill detail exposure.
- Next candidate was completed by the PR23 real-email readability tune after the 2026-06-02 daily email. Future follow-up should again select one separate lane only, such as another report readability pass after a new real report, alert notification dry-run/default-off gate, broker-ready draft/paper boundary, explicit live provider telemetry, or ledger v2 follow-up after manual review.

## 2026-06-02 PR23 Morning Review Card Real-Email Readability

- Status: merged via GitHub PR #227, "Tune Morning Review Card readability", plus follow-up GitHub PR #229, "Polish Morning Review Card reliability labels".
- Merge commits: PR #227 `2c76715b5ed1e804e0ae73f85045bae932741985`; PR #229 `68edc7298f59e4dc67da115d5002bc5da1aedcf7`.
- Real email evidence: first real daily email subject `股票智能分析报告 - 2026-06-02`, Gmail messageId `19e85a61ef289ba5`, proved the Morning Review Card was active but the first screen still repeated the legacy `今日人工复核卡片`, mixed blocked/data-incomplete names into `先看这几只`, and made the data reliability cell too dense.
- Scope: display-only report/email readability micro-tune. PR #227 separated `今日优先复核`, `先补数据再判断`, and `低优先级观察`; removed the legacy review card from the pre-open first screen; shortened the data reliability row; and kept risk sizing as trial-only wording. PR #229 closed two Codex P2 follow-up comments by surfacing ASX announcement gaps in the Morning Review Card `主要缺口` row and keeping non-realtime mixed price labels in Chinese.
- Changed files: PR #227 changed `src/daily_decision_summary.py`, `tests/test_morning_review_card.py`, `tests/test_daily_decision_dashboard_archive.py`, and `tests/test_report_readability_guardrail.py`; PR #229 changed `src/daily_decision_summary.py` and `tests/test_morning_review_card.py`.
- Local verification: PR #227 targeted report/email readability tests passed and `./scripts/ci_gate.sh` passed with `872` tests plus `5` subtests; PR #229 targeted Morning Review Card, ASX announcement, report reliability, report readability, and dashboard/archive tests passed, `git diff --check` and targeted `py_compile` passed, and `./scripts/ci_gate.sh` passed with `874` tests plus `5` subtests.
- GitHub verification: PR #227 and PR #229 both passed backend gate, Docker build, change detection, security, static checks, AI review, and review report; desktop gate was skipped by change detection. PR #229 had no inline review comments and closed the actionable Codex P2 comments discovered after PR #227 merge.
- Boundary: no deterministic final action, position action, target weight, validation block, risk-sizing calculation, sizing write-back, strategy strip, portfolio card, alert worker, notification send, provider order/cache policy, live provider or paid data call, broker/execution, real account/order/fill handling, ledger v2 migration/cutover/production write, secrets, HIN originals, account numbers, or strategy/AI write-back to authoritative action fields.
- Next candidate: wait for another real report/email or select one separate Phase 2 lane; no worker, broker, notification delivery, live-provider call, persistence, provider-policy change, or ledger cutover is implied by PR23.

## Run Log

### 2026-05-05 - Roadmap Initialization

- Synced `main` with `git pull --ff-only`.
- Verified current branch was `main`.
- Verified working tree was clean before starting.
- Verified PR #99 merge commit was present in latest `main` history: `5752773 Keep AI prompt output behind deterministic action gates (#99)`.
- Created branch `codex/p0-2-conditional-plan-points-v1` from current `main`.
- Created roadmap plan at `docs/codex_implementation_plan.md`.
- Created execution log at `docs/codex_execution_log.md`.

### 2026-05-05 - P0-2 Audit

- Status: partial/missing.
- Scope: Conditional Plan Points v1 only.
- Forbidden areas unless explicitly required by P0-2: workflow, `close_only`, position manager, data provider, storage, database, broker integration, automatic trading.
- Finding: analyzer prompt already required conditional plan points, and existing validation gate hid some blocked single-stock point displays, but report exits still rendered naked or semi-naked AI point tables / observation reference lines without source, trigger condition, invalidation condition, price basis, technical basis date, and manual-review contract.
- Decision: implement minimal helper and report-display patch.

### 2026-05-05 - P0-2 Implementation

- Status: implemented.
- Added `src/conditional_plan.py` with `ConditionalPlanPoint` and markdown / inline rendering helpers.
- Updated `src/notification.py` point displays to render conditional plan points and return no displayable points for `BLOCK`.
- Added `tests/test_conditional_plan_points.py`.
- Added `tests/test_report_conditional_price_points.py`.
- Updated existing report-format assertions in `tests/test_notification_summary_format.py`.
- Test result: `python -m pytest tests/test_conditional_plan_points.py tests/test_report_conditional_price_points.py` passed, 6 tests.
- Test result: `python -m pytest tests/test_conditional_plan_points.py tests/test_report_conditional_price_points.py tests/test_notification_summary_format.py tests/test_notification_validation_gate.py tests/test_daily_decision_dashboard_archive.py` passed, 97 tests.
- Test result: `python -m pytest` passed, 454 tests, 6 warnings, 5 subtests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Scope check: no workflow, `close_only`, position manager, pipeline, data provider, storage, database, broker, or automatic trading changes.

### 2026-05-05 - P0-2 PR Opened

- Status: pr_opened.
- PR: https://github.com/bc19sam-afk/ASX_daily_stock_analysis/pull/100
- Original stop condition superseded by user authorization to auto-merge green P0 PRs and continue through P0-6.

### 2026-05-05 - P0-2 Merged

- Status: merged.
- PR: https://github.com/bc19sam-afk/ASX_daily_stock_analysis/pull/100
- Merge method: squash.
- Main commit: `38eff38 Keep report plan points conditional and review gated (#100)`.
- Post-merge sync: checked out `main`, pulled with `--ff-only`, verified clean working tree and P0-2 squash commit in latest main history.

### 2026-05-05 - P0-3 Audit

- Status: partial/missing.
- Scope: Evidence Matrix v1 only.
- Forbidden areas: no new external data source, ASX official announcement scraper, analysis logic change, position rule change, workflow change, `close_only` change, database migration, broker integration, or automatic trading.
- Finding: current main had daily action/data-quality summary fields but no `evidence_matrix`, no per-stock evidence categories, and no evidence quality dashboard / detail table.
- Decision: implement minimal evidence helper and report-display patch without feeding evidence back into action generation.

### 2026-05-05 - P0-3 Implementation

- Status: implemented.
- Added `src/evidence_matrix.py` with per-stock evidence rows for market data, technical, valuation, news, announcement, backtest, portfolio, and validation.
- Added optional `evidence_matrix` and `evidence_summary` to `daily_decision_summary`, with schema version `daily_decision_summary.v1.1`.
- Added dashboard evidence quality summary and per-stock evidence matrix table.
- Added `tests/test_evidence_matrix.py`.
- Added `tests/test_daily_decision_summary_evidence.py`.
- Updated `tests/test_daily_decision_dashboard_archive.py` schema stability coverage.
- Test result: `python -m pytest tests/test_evidence_matrix.py tests/test_daily_decision_summary_evidence.py tests/test_daily_decision_dashboard_archive.py` passed, 14 tests.
- Test result: `python -m pytest` passed, 459 tests, 6 warnings, 5 subtests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Scope check: no workflow, `close_only`, position manager, pipeline, data provider, storage, database, broker, or automatic trading changes.

### 2026-05-05 - P0-3 PR Opened

- Status: pr_opened.
- PR: https://github.com/bc19sam-afk/ASX_daily_stock_analysis/pull/101
- Checks: GitHub check runs all green before merge.
- Mergeability: `mergeable_state=clean`.

### 2026-05-05 - P0-3 Merged

- Status: merged.
- PR: https://github.com/bc19sam-afk/ASX_daily_stock_analysis/pull/101
- Merge method: squash.
- Main commit: `dc9be09 Keep evidence auditable before reliability scoring`.
- Post-merge sync: checked out `main`, pulled with `--ff-only`, verified clean working tree and P0-3 squash commit in latest main history.

### 2026-05-05 - P0-4 Audit

- Status: partial/missing.
- Scope: Report Reliability Score v1 only.
- Dependency check: P0-3 `evidence_matrix` is present in current main history via `dc9be09`.
- Forbidden areas: no buy/sell decision change, sizing change, validation gate change, workflow change, `close_only` change, database migration, broker integration, or automatic trading.
- Finding: current main had `evidence_matrix` and `evidence_summary`, but no `report_reliability` summary field, reliability score helper, or cockpit display explaining whether the report itself is suitable for pre-open manual review.
- Decision: implement a simple, transparent helper based on price policy, market data freshness, evidence completeness, validation health, and backtest support, without feeding the score back into deterministic actions.

### 2026-05-05 - P0-4 Implementation

- Status: implemented.
- Added `src/report_reliability.py` with `build_report_reliability` and dashboard rendering helpers.
- Added `report_reliability` to `daily_decision_summary`, with schema version `daily_decision_summary.v1.2`.
- Added report reliability display near the top of the pre-open cockpit.
- Added `tests/test_report_reliability_score.py`.
- Updated `tests/test_daily_decision_dashboard_archive.py` schema stability coverage.
- Test result: `python -m pytest tests/test_report_reliability_score.py tests/test_daily_decision_dashboard_archive.py` passed, 15 tests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Test result: `python -m pytest` passed, 465 tests, 6 warnings, 5 subtests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Scope check: no workflow, `close_only`, position manager, pipeline, data provider, storage, database, broker, or automatic trading changes.

### 2026-05-05 - P0-4 PR Opened

- Status: pr_opened.
- PR: https://github.com/bc19sam-afk/ASX_daily_stock_analysis/pull/102
- Checks: GitHub check runs all green before merge.
- Mergeability: `mergeable_state=clean`.

### 2026-05-05 - P0-4 Merged

- Status: merged.
- PR: https://github.com/bc19sam-afk/ASX_daily_stock_analysis/pull/102
- Merge method: squash.
- Main commit: `d7050ef Show report reliability before users review daily actions`.
- Post-merge sync: checked out `main`, pulled with `--ff-only`, verified clean working tree and P0-4 squash commit in latest main history.

### 2026-05-05 - P0-5 Audit

- Status: partial/missing.
- Scope: Final Action Display Contract only.
- Forbidden areas: no pipeline rewrite, `AnalysisResult` rewrite, database change, backtest engine change, AI output structure change, PositionManager action generation change, workflow change, or `close_only` change.
- Finding: current main centralized some action counts in `daily_decision_summary`, but had no `FinalActionDisplay` object and report exits still inferred display actionability separately.
- Decision: add a display-only helper and route daily summary / notification action display through it without changing deterministic action generation.

### 2026-05-05 - P0-5 Implementation

- Status: implemented.
- Added `src/final_action_display.py` with display-only actionability, sizing visibility, and plan-point visibility rules.
- Added `final_action_display` to daily decision summary action, watch, and blocked items.
- Updated notification actionability checks and recommended-action table rendering to consume the display object.
- Updated BLOCK report lines to show only unavailable / observe-only wording and validation reason, without target weight, delta, or plan points.
- Added `tests/test_final_action_display_contract.py`.
- Added `tests/test_blocked_action_display.py`.
- Updated existing dashboard, validation-gate, and recommended-action tests for the display contract.
- Test result: `python -m pytest tests/test_final_action_display_contract.py tests/test_blocked_action_display.py tests/test_daily_decision_dashboard_archive.py tests/test_notification_validation_gate.py` passed, 21 tests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Test result: `python -m pytest` passed, 472 tests, 6 warnings, 5 subtests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Scope check: no workflow, `close_only`, position manager, pipeline decision generation, data provider, storage, database, broker, or automatic trading changes.

### 2026-05-05 - P0-5 PR Opened

- Status: pr_opened.
- PR: https://github.com/bc19sam-afk/ASX_daily_stock_analysis/pull/103
- Checks: GitHub check runs all green before merge.
- Mergeability: `mergeable_state=clean`.

### 2026-05-05 - P0-5 Merged

- Status: merged.
- PR: https://github.com/bc19sam-afk/ASX_daily_stock_analysis/pull/103
- Merge method: squash.
- Main commit: `9dadbdd Unify report action display before rendering exits`.
- Post-merge sync: checked out `main`, pulled with `--ff-only`, verified clean working tree and P0-5 squash commit in latest main history.

### 2026-05-05 - P0-6 Audit

- Status: partial/missing.
- Scope: API Auth Guard v1 only.
- Forbidden areas: no user system, OAuth, role model, complex frontend login, workflow change, daily report change, `close_only` change, analysis pipeline change, broker integration, or automatic trading.
- Finding: current main had system config API endpoints and 401 response metadata, but no `API_AUTH_ENABLED` / `API_AUTH_TOKEN` contract, no Bearer token guard, and FastAPI docs still stated no authentication requirement.
- Decision: implement a minimal optional Bearer guard for system config endpoints only, keep `/api/health` public, and preserve default local/API compatibility when auth is disabled.

### 2026-05-05 - P0-6 Implementation

- Status: implemented.
- Added optional API auth dependency in `api/deps.py`, controlled by `API_AUTH_ENABLED` and `API_AUTH_TOKEN`.
- Protected `/api/v1/system/config*` endpoints through the system config router while leaving `/api/health` public.
- Updated FastAPI description, `.env.example`, `README.md`, and `README.zh-CN.md` to document optional Bearer auth.
- Added `tests/test_api_auth_guard.py`.
- Red test result before implementation: `python -m pytest tests/test_api_auth_guard.py` failed as expected because enabled auth still returned 200 for missing / wrong tokens.
- Test result: `python -m pytest tests/test_api_auth_guard.py` passed, 6 tests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Test result: `python -m pytest tests/test_system_config_api.py tests/test_server_runtime.py tests/test_spa_fallback.py` passed, 13 tests.
- Test result: `python -m pytest` passed, 478 tests, 6 warnings, 5 subtests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Scope check: no workflow, `close_only`, position manager, pipeline, data provider, storage, database, daily report, broker, or automatic trading changes.

### 2026-05-05 - P0-6 PR Opened

- Status: pr_opened.
- PR: https://github.com/bc19sam-afk/ASX_daily_stock_analysis/pull/104
- Checks: GitHub check runs all green before merge.
- Mergeability: `mergeable_state=clean`.

### 2026-05-05 - P0-6 Merged

- Status: merged.
- PR: https://github.com/bc19sam-afk/ASX_daily_stock_analysis/pull/104
- Merge method: squash.
- Main commit: `dbea81f Guard web configuration changes before public API exposure`.
- Post-merge verification: synced `main` with `--ff-only`, verified clean working tree, and completed post-P0 integration verification with no regressions.

### 2026-05-05 - P1-1 Audit

- Status: partial/missing.
- Scope: Backtest Confidence Panel v1 only.
- Forbidden areas: no backtest engine rewrite, analysis logic change, action generation change, PositionManager change, workflow change, `close_only` change, database migration, broker integration, or automatic trading.
- Finding: current main had backtest summaries and result rows, but no `backtest_confidence` summary field and no report cockpit panel showing historical calibration sample size, window, win rate, average simulated return, or low-sample warning.
- Decision: add a display-only helper fed by existing backtest summary/result rows; do not feed backtest confidence into deterministic action generation.

### 2026-05-05 - P1-1 Implementation

- Status: implemented.
- Added `src/backtest_confidence.py` with confidence panel builders and Markdown rendering.
- Added `BacktestService.get_confidence_panel()` as a read-only query over existing backtest summaries/results.
- Added `backtest_confidence` to `daily_decision_summary`, with schema version `daily_decision_summary.v1.3`.
- Added historical calibration lines to the pre-open decision cockpit.
- Added `tests/test_backtest_confidence_panel.py`.
- Updated `tests/test_daily_decision_dashboard_archive.py` schema stability coverage.
- Red test result before implementation: `python -m pytest tests/test_backtest_confidence_panel.py` failed as expected because `src.backtest_confidence`, the summary field, and report rendering did not exist.
- Test result: `python -m pytest tests/test_backtest_confidence_panel.py tests/test_backtest_service.py tests/test_daily_decision_dashboard_archive.py` passed, 29 tests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Test result: `python -m pytest tests/test_backtest_service.py tests/test_daily_decision_summary_evidence.py tests/test_report_reliability_score.py tests/test_final_action_display_contract.py` passed, 26 tests.
- Test result: `python -m pytest` passed, 485 tests, 6 warnings, 5 subtests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Scope check: no workflow, `close_only`, PositionManager, backtest engine, data provider, storage schema, database migration, broker, or automatic trading changes.

### 2026-05-05 - P1-1 Merged

- Status: merged.
- PR: https://github.com/bc19sam-afk/ASX_daily_stock_analysis/pull/105
- Merge method: squash.
- Main commit: `8317082 Show historical calibration without changing daily actions`.
- Post-merge verification: synced `main` with `--ff-only`, verified clean working tree, and kept the P1 scope limited to P1-1/P1-2.

### 2026-05-05 - P1-2 Audit

- Status: partial/missing.
- Scope: Score Bucket Calibration only.
- Forbidden areas: no backtest engine rewrite, analysis logic change, action generation change, PositionManager change, workflow change, `close_only` change, database migration, broker integration, or automatic trading.
- Finding: current main had P1-1 historical calibration lines, but no score-bucket summary, no current-score bucket mapping, and no report section that ties current scores to historical buckets.
- Decision: add a display-only score-bucket calibration helper fed by existing backtest rows plus current non-blocked report items; do not feed score buckets into deterministic action generation.

### 2026-05-05 - P1-2 Implementation

- Status: implemented.
- Added `score_bucket_calibration` helpers to `src/backtest_confidence.py` for 60_70 / 70_80 / 80_100 buckets and current-score mapping.
- Added `BacktestService.get_score_bucket_calibration()` as a read-only query over existing backtest rows and analysis scores.
- Added `score_bucket_calibration` to `daily_decision_summary`, with schema version `daily_decision_summary.v1.4`.
- Added score bucket lines to the pre-open decision cockpit.
- Added `tests/test_score_bucket_calibration.py`.
- Updated `tests/test_daily_decision_dashboard_archive.py` schema stability coverage.
- Red test result before implementation: `python -m pytest tests/test_score_bucket_calibration.py` failed as expected because score bucket calibration helpers and summary rendering did not exist.
- Test result: `python -m pytest tests/test_score_bucket_calibration.py` passed, 6 tests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Test result: `python -m pytest tests/test_score_bucket_calibration.py tests/test_backtest_confidence_panel.py tests/test_backtest_service.py tests/test_daily_decision_dashboard_archive.py` passed, 36 tests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Test result: `python -m pytest` passed, 492 tests, 6 warnings, 5 subtests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Scope check: no workflow, `close_only`, PositionManager, backtest engine, data provider, storage schema, database migration, broker, or automatic trading changes.

### 2026-05-05 - P1-3a Audit

- Status: partial/missing.
- Scope: Risk-Based Sizing Shadow Mode only.
- Forbidden areas: no deterministic sizing change, PositionManager output change, pipeline action generation change, workflow change, `close_only` change, data provider change, storage/database migration, broker integration, or automatic trading.
- Finding: current main had deterministic `target_weight` / `delta_amount` generated before daily summary, but no display-only risk-budget sizing preview and no report wording that made the preview explicitly shadow-only.
- Decision: add a read-only risk sizing preview helper and attach generated previews to `daily_decision_summary`; keep all existing deterministic action fields as the source of truth.

### 2026-05-05 - P1-3a Implementation

- Status: implemented.
- Added `src/core/risk_sizing.py` with `RiskSizingPreview` dictionary builders for shadow-mode risk budget, stop distance, cap constraints, unavailable states, and BLOCK handling.
- Added `risk_sizing_previews` to `daily_decision_summary`, with schema version `daily_decision_summary.v1.5`.
- Rendered a cockpit section labelled `风险仓位参考（Shadow，不改变今日动作）`, explicitly stating that the preview is for manual review and does not change today's deterministic action.
- Added conservative config/env fields for shadow preview: `RISK_SIZING_MODE`, `MAX_SINGLE_POSITION_WEIGHT`, `MAX_TRADE_RISK_PCT`, `ATR_STOP_MULTIPLIER`, and `MAX_DAILY_TURNOVER_PCT`.
- Added `tests/test_risk_based_sizing.py` and `tests/test_risk_sizing_shadow_mode.py`.
- Red test result before implementation: `python -m pytest tests/test_risk_based_sizing.py tests/test_risk_sizing_shadow_mode.py` failed as expected because `src.core.risk_sizing` and summary/report preview fields did not exist.
- Test result: `python -m pytest tests/test_risk_based_sizing.py tests/test_risk_sizing_shadow_mode.py tests/test_daily_decision_dashboard_archive.py` passed, 17 tests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Test result: `python -m pytest` passed, 500 tests, 6 warnings, 5 subtests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Scope check: no workflow, `close_only`, PositionManager, pipeline action generation, data provider, storage, database, broker, or automatic trading changes.

### 2026-05-05 - P1-3a Merged And Post-Verification

- Status: merged.
- PR: https://github.com/bc19sam-afk/ASX_daily_stock_analysis/pull/107
- Merge method: squash.
- Main commit: `03c8fa9 Show risk sizing without changing daily actions (#107)`.
- Post-merge verification: synced `main` with `--ff-only`, verified clean working tree, and completed post-P1-3a integration verification.
- Test result: `python -m pytest tests/test_risk_based_sizing.py` passed.
- Test result: `python -m pytest tests/test_risk_sizing_shadow_mode.py` passed.
- Test result: `python -m pytest tests/test_daily_decision_dashboard_archive.py` passed.
- Test result: `python -m pytest tests/test_final_action_display_contract.py tests/test_blocked_action_display.py` passed.
- Test result: `python -m pytest tests/test_report_reliability_score.py` passed.
- Test result: `python -m pytest` passed, 500 tests, 6 warnings, 5 subtests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Semantic audit: risk sizing preview stayed shadow-only, did not change deterministic action fields or action counts, and BLOCK items remained unavailable / observe-only.

### 2026-05-05 - P1-4 Audit

- Status: partial/missing.
- Scope: Structured Valuation Snapshot only.
- Forbidden areas: no decision change, sizing change, action count change, workflow change, `close_only` change, PositionManager change, pipeline change, database migration, broker integration, or automatic trading.
- Finding: yfinance still exposed valuation through legacy `pe_ratio` and concatenated dividend yield into the PE display string; reports and evidence did not prefer a structured valuation snapshot.
- Decision: add a lightweight `ValuationSnapshot` to realtime quote output, preserve legacy `pe_ratio` compatibility as numeric PE, and render valuation as evidence/display only.

### 2026-05-05 - P1-4 Implementation

- Status: implemented.
- Added `ValuationSnapshot` to `data_provider/realtime_types.py` and included it in `UnifiedRealtimeQuote.to_dict()` when present.
- Updated `YfinanceFetcher.get_realtime_quote()` to populate structured PE, forward PE, PB, dividend yield, market cap, ROE, debt-to-equity, source, and as-of date without appending dividend yield to `pe_ratio`.
- Updated valuation evidence to prefer `market_snapshot.valuation_snapshot` while retaining legacy fundamental prose fallback.
- Added structured valuation rendering to single-stock reports, including missing-field display and an explicit note that valuation evidence does not change deterministic actions.
- Added `tests/test_yfinance_valuation_snapshot.py`.
- Updated `tests/test_evidence_matrix.py` for valuation snapshot evidence.
- Red test result before implementation: `python -m pytest tests/test_yfinance_valuation_snapshot.py tests/test_evidence_matrix.py tests/test_daily_decision_dashboard_archive.py` failed because structured valuation fields and report rendering were missing and dividend yield was still joined into `pe_ratio`.
- Test result: `python -m pytest tests/test_yfinance_valuation_snapshot.py tests/test_evidence_matrix.py tests/test_daily_decision_dashboard_archive.py` passed, 20 tests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Test result: `python -m pytest` passed, 508 tests, 6 warnings, 5 subtests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Scope check: no workflow, `close_only`, PositionManager, pipeline, storage, database, broker, or automatic trading changes.

### 2026-05-05 - P1-4 PR Opened

- Status: pr_opened.
- PR: https://github.com/bc19sam-afk/ASX_daily_stock_analysis/pull/108
- Read-only review: no blocking findings after the missing valuation `as_of_date` fallback was fixed.

### 2026-05-05 - P1-4 Merged And Post-Verification

- Status: merged.
- PR: https://github.com/bc19sam-afk/ASX_daily_stock_analysis/pull/108
- Merge method: squash.
- Main commit: `58f3c93 Expose valuation as evidence without changing daily actions`.
- GitHub checks: all green before merge; mergeability `clean`.
- Post-merge verification: synced `main` with `--ff-only`, verified clean working tree, and ran P1-4 post-verification.
- Test result: `python -m pytest tests/test_yfinance_valuation_snapshot.py` passed, 5 tests.
- Test result: `python -m pytest tests/test_evidence_matrix.py` passed, 6 tests.
- Test result: `python -m pytest tests/test_daily_decision_dashboard_archive.py` passed, 9 tests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Test result: `python -m pytest tests/test_report_reliability_score.py` passed, 6 tests.
- Test result: `python -m pytest` passed, 508 tests, 6 warnings, 5 subtests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Semantic audit: structured valuation remained evidence/display only, missing valuation stayed explicit, BLOCK items did not become actionable, and action counts / deterministic action fields were unchanged.

### 2026-05-05 - P1-5 Audit

- Status: partial/missing.
- Scope: ASX Search Localisation only.
- Forbidden areas: no ASX official announcement source, search service rewrite, `news_max_age_days` default change, Chinese compatibility removal, decision change, sizing change, action count change, workflow change, `close_only` change, database migration, broker integration, or automatic trading.
- Finding: current main already included ASX/Australia grounded query terms and ASX entity disambiguation, but ASX news queries did not explicitly signal English-first context, SerpAPI still used HK/CN Chinese locale parameters, and Brave still used US country parameters.
- Decision: keep the existing provider order, fallback, news age filter, and entity filter; only add English-first ASX query context and switch SerpAPI / Brave request parameters to AU/en when the query is ASX-localised.

### 2026-05-05 - P1-5 Implementation

- Status: implemented.
- Added `tests/test_search_asx_localisation.py` covering ASX query context, SerpAPI AU/en parameters, Brave AU/en parameters, non-ASX compatibility, and ASX entity disambiguation.
- Updated ASX grounded queries to include `English-first` alongside ASX and Australia.
- Added a shared provider helper for ASX-localised query detection.
- Updated SerpAPI ASX queries to use `google.com.au`, `hl=en`, and `gl=au` while preserving existing non-ASX defaults.
- Updated Brave ASX queries to use `country=AU` and `search_lang=en` while preserving existing non-ASX defaults.
- Red test result before implementation: `python -m pytest tests/test_search_asx_localisation.py tests/test_search_news_age_filter.py` failed as expected because English-first query context and AU provider parameters were missing.
- Test result: `python -m pytest tests/test_search_asx_localisation.py tests/test_search_news_age_filter.py` passed, 18 tests.
- Read-only review finding: the initial provider ASX-localisation helper matched any query containing `Australia`, which could alter non-ASX queries such as `Apple Australia AAPL latest news`; fixed by requiring explicit `.AX` or standalone `ASX` markers and adding regression coverage.
- Test result: `python -m pytest tests/test_search_asx_localisation.py tests/test_search_news_age_filter.py tests/test_search_entity_disambiguation.py` passed, 35 tests.
- Test result: `python -m pytest` passed, 517 tests, 6 warnings, 5 subtests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Scope check: no workflow, `close_only`, PositionManager, pipeline, storage, database, broker, automatic trading, or deterministic action changes.

### 2026-05-05 - P1-5 PR Opened

- Status: pr_opened.
- PR: https://github.com/bc19sam-afk/ASX_daily_stock_analysis/pull/109
- Read-only review: no blocking findings after tightening ASX provider localisation to explicit `.AX` or standalone `ASX` markers.

### 2026-05-05 - P1-3b-1 Audit

- Status: partial/missing.
- Scope: Risk-Based Sizing Cap Calculation only.
- Forbidden areas: no enabled cap behavior, no target/delta/action/final decision/validation/action count change, no PositionManager output change, no workflow change, no `close_only` change, no data provider or storage change, no broker integration, no automatic trading, no database migration, no LLM prompt change, and no intraday review change.
- Finding: P1-3a already had a shadow-only risk sizing preview, but no standalone cap candidate structure for future enabled-mode comparison and no formal `shadow|enabled` mode normalization.
- Decision: add a deterministic `RiskSizingCapCandidate` helper that calculates candidate caps only when explicitly called with `mode=enabled`, never writes back, and is covered by focused tests for mode gating, cap math, missing data, BLOCK hard stop, buy/add no-forced-sell guard, and default compatibility.

### 2026-05-05 - P1-3b-1 Implementation

- Status: implemented.
- Added `build_risk_sizing_cap_candidate()` and `RiskSizingCapCandidate` in `src/core/risk_sizing.py`; shadow mode returns a no-change candidate instead of calculating a cap.
- Normalized risk sizing mode to `shadow|enabled`, defaulting invalid or missing values to `shadow`.
- Added `tests/test_risk_sizing_cap_calculation.py`.
- Updated `.env.example` and `src/config.py` comments to keep `shadow` as the default and warn that enabled mode requires explicit review before behavior changes.
- Test result: `python -m pytest tests/test_risk_based_sizing.py tests/test_risk_sizing_cap_calculation.py tests/test_risk_sizing_shadow_mode.py` passed, 16 tests.
- Test result: `python -m pytest` passed, 526 tests, 6 warnings, 5 subtests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Scope check: no pipeline write-back, PositionManager behavior, workflow, `close_only`, data provider, storage, broker, automatic trading, database, LLM prompt, or intraday review changes.

### 2026-05-05 - P1-3b-1 Merged And Post-Verification

- Status: merged.
- PR: https://github.com/bc19sam-afk/ASX_daily_stock_analysis/pull/110
- Merge method: squash.
- Main commit: `9d19b6a Prepare risk caps without changing daily sizing`.
- GitHub checks: all green before merge; mergeability `clean`.
- Post-merge verification: synced `main` with `--ff-only`, verified clean working tree, and ran P1-3b-1 post-verification.
- Test result: `python -m pytest tests/test_risk_based_sizing.py tests/test_risk_sizing_cap_calculation.py tests/test_risk_sizing_shadow_mode.py` passed, 17 tests.
- Test result: `python -m pytest tests/test_daily_decision_dashboard_archive.py` passed, 9 tests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Test result: `python -m pytest tests/test_final_action_display_contract.py tests/test_blocked_action_display.py` passed, 7 tests.
- Test result: `python -m pytest` passed, 526 tests, 6 warnings, 5 subtests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Semantic audit: default `shadow` still does not calculate/write back cap candidates; enabled candidates remain helper-only; BLOCK returns unavailable and does not become actionable.

### 2026-05-05 - P1-3b-2 Audit

- Status: partial/missing.
- Scope: Risk Sizing Report Comparison / Dry Run only.
- Forbidden areas: no enabled cap behavior, no target/delta/action/final decision/validation/action count change, no PositionManager output change, no workflow change, no `close_only` change, no data provider or storage change, no broker integration, no automatic trading, no database migration, no LLM prompt change, and no intraday review change.
- Finding: P1-3b-1 provided a config-gated cap candidate helper, but `daily_decision_summary` and the pre-open dashboard did not expose a dry-run comparison between the current deterministic target and a future risk-capped candidate.
- Decision: add a `risk_sizing_comparison` summary artifact and dashboard section labelled Dry Run, calculated from the existing candidate helper with no write-back to action fields.

### 2026-05-05 - P1-3b-2 Implementation

- Status: implemented.
- Added `build_risk_sizing_comparisons()` and `render_risk_sizing_comparison_lines()` in `src/core/risk_sizing.py`.
- Added `risk_sizing_comparison` to `daily_decision_summary` with schema version `daily_decision_summary.v1.6`.
- Rendered `风险仓位对比（Dry Run，不改变今日动作）`, showing current system target, risk-capped candidate, difference, constraints, and explicit no-action-change wording.
- BLOCK items render comparison unavailable with `validation BLOCK，仅观察`; missing close / stop distance renders unavailable without guessing.
- Added `tests/test_risk_sizing_dry_run_comparison.py` and updated the dashboard archive schema test.
- Test result: `python -m pytest tests/test_risk_sizing_dry_run_comparison.py tests/test_daily_decision_dashboard_archive.py` passed, 13 tests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Test result: `python -m pytest` passed, 530 tests, 6 warnings, 5 subtests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Scope check: no target_weight, delta_amount, position_action, final_decision, validation_status, action_counts, PositionManager, workflow, `close_only`, data provider, storage, broker, automatic trading, database, LLM prompt, or intraday review changes.

### 2026-05-05 - P1-3b-2 Merged And Post-Verification

- Status: merged.
- PR: https://github.com/bc19sam-afk/ASX_daily_stock_analysis/pull/111
- Merge method: squash.
- Main commit: `1414505 Show risk cap comparisons without changing actions`.
- GitHub checks: all green before merge; mergeability `clean`.
- Post-merge verification: synced `main` with `--ff-only`, verified clean working tree, and ran P1-3b-2 post-verification.
- Test result: `python -m pytest tests/test_risk_sizing_dry_run_comparison.py` passed, 4 tests.
- Test result: `python -m pytest tests/test_risk_based_sizing.py tests/test_risk_sizing_cap_calculation.py tests/test_risk_sizing_shadow_mode.py` passed, 17 tests.
- Test result: `python -m pytest tests/test_daily_decision_dashboard_archive.py` passed, 9 tests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Test result: `python -m pytest tests/test_final_action_display_contract.py tests/test_blocked_action_display.py` passed, 7 tests.
- Test result: `python -m pytest` passed, 530 tests, 6 warnings, 5 subtests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Semantic audit: dry-run comparison remained display-only, did not change deterministic action fields or action counts, and BLOCK items stayed unavailable / non-actionable.

### 2026-05-05 - P2-1 Audit

- Status: missing.
- Scope: Intraday Review Input Contract only.
- Forbidden areas: no realtime quote fetching, no intraday strategy implementation, no daily report change, no AI re-decision, no broker integration, no automatic trading, no account writes, no workflow change, and no `close_only` change.
- Finding: roadmap documentation mentioned future `intraday_review`, but no contract module, tests, or intraday review docs existed.
- Decision: add a standalone contract module with serializable input/decision types and validation rules, plus contract docs; keep it disconnected from daily report generation and all realtime/data-source paths.

### 2026-05-05 - P2-1 Implementation

- Status: implemented.
- Added `src/intraday_review_contract.py` with `IntradayReviewInput`, `IntradayReviewDecision`, `build_intraday_review_input_from_summary()`, and `validate_intraday_review_decision()`.
- Added `docs/intraday_review.md` documenting contract-only scope and future P2-2 guardrails.
- Added `tests/test_intraday_review_contract.py` covering summary-to-input construction, required `price_policy`, BLOCK-only `observe_only|block` statuses, serialization round-trip, and no AI/data-source imports.
- Test result: initial `python -m pytest tests/test_intraday_review_contract.py` failed because the import-safety test matched boundary text rather than imports; fixed within test scope to inspect AST imports.
- Test result: `python -m pytest tests/test_intraday_review_contract.py tests/test_daily_decision_dashboard_archive.py` passed, 14 tests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Test result: `python -m pytest` passed, 535 tests, 6 warnings, 5 subtests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Scope check: no daily report changes, realtime quote fetching, data provider calls, AI calls, workflow, `close_only`, broker, automatic trading, account writes, storage, or database migration.

### 2026-05-06 - P2-2a Audit

- Status: missing.
- Scope: Offline Intraday Review Evaluator only.
- Forbidden areas: no realtime quote fetching, no data provider/yfinance/external API calls, no AI calls, no broker integration, no automatic trading, no account writes, no workflow change, no `close_only` daily report change, no PositionManager change, no P1-3b-3 risk sizing cap enablement, and no database migration.
- Finding: P2-1 defined input and decision contracts, but there was no offline evaluator that could consume caller-supplied prices and produce manual-review statuses.
- Decision: add a pure rules evaluator in `src/intraday_review.py`, extend the contract with offline market/evaluation types, and keep all inputs caller/test supplied.

### 2026-05-06 - P2-2a Implementation

- Status: implemented.
- Added `IntradayReviewMarketInput` and `IntradayReviewEvaluation` contract types.
- Added `evaluate_intraday_review_offline()` with conservative thresholds: wait above 2% absolute deviation and cancel above 5% absolute deviation.
- BLOCK morning items can only produce `observe_only` or `block`; `price_sensitive_risk=True` produces `block`.
- Missing `last_price` or `previous_close` degrades to `observe_only` without guessing.
- Liquidity warnings produce `wait` for actionable items or `observe_only` for non-actionable items.
- PASS/actionable items inside the wait threshold return `still_valid` for manual review only, with `is_trade_instruction=False`.
- Added `tests/test_intraday_review_offline_evaluator.py` and extended contract serialization coverage.
- Red test result before implementation: `python -m pytest tests/test_intraday_review_offline_evaluator.py` failed because `src.intraday_review` did not exist.
- Test result: `python -m pytest tests/test_intraday_review_offline_evaluator.py tests/test_intraday_review_contract.py` passed, 14 tests.
- Test result: `python -m pytest tests/test_daily_decision_dashboard_archive.py` passed, 9 tests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Test result: `python -m pytest` passed, 544 tests, 6 warnings, 5 subtests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Scope check: evaluator imports only contract/typing modules, does not call realtime data, AI, data providers, brokers, storage, workflow, or daily report generation, and does not mutate input summary/action counts.

### 2026-05-06 - R0 Report Readability Guardrail Audit

- Status: missing.
- Scope: homepage readability only for the pre-open daily report.
- Forbidden areas: no `final_decision`, `position_action`, `target_weight`, `delta_amount`, `action_counts`, `validation_status`, `PositionManager`, pipeline, data provider, workflow, `close_only`, realtime quotes, broker integration, or automatic trading changes.
- Finding: the report homepage had become audit-heavy, with evidence matrix, calibration panels, risk sizing detail, conditional point explanations, and repeated disclaimer wording crowding out the actual morning action summary.
- Decision: keep the homepage to a one-screen operator summary, move evidence / calibration / risk sizing detail into an appendix section, collapse repetitive warnings into short action-oriented copy, and preserve deterministic action semantics unchanged.

### 2026-05-06 - R0 Report Readability Guardrail Implementation

- Status: implemented.
- Compact homepage now keeps only `今日结论`, `今日动作数量`, `当前持仓需要处理什么`, `Top actionable items`, `Top risks / BLOCK`, one-line `报告可信度`, `价格口径`, and one-line `执行前检查`.
- Added appendix rendering for evidence summary/matrix, backtest confidence, score bucket calibration, and risk sizing shadow/dry-run sections so audit detail remains available without dominating the first screen.
- Reduced repeated disclaimer wording and kept a single footer disclaimer: `仅作计划，供人工决策辅助；系统不自动下单。`
- Added `tests/test_report_readability_guardrail.py` and updated report/archive tests to lock the new homepage-vs-appendix contract, including a mixed-price-policy banner regression.
- Test result: `python -m pytest tests/test_report_readability_guardrail.py tests/test_daily_decision_dashboard_archive.py` passed, 13 tests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Test result: `python -m pytest` passed, 548 tests, 6 warnings, 5 subtests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Scope check: presentation-only change; deterministic action fields, BLOCK semantics, validation gate behavior, and `close_only` planning context remained unchanged.

### 2026-05-06 - R1 Report Body Deduplication Audit

- Status: missing.
- Scope: report body structure after the compact homepage.
- Forbidden areas: no `final_decision`, `position_action`, `target_weight`, `delta_amount`, `action_counts`, `validation_status`, `PositionManager`, pipeline, data provider, workflow, `close_only`, broker integration, or automatic trading changes.
- Finding: after R0, the homepage was readable, but the body still repeated the same action information across `今日行动摘要`, `当前持仓总览`, `当前持仓行动清单`, and `目标仓位模拟（计划视图）`.
- Decision: keep the homepage unchanged, collapse body holdings content into one main action section, rename the non-holding section to `新开仓 / 观察清单`, and move simulated target allocation plus audit/time-basis material into the appendix path.

### 2026-05-06 - R1 Report Body Deduplication Implementation

- Status: implemented.
- Replaced the repeated body sequence with `当前持仓动作` and `新开仓 / 观察清单`, preserving one main holdings action table plus a compact risk/remediation block.
- Moved `目标仓位模拟` out of the main reading path into `详情 / 审计附录` as `计划仓位模拟（附录）`, alongside audit scope and data-basis disclosure.
- Restored appendix-level auditability with a compact `持仓估值与覆盖（附录）` table and explicit failed / uncovered compact lists, without re-expanding the body into duplicate overview blocks.
- Normalized `legacy_report_time` display disclosure back to the close-basis path so appendix valuation labels and report-level price-basis wording stay consistent.
- Preserved stock detail rendering and audit appendix content for evidence summary/matrix, backtest confidence, score bucket calibration, and risk sizing shadow/dry-run sections.
- Added `tests/test_report_body_deduplication.py` and updated validation-gate rendering assertions to the new body contract.
- Updated broader notification rendering regression coverage so the appendix now locks holdings valuation source, analysis coverage, reconciliation weights, failure visibility, and the R1 body ordering contract.
- Scope check: presentation-only change; deterministic action fields, BLOCK semantics, validation-gate behavior, and `close_only` planning context remained unchanged.

### 2026-05-06 - P2-2b Audit

- Status: missing.
- Scope: file-based intraday review runner only.
- Forbidden areas: no realtime quote fetching, no yfinance/data_provider/external API calls, no AI calls, no broker integration, no automatic trading, no account writes, no workflow change, no `close_only` daily report change, no PositionManager change, no P1-3b-3 risk sizing cap enablement, no database migration, and no P2-2c realtime adapter.
- Finding: P2-2a exposed a pure offline evaluator, but there was no local-file runner that could read a morning `daily_decision_summary`, consume externally supplied market input, and write auditable intraday review artifacts.
- Decision: keep the runner independent from `main.py` and daily workflow by adding `scripts/run_intraday_review.py`, with file reading/writing logic in `src/intraday_review.py`.

### 2026-05-06 - P2-2b Implementation

- Status: implemented.
- Added `run_intraday_review_file()` to read a local summary JSON and local market-input JSON, run the offline evaluator, and write `intraday_review_YYYYMMDD.json` plus `intraday_review_YYYYMMDD.md`.
- Added `scripts/run_intraday_review.py` as an explicit CLI for file-based review only.
- Output items include `required_checks`, `source`, and `is_trade_instruction=false`; extra market-input symbols are ignored with warnings.
- Missing market input degrades to `observe_only` with a `missing_input` reason.
- Markdown output is intentionally short: data source, no automatic order placement, and manual checks before action.
- Added `tests/test_intraday_review_runner.py`.
- Red test result before implementation: `python -m pytest tests/test_intraday_review_runner.py` failed because `scripts.run_intraday_review` did not exist.
- Test result: `python -m pytest tests/test_intraday_review_runner.py tests/test_intraday_review_offline_evaluator.py tests/test_intraday_review_contract.py` passed, 17 tests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Test result: `python -m pytest tests/test_report_readability_guardrail.py tests/test_report_body_deduplication.py tests/test_daily_decision_dashboard_archive.py` passed, 16 tests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Test result: `python -m pytest` passed, 554 tests, 6 warnings, 5 subtests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Scope check: runner reads only local files, writes only intraday review JSON/Markdown artifacts, does not call realtime data, AI, data providers, brokers, storage, workflow, or daily report generation, and does not mutate input summary/action counts.

### 2026-05-06 - P2-2 Intraday Review v1 Completion Audit

- Status: complete.
- Scope: original roadmap item `P2-2 Intraday Review v1`.
- Audit result: current `main` satisfies the minimal P2-2 v1 contract through the independent intraday review contract, offline evaluator, and file-based runner.
- Evidence: `scripts/run_intraday_review.py` reads a morning `daily_decision_summary` and caller-supplied `market_input.json`; `run_intraday_review_file()` writes independent `intraday_review_YYYYMMDD.json` and `intraday_review_YYYYMMDD.md` artifacts.
- Interpretation: the original roadmap wording "拉取或获得盘中价格" is satisfied for v1 by "获得盘中价格" through explicit file input. Realtime quote fetching is not required for P2-2 v1 and remains out of scope until separately authorized.
- Boundary check: no default daily workflow integration, no `close_only` daily report changes, no AI calls, no data provider calls, no broker integration, no automatic trading, no account writes, and no mutation of morning `final_decision`, `position_action`, `target_weight`, `delta_amount`, `action_counts`, or `validation_status`.
- BLOCK check: BLOCK morning items remain `observe_only` or `block` and cannot become `still_valid`.
- Decision: mark P2-2 complete and continue to original roadmap item `P2-3 ASX Official Announcement Check Contract`.

### 2026-05-06 - P2-3 ASX Official Announcement Check Contract

- Status: implemented.
- Scope: original roadmap item `P2-3 ASX Official Announcement Check Contract`.
- Added a contract-only `ASXAnnouncementCheck` status model with `clear`, `risk_found`, `unavailable`, and `not_checked`; default/unconfigured checks remain `not_checked`.
- Evidence matrix now preserves ASX announcement status explicitly, never falls back from `unavailable` or `not_checked` to `clear`, and treats `risk_found` as a block-severity evidence flag without changing deterministic actions.
- Report reliability now flags and deducts for ASX announcement `not_checked`, `unavailable`, and `risk_found`; this is report evidence only and does not feed back into `final_decision`, `position_action`, sizing, validation gates, or action counts.
- No scraper, paid API, realtime data source, AI call, broker integration, automatic trading, workflow change, `close_only` change, storage change, PositionManager change, or database migration was added.
- Red test result before implementation: `python -m pytest tests/test_asx_announcement_contract.py` failed because `src.asx_announcements` did not exist.
- Test result: `python -m pytest tests/test_asx_announcement_contract.py` passed, 5 tests.
- Test result: `python -m pytest tests/test_asx_announcement_contract.py tests/test_evidence_matrix.py tests/test_report_reliability_score.py tests/test_report_readability_guardrail.py` passed, 21 tests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Test result: `python -m pytest tests/test_daily_decision_dashboard_archive.py` passed, 9 tests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Test result: `python -m pytest` passed, 559 tests, 6 warnings, 5 subtests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Scope check: P2-3 remains contract/display/reliability only; morning `daily_decision_summary` action fields and counts remain unchanged.

### 2026-05-06 - P2-4 Daily Review Journal

- Status: implemented.
- Scope: original roadmap item `P2-4 Daily Review Journal`.
- Added a local JSON artifact helper for `reports/review_journal_YYYYMMDD.json` with schema version `review_journal.v1`.
- Journal initialization records morning actions from an existing `daily_decision_summary` without mutating the summary or changing `final_decision`, `position_action`, `target_weight`, `delta_amount`, `validation_status`, or action counts.
- Intraday review results can be appended with a source review path; manual execution notes are append-only and always marked `user_provided=true`.
- Existing journal writes preserve prior manual notes, post-trade notes, and intraday review entries instead of replacing the artifact wholesale.
- Added `docs/review_journal.md` to document that the journal is a review artifact, not a broker ledger, trading system, account writer, or portfolio updater.
- Red test result before implementation: `python -m pytest tests/test_review_journal.py` failed because `src.review_journal` did not exist.
- Test result: `python -m pytest tests/test_review_journal.py` passed, 6 tests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Test result: `python -m pytest tests/test_intraday_review_runner.py tests/test_intraday_review_contract.py` passed, 8 tests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Test result: `python -m pytest tests/test_report_readability_guardrail.py tests/test_report_body_deduplication.py tests/test_daily_decision_dashboard_archive.py` passed, 16 tests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Test result: `python -m pytest` passed, 565 tests, 6 warnings, 5 subtests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Scope check: P2-4 records and appends review artifacts only; it does not connect brokers, write accounts, infer real fills, modify portfolio holdings, mutate daily summary fields, or affect `close_only` report generation.

### 2026-05-28 - ASX Official Announcements Source v1

- Status: implemented.
- Scope: small PR from `main` HEAD `b36a15266eb11a9a17ed3249b7298079f7b174aa`; add ASX official Market Announcements as a read-only, best-effort evidence source.
- Added batched ASX listing-page metadata fetch in `src/asx_announcements.py`: one today request plus, when lookback is positive, at most one previous-trading-day request. Requests use a User-Agent, cap per-page timeout at 10 seconds, catch network/timeout/parse errors, and return `unavailable` rather than pretending `clear`.
- Parsed only listing metadata: code, date/published_at, headline, URL, price-sensitive marker, and optional pages/size. The implementation does not download PDFs or parse PDF bodies.
- Integrated checks into daily summary evidence through `announcement_checks`, `evidence_matrix`, `evidence_summary`, `report_reliability`, and manual review prompts. `risk_found` and `unavailable` are display-only confirmation gaps; they do not change `final_decision`, `position_action`, `target_weight`, `delta_amount`, `action_counts`, `actionable_items`, `blocked_items`, validation gates, or simulated paper-portfolio writes.
- Added config/workflow defaults: `ASX_ANNOUNCEMENTS_ENABLED=true`, `ASX_ANNOUNCEMENTS_LOOKBACK_DAYS=1`, `ASX_ANNOUNCEMENTS_MAX_ITEMS=5`, and `ASX_ANNOUNCEMENTS_TIMEOUT_SECONDS=10`. Daily workflow passes these as vars/defaults only; no new secrets.
- Updated `.env.example`, README, full guide, and deployment docs to state this is a read-only evidence source for manual review, not a realtime quote source, not an order-execution basis, and not a broker interface.
- Added mocked ASX HTML/response tests for clear, `risk_found`, `unavailable`, ASX canonicalization, non-ASX skip, price-sensitive marker parsing, risk headline matching, page-structure fail-open, and network/timeout degradation.
- Red test result before implementation: `python -m pytest tests/test_asx_announcements_fetcher.py ...` failed because `ASX_TODAY_ANNOUNCEMENTS_URL` and the fetcher API did not exist.
- Test result: `python -m pytest tests/test_asx_announcement_contract.py tests/test_evidence_matrix.py tests/test_report_reliability_score.py` passed, 23 tests.
- Test result: `python -m pytest -m "not network"` passed, 757 tests, 7 warnings, 5 subtests; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Test result: `npm run smoke` from `apps/dsa-desktop` passed (`desktop smoke OK`).
- Test result: `python -m compileall -q src` passed.
- Scope check: no search provider changes, no `max_searches`, no persistent search cache, no Web dashboard, no CSV import, no alert center, no broker integration, no real-account trading, no automatic order placement, and no deterministic action/sizing mutation.

### 2026-05-28 - Documentation Boundary Sync

- Status: implemented.
- Scope: docs-only branch from `main` HEAD `55864458b32cd4bc85f004638de0346820727e4e`; align README, full guide, roadmap, and execution log wording with the current AGENTS boundary and completed ASX official announcements source.
- Replaced temporary per-change broker/execution disclaimers in README and full-guide content with long-term product language: ASX Market Announcements is read-only evidence for manual review and does not provide realtime quotes, order execution, or broker connectivity.
- Updated the roadmap to keep human-in-the-loop as the default while allowing explicitly scoped broker, real-account, or order-execution work to be designed separately.
- Marked P2-3 as completed and implemented: conservative announcement-check contract plus ASX official Market Announcements listing metadata source v1.
- Preserved the implementation boundary that the source reads listing metadata only; do not build brittle PDF scraping, download PDFs, parse PDF bodies, or claim unchecked announcements are clear.

### 2026-05-28 - ASX Roadmap P2-P4 Delivery Chain

- Status: merged.
- Scope: roadmap phases 2-4, each delivered as its own PR from latest `main` and merged only after Actions were green.
- P2 PR: `https://github.com/bc19sam-afk/ASX_daily_stock_analysis/pull/179` | merge commit `37e522ab680784dffe6ac3263e4bc53093df2cc9` | `ASX AnalysisContextPack v1`.
- P3 PR: `https://github.com/bc19sam-afk/ASX_daily_stock_analysis/pull/180` | merge commit `83a0559b8769a63b1482f97e4995c893e1ba5224` | `Minimal Web Workbench v1`.
- P4 PR: `https://github.com/bc19sam-afk/ASX_daily_stock_analysis/pull/181` | merge commit `d113358bde0c0446bf39a4aeaaec41fac1604764` | `ASX Portfolio Ledger / CSV Import v1`.
- Final main HEAD: `d113358bde0c0446bf39a4aeaaec41fac1604764`.
- Verification: `python -m pytest tests/test_asx_portfolio_import.py tests/test_manual_portfolio_workflows.py tests/test_portfolio_integrity_checks.py tests/test_position_management_accounting.py -m "not network"` passed, 71 tests / 5 subtests; `python -m compileall -q src scripts` passed.
- Actions: PR #181 checks were green before merge; backend-gate passed and the other required checks passed or skipped according to change scope.
- Boundary: the chain stayed local to analysis context, a minimal workbench, and a manual ledger import path; no broker API, no real account reads, and no automatic order placement.
- Next step: ASX-aware alert center.

### 2026-05-29 - ASX-aware Alert Center v1

- Status: implemented on branch `codex/asx-aware-alert-center-v1`; publication details are tracked in GitHub PR / merge history.
- Scope: read-only Alert Center for the minimal Web Workbench and API, aggregating "today's must-review" risks from existing report history, `daily_decision_summary`, `evidence_matrix`, `report_reliability`, ASX announcement evidence, AnalysisContextPack risk context, and optional portfolio import / integrity results.
- Added `src/alert_center.py` with stable alert items: `id`, `category`, `severity`, `code`, `title`, `message`, `source`, `as_of`, `action_hint`, and `is_trade_instruction=false`.
- Added `/api/v1/workbench/alerts` and `/api/v1/workbench/alerts/summary`, and embedded `alert_center` in `/api/v1/workbench/summary`.
- Updated the static Web Workbench first screen with a `今日提醒` section and alert-count summary, using everyday review wording rather than engineering internals.
- Alert Center uses `Australia/Sydney` and existing ASX market-calendar helpers to compute the closed-market report date; it does not guess from a hard-coded local `16:00`.
- Alert Center keeps data basis explicit as `close_only`, `delayed`, or `unavailable`.
- Scope boundary: no new external data source, no broker API, no realtime trading monitor, no automatic order placement, no daily workflow change, no search-provider order change, no `close_only` default change, and no mutation of `final_decision`, `position_action`, `target_weight`, `delta_amount`, or `action_counts`.
- Red test result before implementation: `python -m pytest tests/test_alert_center.py -q` failed because `src.alert_center` did not exist.
- Red UI test result before implementation: `python -m pytest tests/test_alert_center.py::test_static_workbench_has_alert_center_first_screen_region -q` failed because the static workbench had no `今日提醒` region.
- Review result: code review and architecture review found no blocking issues; low-risk contract/watch items were fixed before publication.
- Test result: `python -m pytest tests/test_alert_center.py tests/test_notification_summary_format.py -q` passed, 102 tests; Windows pytest temp cleanup may print a `PermissionError` after success with exit code 0.
- Test result: `python -m compileall -q src api` passed.
- Test result: `python -m flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics` passed with count `0`.
- Test result: `python -m py_compile main.py src/config.py src/analyzer.py src/notification.py src/storage.py src/scheduler.py src/search_service.py src/market_analyzer.py src/stock_analyzer.py data_provider/__init__.py data_provider/base.py data_provider/realtime_types.py data_provider/yfinance_fetcher.py` passed.
- Test result: `python -m pytest -m "not network"` passed, 796 tests / 5 subtests, 7 warnings; Windows pytest temp cleanup printed a `PermissionError` after success with exit code 0.
- Next step: after merge, consider using the Alert Center payload in future review-journal or intraday-review surfaces, still without broker execution or realtime trading assumptions.
