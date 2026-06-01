# Architecture: Portfolio Ledger And Review Journal

Category: architecture
Tags: portfolio, ledger, review-journal, csv, manual

## Purpose

This page distinguishes portfolio import, simulated/paper state, manual review
artifacts, and future ledger work.

## Current Boundary

Portfolio and review features are manual-review artifacts unless explicitly
scoped otherwise.

- CSV import can support ASX portfolio review and simulated/paper views.
- Review journal records user-provided notes and review outcomes.
- Paper portfolio supports simulated behavior.
- None of these should be treated as a broker connection, real account ledger,
  or proof of actual fills.

## Existing Safe Properties

- Manual execution notes must be marked user-provided.
- Review journal must not mutate morning report decisions or action fields.
- Portfolio import should preserve explicit account labels without storing raw
  sensitive account identifiers.
- HIN originals, account numbers, and real broker credentials must not be saved.

## Ledger V2 Roadmap

The upstream project has a richer event-sourced portfolio model. The ASX
version should adapt the shape rather than directly copy the business logic:

- Market field such as ASX/AU/US.
- Base currency AUD.
- Trade date and settlement date.
- Brokerage, GST, fees, tax notes.
- Dividend and franking credit fields.
- Corporate actions such as splits, DRP, return of capital, and adjustments.
- Dual-read migration path before any destructive schema change.

PR6 planning artifact: `docs/portfolio-ledger-v2-plan.md`.
The PR6 scope is plan/contract/guard only: no database migration, no broker or
execution integration, and no replacement of current portfolio overview/import,
paper portfolio, workbench, alert, or review-journal behavior.

Current completed ledger v2 groundwork now extends beyond PR6:

- PR7 added the disabled shadow migration scaffold.
- PR10 added dry-run backfill and dual-read comparison groundwork.
- PR11 exposed read-only shadow diagnostics for manual review.
- PR12 added dividend/franking and corporate-action placeholders.

These remain manual-review diagnostics. V1 portfolio reads are still
authoritative, and production migration, cutover, broker integration, worker
side effects, or notification delivery require separate explicit scope.

Phase 2 ledger work may choose a migration rehearsal or deeper shadow-read PR,
but it must stay reversible, default-off, and outside production cutover unless
the task explicitly authorizes that boundary change.

## Related Pages

- [[pattern-broker-execution-scope-gate]]
- [[reference-upstream-diff-evidence-2026-05-29]]
- [[decision-asx-upstream-diff-roadmap-2026-05-29]]
