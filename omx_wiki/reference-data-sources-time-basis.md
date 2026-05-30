# Reference: Data Sources And Time Basis

Category: reference
Tags: data-source, timezone, close-only, delayed, asx

## Purpose

This page keeps recurring data-source and time-basis facts in one place.

## Time Basis

- The default ASX daily report is an Australia/Sydney pre-open report.
- The default planning basis is `close_only` previous-close data.
- Outputs should clearly label `close_only`, delayed, stale, missing, or
  unavailable data.
- Avoid hard-coded local clock assumptions when ASX market calendar helpers are
  available.

## Data Sources

Current ASX-oriented evidence may include:

- YFinance for ASX/AU/US market data, with delayed or missing data caveats.
- ASX official Market Announcements listing metadata as read-only evidence.
- Tavily, Gemini Grounding, SerpAPI, and news_intel cache for news/search
  evidence, depending on configuration and quota.
- Gemini 3.5 Flash for analysis or explanation work, subject to configured
  keys and rate limits.

## External Constraint Summary

- Public/low-cost market data should not be treated as realtime by default.
- Realtime ASX data requires explicit data licensing or provider setup.
- Broker APIs such as IBKR, Saxo, IG, and Openmarkets are future research
  surfaces, not default execution paths.
- Automated order handling in Australia has regulatory and operational
  obligations, so any broker/execution work must enter a separate scope.

## Wiki Rule

Keep source links and stable summaries here. Do not store API keys, credentials,
account identifiers, raw broker exports, or real order information.

