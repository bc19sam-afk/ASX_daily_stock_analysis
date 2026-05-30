# Architecture: Report Evidence Pipeline

Category: architecture
Tags: report, evidence, reliability, analysis-context, close-only

## Purpose

This page maps the report evidence path and the boundaries that keep the
daily ASX report auditable.

## Core Concepts

- `daily_decision_summary`: compact daily action and review summary.
- Evidence matrix: source, timestamp, status, and severity across market data,
  technicals, valuation, news, announcements, backtest, portfolio, and
  validation.
- Report reliability: report-level trust indicator separate from stock score.
- Conditional plan points: buy/sell/stop/target references must include source,
  trigger condition, invalidation, price basis, and manual review requirement.
- AnalysisContextPack: structured LLM input context that should stay aligned
  with ASX/AUD/Australia/Sydney semantics.

## Key Boundaries

- AI can explain deterministic outputs, summarize evidence, and list risks.
- AI must not override `final_decision`, `position_action`, validation gates, or
  deterministic action counts.
- `BLOCK` must remain a hard block and must not leak pseudo-execution fields.
- Missing, stale, delayed, and unavailable data must remain visible.
- `close_only` is the default pre-open report basis unless separately changed.

## Roadmap Notes

The next useful improvement from the upstream diff is a low-sensitivity
AnalysisContextPack prompt renderer. The renderer should pass only safe
summary fields such as status, source, warning, missing reason, and time basis.
It should not pass raw sensitive values, secrets, tokens, webhooks, or account
identifiers.

## Related Pages

- [[pattern-human-review-output-contract]]
- [[reference-data-sources-time-basis]]
- [[decision-asx-upstream-diff-roadmap-2026-05-29]]

