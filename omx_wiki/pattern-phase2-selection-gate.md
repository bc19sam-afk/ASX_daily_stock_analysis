# Pattern: Phase 2 Selection Gate

Category: pattern
Tags: phase-2, selection-gate, roadmap, human-review, side-effects

## Purpose

Use this gate before starting any Phase 2 PR after PR18. It forces one clear
direction to be selected before implementation so ledger, broker, notification,
worker, migration, and live telemetry work do not drift into the same PR.

This gate is a planning and control-plane artifact. Passing it does not
authorize side effects beyond the side-effect class explicitly selected for the
next PR.

## When To Use

- Required before each Phase 2 implementation PR.
- Required when a Phase 2 PR would touch ledger v2, broker-ready contracts,
  alerts, notifications, workers, provider telemetry, Workbench productization,
  or related documentation.
- Optional for a docs-only roadmap PR that exists only to prepare or refine the
  next selection.

Do not use a completed gate as permission to start unrelated Phase 2 lanes. If
the selected work needs more than one lane, split it before implementation.

## Gate Checklist

Record these fields before implementation starts:

- Chosen lane: A Workbench productization, B ledger v2 rehearsal or deeper
  shadow-read, C alert worker or notification attempt, D broker-ready draft or
  paper boundary, or E live provider quota telemetry.
- Why now / ROI: the operator value, risk reduction, or roadmap dependency.
- Risk class: low, medium, or high.
- Side effects allowed: none, dry-run, persisted state, external call, worker,
  or broker.
- Default-off controls: feature flags, guard functions, disabled runners,
  dry-run mode, or manual switches that keep the new behavior inactive by
  default.
- Human-review boundary: what remains a review prompt or operator decision.
- Data/secrets boundary: which sensitive values are excluded from storage,
  logs, prompts, UI, wiki, and tests.
- Affected files/modules: expected docs, wiki, service, API, UI, test, or
  workflow paths.
- Required tests/smoke/checks: targeted tests plus any static, UI, or manual
  smoke checks needed to prove the selected scope.
- Wiki pages to update: decision, architecture, pattern, runbook, or status
  pages that should be refreshed.
- Explicit non-goals: adjacent lanes and side effects that remain out of scope.
- Stop rule / rollback rule: conditions that force the PR to stop, split, or
  revert.

## Lane Rules

### A. Workbench Productization

Use this lane for operator flow, navigation, wording, diagnostics grouping, or
smoke coverage. It should normally allow no side effects. Do not add workers,
external calls, provider quota probes, broker behavior, database writes, or
ledger cutover inside this lane.

PR18 used this lowest-risk lane for diagnostics productization. A future
Workbench PR should explain why another productization pass is worth doing
before ledger, broker, alert, or telemetry work.

### B. Ledger V2 Rehearsal Or Deeper Shadow-Read

Use this lane for reversible ledger v2 rehearsal, shadow-read, or diagnostics
work. V1 remains authoritative unless a later task explicitly authorizes a
production migration or cutover. Migration runners, storage writes, read-path
replacement, and cutover need separate authorization and default-off controls.

### C. Alert Worker Or Notification Attempt

Use this lane only with explicit default-off controls. Worker or notification
work must start in dry-run/manual-review mode, with no real delivery by default
and no wording that turns alert output into trade instructions.

### D. Broker-Ready Draft Or Paper Boundary

Use this lane only for draft, paper, interface, precheck, or sanitized
read-shape work. Any broker, order, real-account, or execution-adjacent scope
must cite and satisfy [[pattern-broker-execution-scope-gate]]. No real broker
login, real account mutation, or real order submission is allowed without a
separately authorized broker/execution task.

### E. Live Provider Quota Telemetry

Use this lane only when the task explicitly authorizes external provider calls.
Keep secret values, raw request payloads, requester fields, provider keys,
queries, snippets, URLs, and raw token-like values out of logs, prompts, UI,
wiki, and fixtures. Prefer quota-safe probes and degraded-state reporting.

## PR20 Candidate Order

Recommended ordering for the next selection, without choosing for the user:

1. Ledger deeper shadow-read or rehearsal gate.
2. Broker-ready draft or paper gate.
3. Alert notification dry-run gate.
4. Live provider telemetry gate.

Workbench productization remains available, but PR18 already used the
lowest-risk Workbench lane. Pick it again only if the user wants another
operator-flow pass before the other Phase 2 options.

## Stop And Rollback Rules

Stop and split the PR if:

- More than one Phase 2 lane becomes necessary.
- The diff enters a higher side-effect class than the gate selected.
- Broker, worker, notification, migration, cutover, or external-call behavior
  appears without explicit authorization.
- Sensitive account, credential, order, fill, or provider payload material
  appears in docs, code, logs, fixtures, prompts, UI, or wiki.
- A docs/wiki selection-gate PR touches business implementation paths.

Rollback should prefer the smallest reversible action: revert the branch for a
docs/wiki-only gate; disable the feature flag or guard for future code PRs;
preserve v1 portfolio authority for ledger work; and document the stop reason
in the roadmap status page if the scope decision remains useful.

## Related Pages

- [[decision-asx-roadmap-control-plane]]
- [[reference-roadmap-status-and-pr-log]]
- [[project-boundary-and-safety-contract]]
- [[pattern-human-review-output-contract]]
- [[pattern-broker-execution-scope-gate]]
- [[architecture-workbench-alert-center]]
- [[architecture-portfolio-ledger-review-journal]]
