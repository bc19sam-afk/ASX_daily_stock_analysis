# Daily Review Journal

The daily review journal is a local review artifact for the original roadmap item `P2-4 Daily Review Journal`.

It records:

- the morning `daily_decision_summary` actions
- user-provided manual execution notes
- optional post-trade notes

It is not a trading ledger, broker connector, or portfolio update mechanism.

## Boundaries

- It does not connect to a broker.
- It does not place orders.
- It does not write to a real account.
- It does not infer whether an order was filled.
- It does not modify portfolio holdings.
- It does not modify the morning daily report or its deterministic action fields.

All manual execution notes are stored with `user_provided: true`.

## Artifact

The first version writes a JSON artifact:

```text
reports/review_journal_YYYYMMDD.json
```

The artifact contains a top-level `review_journal` object with schema version `review_journal.v1`.
