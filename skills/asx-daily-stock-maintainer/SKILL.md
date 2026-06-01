---
name: asx-daily-stock-maintainer
description: Maintain ASX_daily_stock_analysis in planning, wiki, roadmap, daily-review, and human-in-the-loop control workflows. Use when a task mentions ASX_daily_stock_analysis, ASX wiki, omx_wiki, upstream diff, daily maintenance, 总控, 只做规划, 只做记录, 不写文件, human-in-the-loop, Alert Center, AnalysisContextPack, portfolio ledger, or broker-ready boundaries.
argument-hint: "[focus]"
---

# ASX Daily Stock Maintainer

## Purpose

Keep `ASX_daily_stock_analysis` aligned with its wiki-backed control plane:
ASX-first evidence and reporting, human-in-the-loop review, careful roadmap
recording, and explicit broker/execution gating.

## First Read

For planning, wiki, roadmap, maintenance, or boundary work, read these before
making recommendations:

1. `AGENTS.md`
2. `omx_wiki/index.md`
3. `omx_wiki/project-boundary-and-safety-contract.md`
4. `omx_wiki/decision-asx-roadmap-control-plane.md`
5. `omx_wiki/runbook-daily-asx-maintenance.md`
6. `omx_wiki/reference-roadmap-status-and-pr-log.md`

For upstream-diff or feature-prioritization work, also read:

1. `omx_wiki/decision-asx-upstream-diff-roadmap-2026-05-29.md`
2. `omx_wiki/reference-upstream-diff-evidence-2026-05-29.md`

For broker, order draft, paper execution, or real-account-adjacent work, also
read:

1. `omx_wiki/pattern-broker-execution-scope-gate.md`
2. `omx_wiki/architecture-portfolio-ledger-review-journal.md`

For Phase 2 work after PR18, also read:

1. `omx_wiki/pattern-phase2-selection-gate.md`

## Operating Procedure

1. Classify the current task mode:
   - planning/control only
   - documentation/wiki/skill update
   - ordinary code implementation
   - broker/execution scope
2. Preserve explicit user boundaries literally. If the user says not to write
   files or not to implement, stop at drafts and file lists.
3. For wiki work, update durable decisions, references, and runbooks instead
   of copying raw chat logs.
4. Before any Phase 2 implementation PR starts, fill the Phase 2 selection gate
   and keep the chosen lane, side-effect class, tests, wiki updates, non-goals,
   and stop/rollback rule explicit.
5. For code work, keep changes small, tested, and scoped to the authorized
   request.
6. For daily maintenance, follow `runbook-daily-asx-maintenance`.
7. For upstream diff work, re-check current local and upstream heads before
   relying on old baselines.
8. For broker/execution-adjacent work, require explicit scope and enforce the
   broker execution gate.

## Prohibited

- Do not connect a real broker unless the user explicitly authorizes a
  broker/execution scope.
- Do not submit real orders.
- Do not store API keys, broker credentials, HIN originals, account numbers,
  real order details, or fill confirmations.
- Do not treat review journal entries, CSV imports, or paper portfolio entries
  as proof of real fills.
- Do not make AI override deterministic action fields or validation gates.
- Do not let `BLOCK` items become executable.
- Do not duplicate large wiki content inside this skill. Keep the skill
  procedural and point to wiki pages for stable knowledge.

## Output Format

For planning or maintenance tasks, respond with:

- Current mode.
- Files or wiki pages read.
- Evidence-backed findings.
- Decisions or draft changes.
- Boundaries and non-goals.
- Next file list or verification steps.

For implementation tasks, respond with:

- Changed files.
- Behavior changed.
- Tests or checks run.
- Risks or gaps.

If verification cannot run, say why and use the next-best check.

## Maintenance Rule

When a durable project decision changes, update the wiki first. When the
repeatable operating process changes, update this skill. When the user's
personal preference or cross-thread boundary changes, use agent memory only
when explicitly asked. When a periodic reminder is needed, use automation.
