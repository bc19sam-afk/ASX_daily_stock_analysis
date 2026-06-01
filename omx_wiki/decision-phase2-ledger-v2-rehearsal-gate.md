# Decision: Phase 2 Ledger V2 Rehearsal Gate

Category: decision
Tags: phase-2, ledger-v2, rehearsal, shadow-read, control-plane

## Decision

PR20 selected Phase 2 lane B: Ledger v2 deeper shadow-read / rehearsal.

PR21 completed the selected implementation as GitHub PR #223, "Add ledger v2
rehearsal report", merged at `059abef45231726526b379dbc7dd152a1f164cf1`.
It added a read-only rehearsal report over the existing ledger v2 dry-run,
shadow diagnostics, and income/corporate-action placeholder surfaces. It does
not write ledger v2 storage, create production tables, cut over reads, connect
a broker, send notifications, start a worker, or make live provider API calls.

## Selection Gate

- Chosen lane: Ledger v2 deeper shadow-read / rehearsal.
- Why now / ROI: PR6, PR7, PR10, PR11, and PR12 already provide the ledger v2
  plan, guard, disabled scaffold, dry-run comparison, shadow diagnostics, and
  placeholder groundwork. The lowest-risk next step is to test whether those
  diagnostics can be rehearsed and explained to an operator before any storage,
  migration, or cutover decision.
- Risk class: medium. The work remains read-only, but it summarizes ledger
  interpretation and could mislead future cutover decisions if mismatch,
  unsupported, or partial placeholder states are blurred.
- Side effects allowed for PR21: none or explicit dry-run only. No production
  write, ledger v2 storage write, startup table creation, background worker,
  notification, broker call, or live provider call is allowed.
- Default-off controls: v1 portfolio reads remain authoritative; the ledger v2
  migration flag remains off; any rehearsal runner must be explicit dry-run and
  must not register v2 tables on active storage metadata.
- Human-review boundary: mismatch, missing, unsupported, warning, and partial
  placeholder outputs are prompts for manual review only. They are not trade
  instructions, tax advice, broker statement reconciliation, or authority to
  modify portfolio state.
- Data/secrets boundary: no API keys, broker credentials, HIN originals,
  account numbers, raw account identifiers, real order details, real fill
  confirmations, provider request payloads, raw keys/tokens, queries, URLs, or
  requester fields may be stored in docs, wiki, tests, logs, prompts, UI, or
  fixtures.
- Affected modules for PR21 candidates: the ledger dry-run service, portfolio
  events API, Workbench summary, targeted tests, docs, and wiki. PR20 itself is
  docs/wiki/control-plane only.
- Required tests/smoke/checks for PR21: targeted ledger dry-run diagnostics
  tests, portfolio-events API tests, Workbench summary tests if the Workbench
  link or summary changes, `git diff --check`, sensitive-term search, and
  targeted compile/static checks for any touched Python modules. Full
  `ci_gate.sh` is required if PR21 changes business code or API behavior.
- Wiki pages to update for PR21: this decision, the roadmap status log, the
  ledger v2 plan, and the portfolio-ledger/review-journal architecture page if
  rehearsal semantics change.
- Explicit non-goals: production migration, table creation during startup,
  read-path cutover, v2 authority replacement, broker or execution behavior,
  real-account access, tax advice, broker-statement import, worker or
  notification delivery, live provider telemetry, and unrelated Workbench,
  alert, or broker lanes.
- Stop rule / rollback rule: stop and split the PR if any side-effect class
  rises above none/dry-run, if implementation needs storage or migration work,
  if v2 output starts replacing v1 authority, if sensitive account/order/fill
  material appears, or if a second Phase 2 lane becomes necessary. Rollback is
  to remove the rehearsal report/export and keep existing PR10-PR12 dry-run and
  diagnostics endpoints unchanged.

## PR21 Boundary

Suggested name: Ledger v2 rehearsal report over shadow diagnostics.

Suggested files:

- `src/services/asx_ledger_v2_dry_run.py` for a read-only report builder over
  existing dry-run and diagnostics structures.
- `api/v1/endpoints/portfolio_events.py` if an explicit read-only report or
  export endpoint is needed.
- `api/v1/endpoints/workbench.py` if only compact Workbench metadata or a link
  is added.
- `tests/test_asx_ledger_v2_dry_run.py`,
  `tests/test_portfolio_events_api.py`, and `tests/test_workbench_api.py` for
  targeted coverage.
- `docs/portfolio-ledger-v2-plan.md` and relevant `omx_wiki/` pages for the
  durable boundary update.

Acceptance criteria:

- The report is generated from existing v1 state plus ledger v2 dry-run /
  diagnostics data without writing ledger v2 storage.
- The report groups mismatched, missing, unsupported, warning, and partial
  placeholder states with operator-readable explanations.
- Every output keeps v1 authoritative and marks rehearsal data as dry-run /
  manual-review only.
- Unsupported dividend/franking/corporate-action placeholders remain explicit
  and are not converted into supported cash, lot, tax, or cost-base events.
- No startup table creation, migration flag enablement, storage mutation,
  broker/execution behavior, notification delivery, worker, live provider call,
  or sensitive account/order/fill material appears.
- Targeted tests prove the read-only report contract, redaction boundary, v1
  authority wording, and Workbench/API links if touched.

Status:

- PR21 is implemented in GitHub PR #223 and merged on `main`.
- The report endpoint is
  `/api/v1/portfolio-events/ledger-v2/rehearsal-report`.
- Local verification included the targeted ledger dry-run, portfolio-events,
  Workbench, ledger v2 contract, and migration scaffold tests plus
  `./scripts/ci_gate.sh` with the repo virtualenv and bundled Node on `PATH`.
- GitHub checks passed for backend gate, Docker build, change detection,
  security, static checks, AI review, and review reporting; desktop gate was
  skipped by change detection.
- Thread-aware review inspection found no review threads and only the generated
  review-report comment.
- The next step is manual review of PR21 rehearsal output before selecting any
  separate PR22 lane; PR21 is not migration evidence or cutover readiness proof.

Historical compact PR21 goal direction:

> Build PR21 "Ledger v2 rehearsal report over shadow diagnostics" as a
> read-only/dry-run report or comparison export over existing PR10-PR12 ledger
> dry-run, shadow diagnostics, and placeholder data. Do not write ledger v2
> storage, create tables, enable migration, cut over reads, connect broker,
> send notifications, start workers, or call live providers. Keep v1
> authoritative; group mismatch/missing/unsupported/warning/partial states for
> manual review; exclude secrets, HIN originals, account numbers, real
> order/fill details, and provider payloads. Update targeted tests and docs.

## Evidence

- [[pattern-phase2-selection-gate]] requires one Phase 2 lane, side-effect
  class, non-goals, and stop/rollback rule before implementation starts.
- [[reference-roadmap-status-and-pr-log]] records PR6/PR7/PR10/PR11/PR12 as
  ledger v2 pre-cutover groundwork and PR19 as the docs/wiki selection gate.
- [[architecture-portfolio-ledger-review-journal]] keeps ledger v2 diagnostics
  as manual-review artifacts while v1 remains authoritative.
- `docs/portfolio-ledger-v2-plan.md` records that PR6-PR12 do not prove ledger
  v2 storage, production migration, or cutover readiness.

## Related Pages

- [[pattern-phase2-selection-gate]]
- [[decision-asx-roadmap-control-plane]]
- [[reference-roadmap-status-and-pr-log]]
- [[architecture-portfolio-ledger-review-journal]]
- [[project-boundary-and-safety-contract]]
