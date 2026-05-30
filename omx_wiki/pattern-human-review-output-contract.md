# Pattern: Human Review Output Contract

Category: pattern
Tags: output-contract, human-review, block, ai-boundary

## Purpose

This pattern keeps reports, alerts, workbench output, and review artifacts from
being mistaken for automatic trading instructions.

## Contract

- The system may summarize evidence, identify risks, and prepare conditional
  plan references.
- AI may explain deterministic outputs and list invalidation conditions.
- AI must not override deterministic action fields or validation gates.
- `BLOCK` must remain non-actionable and cannot leak executable fields.
- Alert Center items and future alert-rule outputs must be review prompts, not
  order instructions.

## Conditional Plan Points

Any displayed buy, sell, stop-loss, or target reference should include:

- Source.
- Trigger condition.
- Invalidation condition.
- Price basis.
- Technical basis date when available.
- Manual review requirement.

If a source is unclear or AI-extracted, mark it as unverified or observation
only.

## Review Language

Prefer wording such as:

- needs review
- observe only
- evidence missing
- validation blocked
- delayed data
- unavailable source
- manual confirmation required

Avoid wording that implies direct execution, guaranteed fills, automatic stops,
or broker submission.

## Related Pages

- [[project-boundary-and-safety-contract]]
- [[architecture-report-evidence-pipeline]]
- [[architecture-workbench-alert-center]]

