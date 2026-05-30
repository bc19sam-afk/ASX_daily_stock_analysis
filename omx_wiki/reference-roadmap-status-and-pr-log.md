# Reference: Roadmap Status And PR Log

Category: reference
Tags: roadmap, status, prs, history

## Purpose

This page is a compressed index of durable roadmap state. Detailed historical
logs remain in `docs/codex_execution_log.md`; this page should keep only the
facts needed for future planning.

## Stable Current State

- P0 report safety and evidence chain completed.
- P1 completed through shadow/dry-run risk sizing, structured valuation, and
  ASX search localisation.
- P2 completed through intraday review contract, offline review surfaces, ASX
  official announcement check contract, and daily review journal.
- Later ASX roadmap work delivered AnalysisContextPack v1, minimal ASX
  workbench, ASX portfolio ledger/CSV import, and ASX-aware Alert Center.

## Blocked Or Separately Authorized Areas

- True risk-sizing enabled mode.
- Realtime quote adapter.
- Broker integration.
- Automatic trading.
- Workflow changes.
- `close_only` default changes.
- Storage or database migrations unless scoped as an explicit PR.

## Maintenance Rule

When a major PR chain changes durable roadmap state, update this page with:

- Status.
- Scope.
- Merge or baseline reference when known.
- Verification summary.
- Boundary notes.
- Next candidate step.

Do not copy full execution logs here.

