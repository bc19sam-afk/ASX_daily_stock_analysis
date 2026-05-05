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

## Offline Evaluator

P2-2a adds an offline-only evaluator. It accepts `IntradayReviewMarketInput`
objects supplied by a caller or test fixture and produces
`IntradayReviewEvaluation` objects.

`IntradayReviewMarketInput`:

- `code`
- `last_price`
- `previous_close`
- `price_timestamp`
- `has_price_sensitive_risk`
- `liquidity_warning`
- `notes`

`IntradayReviewEvaluation`:

- `code`
- `morning_action`
- `review_status`
- `reason`
- `price_deviation_pct`
- `required_manual_checks`
- `source`: always `offline_input`
- `is_trade_instruction`: always `false`

Rules:

- Inputs are caller-supplied; the evaluator does not fetch realtime prices.
- Missing `last_price` or `previous_close` degrades to observe-only.
- Price-sensitive risk blocks review output.
- Liquidity warnings keep items waiting or observe-only.
- Morning BLOCK items can only remain observe-only or block.
- PASS/actionable items can be `still_valid` only for manual review, never as a
  trade instruction.

## Future P2-2 Guardrails

A future implementation may build a separate intraday report, but it must stay
outside the default daily workflow and remain manual-review only. It must not
connect brokers, write accounts, place orders, or let AI override deterministic
validation and action gates.
