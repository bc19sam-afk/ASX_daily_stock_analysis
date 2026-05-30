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
  minimal workbench, ASX portfolio import, paper/simulated portfolio surfaces,
  manual review journal, and Alert Center.
- Broker integration, automatic trading, realtime quote adapters, workflow
  changes, `close_only` default changes, and database migrations require
  separate authorization.

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
If a PR touches broker/execution behavior, it must cite
[[pattern-broker-execution-scope-gate]] and meet the gate before implementation.

## Source Threads

- `codex://threads/019e73a9-65d6-79f0-a84f-153d49079eed`:
  upstream diff, ASX roadmap, and original wiki control-plane proposal.

