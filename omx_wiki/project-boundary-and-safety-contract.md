# Project Boundary And Safety Contract

Category: convention
Tags: asx, human-review, broker-boundary, safety

## Purpose

This page records the long-term product boundary for
`ASX_daily_stock_analysis`. It should be read before roadmap, broker,
portfolio, alert, or reporting work.

## Default Product Shape

- ASX/AU/US stock analysis and reporting assistant.
- Default workflow: human-in-the-loop.
- The system prepares evidence, risk prompts, position suggestions,
  simulated/paper views, reports, alerts, and review artifacts.
- The user decides and performs any real-world action.

## What Is Allowed In Normal Report/Data/UI Work

- Daily report quality, evidence matrix, report reliability, and time-basis
  improvements.
- ASX official announcements as read-only evidence.
- AnalysisContextPack and prompt context hardening.
- Workbench, alert center, portfolio import, simulated/paper portfolio, and
  manual review journal improvements.
- ASX-aware CSV parsing and manual ledger artifacts.
- Documentation and tests that keep human review clear.

## Broker / Execution Scope Gate

Broker, real-account, or automatic execution work is allowed only when the task
explicitly enters broker/execution scope. That work must not be mixed into
ordinary report, data-source, UI, documentation, or test changes.

Required defaults for broker/execution scope:

- Real execution off by default.
- Dry-run or paper mode available before any real mode.
- Explicit human confirmation for any real action.
- Audit logs for intent, preview, confirmation, submission, and result.
- Idempotency protection against repeated order creation.
- Limits and circuit breakers for size, frequency, stale data, validation
  status, and unexpected account state.
- Credential isolation away from repo, logs, prompts, reports, and wiki.
- Failure recovery and clear disabled-state behavior.

## What Must Never Be Saved

- API keys.
- Broker credentials.
- HIN originals.
- Account numbers.
- Real order details.
- Real fill confirmations.
- Raw account statements unless explicitly sanitized for an approved import
  task.
- Any secret or identifier that can access, identify, or operate a real account.

## Wording Guidance

Do not add repeated "no trading" disclaimers to every normal report, data,
UI, documentation, or test change. Mention the execution boundary only when
the work touches brokers, real accounts, orders, automatic stop-loss/take-profit,
or other execution-like behavior.

