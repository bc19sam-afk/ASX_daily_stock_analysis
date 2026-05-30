# Pattern: Broker Execution Scope Gate

Category: convention
Tags: broker, execution, dry-run, paper, audit, credentials

## Purpose

This page defines the gate for any future broker, real-account, order draft, or
execution-adjacent work.

## Before Entering Scope

Confirm the task explicitly says it is entering broker/execution scope. If not,
keep work limited to reports, evidence, manual review artifacts, dry-run
contracts, simulated/paper views, documentation, or tests.

## Required Design Properties

Any broker/execution scope must include:

- Default disabled state.
- Dry-run or paper mode before real mode.
- Human confirmation for real submission.
- Audit trail for draft, preview, confirmation, submission, and result.
- Idempotency keys or equivalent duplicate protection.
- Size, frequency, stale-data, validation, and account-state limits.
- Circuit breakers.
- Credential isolation.
- Clear failure recovery.
- Clear user-facing disclaimer.

## Allowed Early Work

- Broker adapter interface research.
- Test doubles.
- Read-only holdings or account shape research with sanitized fixtures.
- Order precheck contracts.
- Draft orders.
- Paper order simulation.

## Not Allowed Without Separate Authorization

- Real broker login.
- Real account mutation.
- Real order submission.
- Automatic stop-loss or take-profit execution.
- Storing credentials or account identifiers.
- Treating review journal or CSV import as proof of real fills.

## Related Pages

- [[project-boundary-and-safety-contract]]
- [[architecture-portfolio-ledger-review-journal]]

