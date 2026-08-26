# Runbook: Daily ASX Maintenance

Category: pattern
Tags: runbook, daily-maintenance, asx, review, alert-center

## Purpose

Keep the ASX analysis assistant reliable without accidentally expanding the
task into broker/execution behavior.

## First Read

1. [[project-boundary-and-safety-contract]]
2. [[decision-asx-roadmap-control-plane]]
3. [[reference-data-sources-time-basis]]
4. [[pattern-human-review-output-contract]]
5. [[reference-roadmap-status-and-pr-log]]

## Daily Check

1. Confirm the current task mode: planning/control, documentation, code change,
   or explicitly authorized broker/execution scope.
2. Check the latest daily report or `daily_decision_summary` date, market date,
   and time basis.
3. Confirm report output distinguishes `close_only`, delayed, stale, missing,
   and unavailable data.
4. Check evidence matrix and report reliability for missing/stale/blocking
   evidence.
5. Check Alert Center for validation blocks, ASX announcement review risks,
   portfolio import warnings, and must-review items.
6. Review portfolio import or review journal artifacts only as manual review
   records. Do not infer real fills or account state.
7. Check provider status and search/cache behavior when report quality depends
   on external calls.
8. Record only stable outcomes in wiki: decisions, changed boundaries, durable
   runbook updates, and new reference facts.

## GitHub Actions Scheduled Workflow Continuity

GitHub can automatically disable `schedule` triggers after 60 days without
repository activity. This is separate from the workflow's enabled/disabled
state and does not mean GitHub Actions itself is being retired.

1. Check the Actions page for `每日股票分析` and `Network Smoke` when GitHub
   sends a "will be disabled soon" notice.
2. Use the page's `Continue running workflow` or `Enable workflow` control when
   it is offered; the CLI/API `enable` operation only re-enables a workflow
   that is disabled.
3. Keep `main` active with a meaningful code, documentation, or maintenance
   change before the 60-day threshold. Do not rely on manual `workflow_dispatch`
   runs or empty commits as the only activity signal.
4. Preserve the existing Australia/Sydney weekday schedule and the
   `stock-db-*` cache lineage; this continuity procedure must not alter
   portfolio or broker behavior.

## Output Shape

Use this shape for daily maintenance summaries:

- Current mode.
- Report/date/time-basis status.
- Evidence and reliability status.
- Alert Center status.
- Portfolio/review artifact status.
- Human review items.
- Blockers or deferred items.
- Explicit non-goals for this pass.

## Stop Conditions

Stop and escalate before proceeding if the task needs:

- Broker credentials.
- HIN originals or account numbers.
- Real account reads or writes.
- Real order submission.
- Automatic stop-loss/take-profit execution.
- Production notification side effects.
- A change to `close_only`, workflow, storage schema, or database migrations
  outside an explicitly authorized scope.
