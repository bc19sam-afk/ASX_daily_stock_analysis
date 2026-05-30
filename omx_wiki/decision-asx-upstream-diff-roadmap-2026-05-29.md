# Decision: ASX Upstream Diff Roadmap 2026-05-29

Category: decision
Tags: upstream-diff, roadmap, asx, workbench, portfolio, alerts

## Context

The ASX project was compared against the original upstream project
`ZhuLinsen/daily_stock_analysis` in a read-only planning thread:

- Source thread: `codex://threads/019e73a9-65d6-79f0-a84f-153d49079eed`
- Current project baseline in that thread: local ASX repo main at
  `48e82fa95b0676715f103769827e536fc1689ad5`.
- Upstream baseline in that thread: upstream main at
  `c6cad832322f30144cbdecfe1307367108928fab`.

This page records the compressed decision. Detailed file evidence belongs in
[[reference-upstream-diff-evidence-2026-05-29]].

## Decision

Absorb upstream engineering shapes, not upstream A-share business assumptions.

The current ASX fork already has key ASX-first surfaces. Do not restart from
the premise that the project lacks workbench, analysis context, ASX official
announcement evidence, portfolio import, simulated/paper behavior, or alerts.

## Already Absorbed

- ASX workbench summary and static UI.
- AnalysisContextPack v1 with ASX/AUD/Australia/Sydney semantics.
- ASX official announcement listing metadata as read-only evidence.
- Gemini 3.5 Flash, Tavily/Gemini Grounding/SerpAPI search chain, and
  news_intel cache behavior.
- ASX CSV portfolio ledger import and paper/simulated portfolio surfaces.
- Alert Center for report and portfolio-review risks.

## Top 10 ROI Items To Absorb Next

1. Low-sensitivity AnalysisContextPack prompt summary.
2. ASX CSV parser registry and dedup counters.
3. Read-only portfolio event facade.
4. ASX alert rule dry-run API.
5. Workbench UI evolution with smoke tests.
6. ASX ledger v2 event model.
7. Dividend, franking, and corporate-action model.
8. Portfolio/watchlist review alerts.
9. Provider quota/status dashboard.
10. Broker-ready draft/paper boundary.

## Phased Route

Week 1:
- AnalysisContextPack low-sensitivity summary.
- Provider budget/status dashboard.

Week 2:
- ASX CSV parser registry and dedup.
- Portfolio event read facade.

Week 3:
- ASX alert rule dry-run API.
- Workbench alert rule read UI.

Week 4:
- Workbench componentization or React shell.
- UI smoke tests and optional web CI gate.

Week 5:
- Ledger v2 dual-read design.
- Dividend/franking/corporate-action modeling.

Week 6:
- Broker-ready draft/paper boundary.
- Minimal order-draft contract only, with no real broker connection.

## Non-Goals

- No real broker order submission.
- No automatic stop-loss or take-profit execution.
- No paid realtime data baseline.
- No direct transplant of China broker parsers or A-share data sources.
- No default background alert worker with notification side effects.
- No credentials in repo, DB, logs, prompts, reports, wiki, or skill files.

