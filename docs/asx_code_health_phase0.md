# ASX Code Health Phase 0 Contract

This note locks the local behavior and dependency map for the approved
Phase 0 + Phase 1 cleanup. It is intentionally narrow: it supports report
assembly refactoring only and does not authorize storage, schema, session, or
business-rule changes.

## Baseline Gate

Full backend gate command for this machine:

```bash
PATH="/Users/mac/workspace/ASX_daily_stock_analysis/.venv/bin:/Users/mac/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:/opt/homebrew/bin:$PATH" ./scripts/ci_gate.sh
```

Latest post-cleanup gate evidence: `884 passed, 5 warnings, 5 subtests passed`.

Pre-change report contract check run before Phase 1 edits:

```bash
PATH="/Users/mac/workspace/ASX_daily_stock_analysis/.venv/bin:/opt/homebrew/bin:$PATH" python -m pytest tests/test_morning_review_card.py tests/test_daily_decision_dashboard_archive.py tests/test_report_body_deduplication.py tests/test_report_readability_guardrail.py -q
```

Result: `48 passed, 1 warning`.

## Complexity Baseline

The pre-refactor `HEAD` baseline for `NotificationService.generate_dashboard_report`
was:

- Lines: `531` (`src/notification.py:2370-2900` before this change).
- Branch nodes counted with Python `ast`: `82`.

The Phase 1 extraction target is not to change report semantics. It is to turn
that single report assembly body into smaller private helpers while preserving
the `NotificationService.generate_dashboard_report(...)` facade.

Post-extraction shape after the final Phase 1 context split, rebased over the
daily report malformed-data and delivery-health guards:

- `generate_dashboard_report`: `99` lines, `1` branch node.
- The old single `_DashboardReportContext` was split into five narrow internal
  value objects: report timing, portfolio snapshot, summary groups, action
  groups, and risk groups.
- Largest preparation helper after the split:
  `_load_dashboard_portfolio_snapshot`, `36` lines, `6` branch nodes.
- Largest section helper in the extracted dashboard report assembly path:
  `_build_dashboard_current_holdings_lines`, `106` lines, `20` branch nodes.
- Largest branch count in the extracted helper path remains
  `_build_dashboard_detail_core_lines`, `85` lines, `19` branch nodes.

## Characterization Coverage

The Phase 1 notification/report cleanup is guarded by existing tests covering:

- Morning Review Card presence, ordering, reliability rows, and email body
  projection: `tests/test_morning_review_card.py`.
- Dashboard archive shape, daily decision summary schema, report dates, and
  HTML archive rendering: `tests/test_daily_decision_dashboard_archive.py`.
- Mainline/report appendix deduplication and concise email projection:
  `tests/test_report_body_deduplication.py`.
- Report readability, dashboard landing shape, user-facing language cleanup,
  paper-ledger display, and email/body archive separation:
  `tests/test_report_readability_guardrail.py`.
- Markdown-to-image channel fallback and email subject/date contracts:
  `tests/test_notification_summary_format.py`.

## `get_db()` Consumer Map

This cleanup must not change `src.storage.get_db()` or storage/session behavior.
Current direct consumers are:

- `src/core/pipeline.py`: constructs the pipeline-level database manager for
  analysis persistence and orchestration. Category: write/read orchestration.
- `src/services/task_service.py`: reads analysis history. Category: read/query.
- `src/notification.py`: reads portfolio overview for report-time display and
  daily decision summary context. Category: read-only report display.
- `src/notification.py`: reads paper portfolio overview for the dashboard
  read-only ledger section. Category: read-only report display.
- `src/storage.py`: module self-test path only. Category: manual diagnostic.

The only in-scope `get_db()` work for Phase 1 is preserving the existing
read-only notification calls while moving report assembly code around.

## Stop Rules

- Stop if any edit requires changing `src/storage.py`, `api/deps.py`, schema
  setup, table/column definitions, or session lifecycle.
- Stop if a helper extraction changes public `NotificationService` method
  signatures or generated report text ordering outside intentional tests.
- Stop if circular imports appear between notification modules.
- Stop if report assembly starts requiring a new dependency.
- Stop if targeted report tests pass only by weakening expected output.

## Phase 1 Scope

Allowed:

- Extract private helpers from `NotificationService.generate_dashboard_report`.
- Add pure report assembly helpers that keep the `NotificationService` facade
  unchanged.
- Add characterization tests only when an existing contract is missing.

Not allowed in this phase:

- Analyzer, pipeline, or storage migration.
- Broker/execution behavior.
- New dependencies.
- Business-rule changes to action selection, validation blocking, portfolio
  weighting, or report disclaimers.
