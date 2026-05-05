# Intraday Review Contract

`intraday_review` is a future independent mode. It consumes an already-generated
`daily_decision_summary_YYYYMMDD.json` and must not be mixed into the close-only
daily report workflow.

## Boundary

- Contract only in P2-1.
- No realtime quote fetching.
- No AI re-decision.
- No broker integration.
- No automatic trading.
- No account writes.
- No daily report changes.
- No workflow changes.

The daily report remains an Australia/Sydney pre-open, close-only morning plan
for human review.

## Input

`IntradayReviewInput`:

- `report_date`
- `source_summary_path`
- `technical_basis_date`
- `price_policy`
- `price_policy_source_note`
- `actionable_items`
- `watch_items`
- `blocked_items`

`price_policy` is required. For `close_only`, the source note must preserve that
the morning summary is based on last close / pre-open planning, not realtime
execution data.

## Decision

`IntradayReviewDecision`:

- `code`
- `morning_action`
- `review_status`: `still_valid`, `wait`, `cancel`, `observe_only`, or `block`
- `reason`
- `required_manual_checks`

Morning BLOCK items can only remain `observe_only` or `block`. A future review
mode may not convert a BLOCK item into an actionable intraday item.

## Future P2-2 Guardrails

A future implementation may build a separate intraday report, but it must stay
outside the default daily workflow and remain manual-review only. It must not
connect brokers, write accounts, place orders, or let AI override deterministic
validation and action gates.
