# Reference: Upstream Diff Evidence 2026-05-29

Category: reference
Tags: upstream-diff, evidence, asx, source-thread

## Purpose

This page preserves the file-level evidence from the read-only upstream diff
thread without copying the full conversation.

Source thread:
`codex://threads/019e73a9-65d6-79f0-a84f-153d49079eed`

## Baselines From The Thread

- Current ASX repo baseline: `48e82fa95b0676715f103769827e536fc1689ad5`.
- Upstream baseline: `c6cad832322f30144cbdecfe1307367108928fab`.
- Upstream temporary checkout used in the analysis:
  `/tmp/ZhuLinsen_daily_stock_analysis_upstream`.

These baselines are historical evidence for the 2026-05-29 analysis. Re-check
current local and upstream heads before doing a new diff.

## Evidence Summary

### Workbench

- Current ASX project already had a workbench summary endpoint and static UI.
- Upstream had a richer React application with routes, sidebar navigation, and
  smoke tests.
- Decision: do not rebuild "a workbench exists"; instead borrow UI structure
  and smoke-test patterns when the ASX UI grows.

### AnalysisContextPack

- Current ASX project already had ASX/AUD/Australia/Sydney context semantics.
- Upstream had a lower-sensitivity prompt summary renderer and tests that
  avoided leaking raw secrets or sensitive values.
- Decision: add a safe renderer in future work rather than injecting overly
  broad context into prompts.

### Portfolio And CSV Import

- Current ASX project already had ASX CSV import, manual portfolio review
  fields, paper/simulated surfaces, and HIN/franking-related placeholders.
- Upstream had parser-spec and dedup-counter patterns.
- Decision: adopt parser registry and dedup ideas, but adapt to ASX broker CSV,
  AUD, settlement, brokerage, GST, dividends, franking, and corporate actions.

### Alert Center

- Current ASX project had a read-only Alert Center for manual review risks.
- Upstream had alert CRUD, dry-run, triggers, notification attempts, and
  portfolio/watchlist expansion.
- Decision: implement ASX dry-run alert rules first; do not default to a
  background notification worker.

### Data And Quota Strategy

- Current ASX project already had Gemini 3.5 Flash, Tavily/Gemini
  Grounding/SerpAPI, yfinance, ASX announcement metadata, and cache-aware
  behavior.
- Decision: add provider budget/status visibility before adding new sources.

### Broker-Ready Boundary

- Current ASX project had paper/simulated behavior and review journal
  boundaries.
- External broker APIs exist but require credentials, demo/live distinctions,
  and execution-specific safety controls.
- Decision: future work may define draft/paper order contracts, but no real
  broker connection without explicit broker/execution scope.

## Official Source Links Mentioned In The Thread

- ASX price data: https://www.asx.com.au/connectivity-and-data/information-services/price-data
- ASIC RG 241 Electronic trading: https://asic.gov.au/regulatory-resources/find-a-document/regulatory-guides/rg-241-electronic-trading/
- IBKR TWS API: https://www.interactivebrokers.com/campus/ibkr-api-page/twsapi-doc/
- Saxo OpenAPI: https://www.developer.saxo/openapi/learn
- IG REST trading API: https://labs.ig.com/rest-trading-api-guide.html
- Openmarkets developers: https://openmarkets.com.au/developers

## Reuse Rule

Use this page as a roadmap evidence index, not as a substitute for a fresh diff.
Before implementing any upstream-inspired feature, re-check the current ASX
repo and current upstream state.

