# Architecture: Workbench And Alert Center

Category: architecture
Tags: workbench, alerts, review, ui, dry-run

## Purpose

This page records the boundary between the ASX workbench, Alert Center, and
future alert-rule features.

## Current Shape

The workbench is the local review surface for:

- Latest report status.
- Report history.
- Portfolio and paper/simulated portfolio summaries.
- Risk and backtest visibility.
- Configuration/status links.
- Alert Center review items.
- Alert-rule dry-run and preset review.
- Diagnostics hub links for provider/cache status, alert-rule batch dry-run,
  ledger v2 dry-run, and ledger v2 diagnostics.
- Provider-cache usage telemetry v0 from local cache observations only.

The Alert Center aggregates must-review risks from existing report and
portfolio evidence. It should use review language and should not produce trade
instructions.

## Alert Rules Roadmap

The upstream project has a richer alert-rule shape with CRUD, dry-run, trigger
history, and notification attempts. The ASX project has adopted the dry-run
contract first:

- Rules evaluate against watchlist, portfolio holdings, single symbols, report
  history, and existing evidence.
- Results include evaluated, triggered, degraded, skipped, and reason fields.
- Output remains `is_trade_instruction=false`.
- No background worker or production notification side effects by default.

Future worker or notification work requires a separate default-off,
dry-run/manual-review scope. It should not be bundled with Workbench
productization or diagnostics-only PRs.

## UI Roadmap

Future workbench UI evolution can stay static or move to a React shell. Either
way, UI changes should preserve:

- First-screen daily review usefulness.
- Mobile readability.
- Clear data basis labels.
- Alert Center wording as review prompts, not orders.
- Smoke tests if navigation or layout complexity increases.

Phase 2 Workbench productization can improve operator flow, navigation,
diagnostics grouping, or smoke coverage. It should remain side-effect-free
unless a later PR explicitly enters worker, notification, broker, migration, or
external-provider-call scope.

## Related Pages

- [[runbook-daily-asx-maintenance]]
- [[pattern-human-review-output-contract]]
- [[decision-asx-upstream-diff-roadmap-2026-05-29]]
