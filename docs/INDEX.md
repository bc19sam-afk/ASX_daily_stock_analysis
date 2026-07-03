# Documentation Index

This is the user-facing entry point for common ASX/AU/US analysis and
contribution tasks.
For internal roadmap decisions, maintainer runbooks, and project control-plane
notes, use [`omx_wiki`](../omx_wiki/index.md) instead of copying those details
into public docs.

Do not put API keys, broker credentials, HINs, account numbers, real order
details, fill confirmations, or raw logs into docs, issues, PRs, or prompts.
Paper, simulated, and review-journal records are manual-review artifacts; they
are not proof of real executions.

## I want to run the daily ASX report

Start with the root [`README`](../README.md) for the current ASX-first setup,
runtime modes, report outputs, and GitHub Actions entry points.

Use these next:

- [`docs/full-guide_EN.md`](full-guide_EN.md) for complete environment-variable
  setup, GitHub Actions configuration, notification channels, and advanced
  runtime options.
- [`docs/DEPLOY_EN.md`](DEPLOY_EN.md) when running on Docker, a server, or a
  long-running service.
- [`.github/workflows/daily_analysis.yml`](../.github/workflows/daily_analysis.yml)
  to inspect the scheduled/manual workflow shape.

The normal daily report flow prepares evidence, risk prompts, recommendations,
and notifications for manual review. It does not submit trades.

## I want to view Workbench

Start the API server as described in the root [`README`](../README.md), then
use the Workbench and Alert Center surfaces to inspect "what needs a look
today."

Useful references:

- Root [`README`](../README.md) for API server startup and Workbench endpoint
  overview.
- [`docs/full-guide_EN.md`](full-guide_EN.md) for API and local runtime
  configuration.
- [`omx_wiki/architecture-workbench-alert-center.md`](../omx_wiki/architecture-workbench-alert-center.md)
  for maintainer-level architecture context.

Workbench and Alert Center are read-only manual-review surfaces. They do not
connect to brokers, place orders, monitor realtime trading, or change
deterministic action fields.

## I want to check diagnostics, provider cache, alert dry-runs, or ledger diagnostics

Use these routes and docs when you need to understand why a run looks degraded
or what review evidence is available:

- Workbench diagnostics: `GET /api/v1/workbench/diagnostics`.
- Workbench summary and alerts: `GET /api/v1/workbench/summary`,
  `GET /api/v1/workbench/alerts`, and
  `GET /api/v1/workbench/alerts/summary`.
- Alert-rule dry-run API: use the Workbench Alert Center path before treating
  any alert as actionable.
- Provider/cache status: start from the Workbench summary and diagnostics
  fields; they are visibility signals, not live quota probes.
- Ledger diagnostics: read [`docs/portfolio-ledger-v2-plan.md`](portfolio-ledger-v2-plan.md)
  for the current read-only rehearsal/shadow-diagnostics posture.

For internal status and roadmap boundaries, use:

- [`omx_wiki/decision-asx-roadmap-control-plane.md`](../omx_wiki/decision-asx-roadmap-control-plane.md)
- [`omx_wiki/reference-roadmap-status-and-pr-log.md`](../omx_wiki/reference-roadmap-status-and-pr-log.md)

## I want to configure data sources and model sources

Start here:

- Root [`README`](../README.md) for the shortest current setup.
- [`docs/full-guide_EN.md`](full-guide_EN.md) for the complete configuration
  list.
- [`docs/FAQ_EN.md`](FAQ_EN.md) for common data, model, quota, and notification
  problems.
- [`docs/DEPLOY_EN.md`](DEPLOY_EN.md) for server and Docker configuration.
- [`.env.example`](../.env.example) for variable names and safe placeholders.

Keep real secret values in your local `.env`, GitHub Secrets, or your deployment
secret store. Do not paste them into documentation, logs, wiki pages, PRs, or
review comments.

## I want to understand the manual-review and non-automatic-trading boundary

Read these before changing report, portfolio, alert, ledger, or broker-adjacent
behavior:

- Root [`README`](../README.md) for the user-facing disclaimer and runtime
  assumptions.
- [`docs/review_journal.md`](review_journal.md) for why review journal entries
  are not a trading ledger or broker record.
- [`docs/portfolio-ledger-v2-plan.md`](portfolio-ledger-v2-plan.md) for the
  current ledger v2 rehearsal and non-cutover posture.
- [`omx_wiki/project-boundary-and-safety-contract.md`](../omx_wiki/project-boundary-and-safety-contract.md)
  for the internal maintainer safety contract.

Broker connections, real-account access, real order submission, or automatic
execution require a separately scoped broker/execution task. They are outside
normal report, Workbench, diagnostics, and documentation work.

## I want to troubleshoot common failures

Start with [`docs/FAQ_EN.md`](FAQ_EN.md). It covers common data-source, model,
quota, notification, Docker, and API access failures.

Then use the smallest relevant check:

- Daily report or GitHub Actions failure: inspect the workflow run and generated
  report artifacts before changing configuration.
- API or Workbench failure: check the API server mode in the root
  [`README`](../README.md), then inspect Workbench diagnostics.
- Provider/cache uncertainty: compare report evidence, Workbench status, and
  provider/cache fields before assuming a live provider outage.
- Ledger or review-journal confusion: read
  [`docs/portfolio-ledger-v2-plan.md`](portfolio-ledger-v2-plan.md) and
  [`docs/review_journal.md`](review_journal.md) before treating any reviewed,
  paper, or simulated entry as real execution evidence.

When sharing a failure for review, summarize the symptom and relevant status
fields. Do not paste raw secrets, raw account identifiers, raw broker data, or
full logs containing sensitive values.

## I am contributing and want to validate a PR

Start with:

- [`AGENTS.md`](../AGENTS.md) for the repository operating contract.
- [`CONTRIBUTING.md`](../CONTRIBUTING.md) and
  [`docs/CONTRIBUTING.md`](CONTRIBUTING.md) for contribution expectations.
- [`scripts/ci_gate.sh`](../scripts/ci_gate.sh) for the backend validation gate.
- [`omx_wiki/index.md`](../omx_wiki/index.md) when the work touches roadmap,
  safety boundaries, Workbench, alert, portfolio, ledger, or broker-adjacent
  behavior.

This is the contributor-only part of the index. For documentation-only PRs, at
minimum check that changed links point to existing paths and run
`git diff --check`. If a markdown/docs lint command is introduced later, run it
as part of the docs PR gate.

## I want the short upstream-learning engineering-shape summary

This contributor-facing summary is a lightweight orientation note, not the
roadmap authority. Durable decisions and control-plane context stay in
[`omx_wiki`](../omx_wiki/index.md).

- CI phase gate: when validating a PR, use the smaller backend phases in
  `scripts/ci_gate.sh` to find failures closer to their source.
- Notification sender split: when reading notification code, expect channel
  dispatch to stay separate from main notification orchestration.
- Report renderer fallback: when touching report rendering, preserve the
  fail-open path that keeps report generation working if the renderer cannot
  render a fragment.
- Run-flow diagnostics: when checking Workbench diagnostics, treat the run-flow
  contract as compact, read-only operator visibility with no new side effects.
- User documentation index: start from this page by goal; keep internal
  strategy and roadmap records in [`omx_wiki`](../omx_wiki/index.md).
