# ASX Daily Stock Analysis Wiki

Category: reference
Tags: index, asx, roadmap, human-in-the-loop

This wiki is the durable control plane for `ASX_daily_stock_analysis`.
It stores stable project knowledge, decisions, runbooks, and design boundaries.
It is not a place for secrets, raw account identifiers, or real order details.

## Start Here

- [[project-boundary-and-safety-contract]]
- [[decision-asx-roadmap-control-plane]]
- [[runbook-daily-asx-maintenance]]
- [[decision-asx-upstream-diff-roadmap-2026-05-29]]

## Architecture

- [[architecture-report-evidence-pipeline]]
- [[architecture-workbench-alert-center]]
- [[architecture-portfolio-ledger-review-journal]]

## Patterns

- [[pattern-human-review-output-contract]]
- [[pattern-broker-execution-scope-gate]]

## References

- [[reference-data-sources-time-basis]]
- [[reference-roadmap-status-and-pr-log]]
- [[reference-upstream-diff-evidence-2026-05-29]]
- [[reference-local-dev-tooling-codegraph]]

## Operating Boundary

The project is an ASX/AU/US stock analysis and reporting assistant.
The default workflow is human-in-the-loop: the system prepares evidence,
risks, plans, alerts, simulated/paper views, and manual review artifacts;
the user remains responsible for decisions and any real-world action.

Trading-related research is not banned. Real account or broker execution is
only allowed inside an explicitly scoped broker/execution task, and must remain
off by default with dry-run or paper behavior, human confirmation, audit logs,
idempotency, limits, circuit breakers, credential isolation, and failure
recovery.

## Storage Split

- Wiki: stable project knowledge, decisions, architecture notes, runbooks,
  external constraints, roadmap summaries, and PR status summaries.
- Skill: repeatable operating procedure, first-read pages, stop rules, and
  output shape.
- Agent memory: stable user preferences and cross-thread boundaries.
- Automation: reminders and periodic checks only.
- Never store: API keys, broker credentials, HIN originals, account numbers,
  real order details, fill confirmations, or any secret that can access or
  operate an account.
