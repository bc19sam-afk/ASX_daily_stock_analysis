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

The Alert Center aggregates must-review risks from existing report and
portfolio evidence. It should use review language and should not produce trade
instructions.

## Alert Rules Roadmap

The upstream project has a richer alert-rule shape with CRUD, dry-run, trigger
history, and notification attempts. The ASX project should adopt the dry-run
contract first:

- Rules evaluate against watchlist, portfolio holdings, single symbols, report
  history, and existing evidence.
- Results include evaluated, triggered, degraded, skipped, and reason fields.
- Output remains `is_trade_instruction=false`.
- No background worker or production notification side effects by default.

## UI Roadmap

Future workbench UI evolution can stay static or move to a React shell. Either
way, UI changes should preserve:

- First-screen daily review usefulness.
- Mobile readability.
- Clear data basis labels.
- Alert Center wording as review prompts, not orders.
- Smoke tests if navigation or layout complexity increases.

## Related Pages

- [[runbook-daily-asx-maintenance]]
- [[pattern-human-review-output-contract]]
- [[decision-asx-upstream-diff-roadmap-2026-05-29]]

