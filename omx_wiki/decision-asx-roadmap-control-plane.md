# Decision: ASX Roadmap Control Plane

Category: decision
Tags: roadmap, control-plane, asx, omx, human-in-the-loop

## Decision

Use `omx_wiki/` as the durable project knowledge layer for the ASX project.
Use `skills/asx-daily-stock-maintainer/SKILL.md` as the repeatable operating
procedure for ASX maintenance and planning tasks. Keep agent memory and
automation separate from project documentation.

## Why

The ASX project has accumulated several important boundaries and roadmap
decisions across conversations, PR logs, and docs. Keeping them only in chat
makes future maintenance fragile. Keeping everything in one giant document
makes it noisy. The wiki should preserve the compressed decisions and stable
evidence; the skill should tell future agents what to read and where to stop.

## Current Baseline

- Product default: ASX/AU/US analysis assistant, human-in-the-loop.
- Current completed surfaces include report safety contracts, evidence matrix,
  report reliability, AnalysisContextPack, ASX official announcement evidence,
  CSV import/parser dedup, read-only portfolio events, alert-rule dry-runs and
  presets, the Workbench diagnostics hub, ASX portfolio import,
  Workbench diagnostics productization, paper/simulated portfolio surfaces,
  manual review journal, and Alert Center.
- Ledger v2 work is still pre-cutover: plan/contract/guard, disabled scaffold,
  dry-run backfill comparison, shadow diagnostics, and dividend/franking plus
  corporate-action placeholders are available for manual review only.
- Provider/cache visibility is local-status only: status dashboard and
  provider-cache usage telemetry v0 are present without live quota probes or
  external provider calls.
- Broker integration, automatic trading, realtime quote adapters, workflow
  changes, `close_only` default changes, and database migrations require
  separate authorization.

## Phase 1 Completed / Phase 2 Options

The upstream catch-up and infrastructure phase is now substantially complete
through PR18 and status PR #220, with #210 and #211 closing the final
alert-center audit/status gap. Treat PR0-PR18 as a completed foundation, not as
permission to keep extending the same chain automatically.

Completed capability groups:

- AnalysisContextPack and low-sensitive prompt context.
- ASX CSV import, parser registry, and dedup counters.
- Read-only portfolio events and manual portfolio review surfaces.
- Alert-rule dry-run API, presets, batch diagnostics, and manual-review UI.
- Workbench evolution through diagnostics hub, smoke coverage, provider/cache
  status, provider-cache telemetry v0, and PR18 diagnostics productization.
- Ledger v2 plan, guarded scaffold, dry-run backfill comparison, shadow
  diagnostics, and dividend/franking/corporate-action placeholders.

Phase 2 should be selected by direction, one small PR at a time. Before any
Phase 2 implementation PR starts, fill [[pattern-phase2-selection-gate]] so the
chosen lane, side-effect class, review boundary, tests, wiki updates, non-goals,
and stop/rollback rules are explicit.

Current options:

A. Workbench productization: improve navigation, operator copy, or diagnostics
surfacing without new side effects.
B. Ledger v2 migration rehearsal or deeper shadow-read: keep v1 authoritative
and stay outside production cutover.
C. Alert worker or notification attempt: default-off, dry-run/manual-review
only, and separately authorized before any worker or delivery side effect.
D. Broker-ready draft/paper boundary: draft or paper contracts only, with no
real broker connection.
E. Live provider quota telemetry: only with explicit external-call scope and no
secret exposure.

PR18 used the lowest-risk Workbench productization lane. Do not start PR20
implicitly. PR20 must be selected through the Phase 2 selection gate, and it
must not combine broker/execution, worker/notification, migration/cutover, or
live provider-call work into the same PR.

## Ledger V2 Freeze Posture

Ledger v2 is retained as a read-only manual-review diagnostic surface. Freeze
further Ledger v2 expansion for now: do not add new implementation work, do not
start cutover prep, and do not treat rehearsal outputs as migration evidence.

Existing dry-run, diagnostics, rehearsal-report, and default-off scaffold
surfaces remain available for inspection. A future reconsideration requires a
fresh Phase 2 selection gate plus separate explicit authorization; a checklist
alone does not authorize implementation, migration, or cutover prep.

Phase 2 non-goals without separate authorization:

- Real broker order submission or automatic trading.
- Default alert worker or production notification delivery.
- Production ledger v2 migration or cutover.
- Realtime paid-data baseline.
- Secrets, HIN originals, account identifiers, real order details, or fill
  persistence.

## Control Plane Rules

1. Start planning work from this wiki and `AGENTS.md`.
2. Keep roadmap decisions as decision pages, not raw chat dumps.
3. Keep daily or recurring procedures as runbooks.
4. Keep code-level designs as architecture or pattern pages.
5. Keep external/source-backed facts as reference pages.
6. Do not use the wiki for secrets, credentials, or real account details.
7. Do not treat wiki creation as implementation authorization.

## Roadmap Use

Future implementation work should split from wiki decisions into small PRs.
Each PR should have a narrow scope, targeted tests, and explicit non-goals.
Each Phase 2 PR should cite [[pattern-phase2-selection-gate]] before
implementation starts.
If a PR touches broker/execution behavior, it must cite
[[pattern-broker-execution-scope-gate]] and meet the gate before implementation.

## Source Threads

- `codex://threads/019e73a9-65d6-79f0-a84f-153d49079eed`:
  upstream diff, ASX roadmap, and original wiki control-plane proposal.
