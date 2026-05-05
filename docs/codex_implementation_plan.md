# Codex Roadmap Executor Implementation Plan

## Operating Rules

- Work in small, reviewable, reversible PRs.
- Start at P0-2. P0-1 is complete via PR #99 and must not be reimplemented.
- Use one branch per PR and one PR per branch.
- Audit current `main` before each PR. If the PR is already satisfied, add only missing tests or mark `already_satisfied`.
- If a gap exists, make the smallest patch that satisfies that PR only.
- Automatically execute only P0-2 through P0-6. Stop after P0-6 and wait before P1.
- Stop after opening each PR and wait for review / merge before continuing to the next PR.
- Do not combine multiple roadmap PRs into one diff.
- Do not do incidental refactors.
- Do not mix `intraday_review` into the daily report.
- Do not connect brokers, automate trading, or write to real trading accounts.

## Long-Term Project Boundary

This is an ASX-first daily stock analysis and reporting system. The default report is an Australia/Sydney pre-open daily report based on a `close_only` previous-close plan. It is a human decision-support system, not an automated trading system.

AI may explain deterministic outputs, summarize evidence, and list risks or invalidation conditions. AI must not override `final_decision`, `position_action`, or validation gates. `BLOCK` must hard-block pseudo-execution semantics. Buy, sell, stop-loss, and target points may remain only as conditional plan points with source, trigger condition, invalidation condition, and required human review before execution.

## Execution Flow Per PR

1. Start from `main` and fast-forward pull.
2. Create a new branch for the single PR.
3. Audit whether current `main` already satisfies the PR.
4. If already satisfied, add only missing tests or mark `already_satisfied`.
5. If a gap exists, implement the minimal patch.
6. Run targeted tests.
7. Run full `python -m pytest` if time allows.
8. Self-review the diff.
9. Confirm forbidden files were not modified unless the current PR explicitly allows them.
10. Update `docs/codex_execution_log.md`.
11. Commit with the repo Lore commit protocol.
12. Push the branch.
13. Create a PR to `main`.
14. Stop and wait for review / merge before continuing.

## Stop Conditions

Stop immediately if tests fail and cannot be fixed inside the current PR scope, the scope grows beyond the current PR, project boundaries would need to change, unauthorized workflow / `close_only` / position-manager / data-provider / storage / database changes become necessary, broker or auto-trading integration would be required, current `main` is inconsistent with the roadmap assumptions, or the diff becomes too large for the PR.

## P0-1 AI Role Boundary

**Status:** Completed and merged via PR #99.

**Goal:** Demote the LLM from trading decision maker to explainer. AI can explain deterministic actions, summarize evidence, and list risks or invalidation conditions, but cannot override `final_decision`, `position_action`, or validation gates.

**Do Not Do:** Do not reimplement P0-1 or edit the analyzer prompt unless later tests prove a regression.

**Execution Log Requirement:** Mark `P0-1: merged via PR #99`.

## P0-2 Conditional Plan Points v1

**Goal:** Turn ideal buy, secondary buy, stop-loss, and take-profit points into conditional plan points with source, trigger condition, invalidation condition, manual-review requirement, price basis, and technical basis date.

**Why:** Price points can remain in the ASX pre-open `close_only` plan, but must not read like direct trading instructions. They must be human-review references before any real-world action.

**Do Not Do:**

- Do not connect realtime feeds or implement intraday review.
- Do not change position sizing or position-manager rules.
- Do not change AI output parsing as a main chain.
- Do not change workflows, `daily_analysis.yml`, or `close_only`.
- Do not connect brokers, auto-trade, write real accounts, or add database migrations.
- Do not refactor `src/notification.py` beyond necessary display changes.

**Expected Files:**

- `src/conditional_plan.py`
- `src/notification.py`
- `src/notification_dashboard_observation_builders.py`
- `src/notification_recommended_action_builders.py`
- `tests/test_conditional_plan_points.py`
- `tests/test_report_conditional_price_points.py`

Prefer extending existing helpers or tests if they already exist.

**Data Structure:**

`ConditionalPlanPoint`

- `label: ideal_buy | secondary_buy | stop_loss | take_profit`
- `price: Optional[float]`
- `source_type: ma | atr | prior_high_low | ai_extracted | unavailable`
- `source_detail: str`
- `condition: str`
- `invalidation: str`
- `requires_manual_review: bool`
- `price_basis: close_only | non_executable_reference`
- `technical_basis_date: str`

If the source is unclear, display: `来源：AI 提取，未验证；仅作观察参考，不作为执行价格。`

**Report Display Change:**

Replace naked points such as `理想买入点`, `止损位`, and `目标位` with `条件化计划点位` entries. Each displayed point must show source, trigger condition, invalidation condition, and manual-review requirement.

For `BLOCK` symbols, do not show executable points. Only show observation references or no points. Do not show target weight, rebalance amount, target quantity, or executable buy / sell points.

**Tests:**

- No point is displayed naked.
- Every displayed point includes source, trigger condition, invalidation condition, and manual-review prompt.
- `BLOCK` symbols do not display executable points.
- `price_basis` is `close_only` or explicitly non-executable reference.
- AI-extracted points show unverified / observation-only wording.
- Reports do not treat points as direct trading instructions.

**Acceptance:**

- `python -m pytest tests/test_conditional_plan_points.py tests/test_report_conditional_price_points.py`
- Related existing report tests pass.
- Reports contain no naked `买入点 / 止损位 / 目标位` executable display.
- `BLOCK` symbols cannot leak executable points.
- No workflow / `close_only` / position-manager / data-provider / storage change.

**Risks:**

- Report may become longer.
- Home dashboard should stay concise while details carry full conditions.
- `src/notification.py` is coupled, so changes must remain minimal.

## P0-3 Evidence Matrix v1

**Goal:** Generate an evidence matrix for each stock covering market, technical, valuation, news, announcement, backtest, portfolio, and validation data with source, timestamp, and missing/stale status.

**Why:** Report trust should come from auditable evidence rather than AI prose. Conclusions must be traceable to data sources and data time.

**Do Not Do:**

- Do not add external data sources or ASX official announcement scraping.
- Do not change analysis logic, position rules, workflow, `close_only`, or database schema.
- Do not implement report reliability score in this PR.

**Expected Files:**

- `src/evidence_matrix.py`
- `src/daily_decision_summary.py`
- `src/notification.py`
- `tests/test_evidence_matrix.py`
- `tests/test_daily_decision_summary_evidence.py`
- `tests/test_daily_decision_dashboard_archive.py`

**Data Structure:**

Add optional `evidence_matrix` to `daily_decision_summary`:

- `category: market_data | technical | valuation | news | announcement | backtest | portfolio | validation`
- `source: str`
- `as_of_date: str | null`
- `status: available | missing | stale | not_checked`
- `details: str`
- `severity: info | warning | block`

Keep backward compatibility. If strict top-level schema tests require it, use a versioned summary change such as `daily_decision_summary.v1.1` and update tests only.

**Report Display Change:**

Dashboard evidence quality summary, for example complete market-data count, missing news count, insufficient backtest count, and validation block count. Stock detail includes an evidence table with category, source, time, status, and details.

**Tests:**

- Summary includes `evidence_matrix`.
- Missing `market_snapshot.date` is marked missing or stale.
- `validation_status=BLOCK` produces evidence with `severity=block`.
- Missing news / backtest / valuation is visible as missing or not_checked.
- Schema stability tests are updated.
- Evidence matrix does not change action count, watch list, or blocked list.

**Acceptance:**

- `python -m pytest tests/test_evidence_matrix.py tests/test_daily_decision_summary_evidence.py tests/test_daily_decision_dashboard_archive.py`
- Missing data is not hidden.
- Existing dashboard behavior and `BLOCK` semantics remain intact.
- `close_only` is unaffected.

**Risks:**

- Summary schema changes may affect existing tests.
- Evidence logic must not influence action generation.
- AI must not use evidence matrix to decide actions.

## P0-4 Report Reliability Score v1

**Goal:** Add `report_reliability` to explain whether the daily report is reliable enough for a pre-open manual review plan.

**Why:** A high stock score does not imply high report reliability. Missing data, stale evidence, many blocks, insufficient backtests, and price-basis mismatch should lower trust in the report itself.

**Dependency:** Requires P0-3 `evidence_matrix`. If P0-3 is not completed and merged, stop before implementing P0-4.

**Do Not Do:**

- Do not change buy / sell decisions, sizing, validation gates, or `position_action`.
- Do not introduce a complex model or treat reliability as a trading signal.
- Do not implement P1 backtest confidence or ASX announcement scraping.
- Do not add database migrations.

**Expected Files:**

- `src/report_reliability.py`
- `src/daily_decision_summary.py`
- `src/notification.py`
- `tests/test_report_reliability_score.py`
- `tests/test_daily_decision_dashboard_archive.py`

**Data Structure:**

Add `report_reliability`:

- `score: int`
- `level: high | usable_with_manual_review | low_observe_only`
- `components.price_basis_consistency: int`
- `components.market_data_freshness: int`
- `components.evidence_completeness: int`
- `components.validation_health: int`
- `components.backtest_support: int`
- `flags[].code: str`
- `flags[].severity: info | warning | block`
- `flags[].message: str`

Rules must be simple and explainable. `close_only`, consistent price basis, fresh market data, complete evidence, and healthy validation increase score. `BLOCK`, missing/stale evidence, and mixed/non-close-only price policy reduce score. Missing backtest should be a small penalty or warning, not a blocker.

**Report Display Change:**

Dashboard top shows reliability score, level, and main deductions. Low reliability displays: `报告可信度偏低：不建议直接依据本报告执行，仅用于观察和人工复核。`

**Tests:**

- Complete close-only report without blocks scores high.
- `BLOCK` reduces score.
- Missing news or evidence reduces score.
- Non-close-only or mixed price policy reduces score.
- Low score displays observe-only / do-not-execute wording.
- Reliability does not change `position_action` or action counts.
- `BLOCK` semantics are unchanged.

**Acceptance:**

- `python -m pytest tests/test_report_reliability_score.py tests/test_daily_decision_dashboard_archive.py`
- Dashboard displays reliability.
- Reliability never changes deterministic actions.
- Low reliability does not strengthen action wording.

**Risks:**

- Score weights may be disputed.
- First version must stay conservative, transparent, and explainable.

## P0-5 Final Action Display Contract

**Goal:** Centralize final action display so report, summary, history, and dashboard do not infer actions separately.

**Why:** Prevent display drift where one output shows HOLD while another shows ADD. All report exits should consume one final display object.

**Do Not Do:**

- Do not refactor the full pipeline or rewrite `AnalysisResult`.
- Do not change database, backtest engine, AI output structure, PositionManager action generation, workflows, or `close_only`.
- Do not perform a large `notification.py` split.

**Expected Files:**

- `src/final_action_display.py`
- `src/daily_decision_summary.py`
- `src/notification.py`
- `src/notification_recommended_action_builders.py`
- `tests/test_final_action_display_contract.py`
- `tests/test_blocked_action_display.py`
- `tests/test_daily_decision_dashboard_archive.py`

**Data Structure:**

`FinalActionDisplay`

- `code`
- `name`
- `validation_status`
- `actionability: actionable | watch_only | blocked | failed`
- `final_decision`
- `position_action`
- `target_weight`
- `current_weight`
- `delta_amount`
- `reason`
- `display_label`
- `can_show_sizing: bool`
- `can_show_plan_points: bool`

Rules:

- `BLOCK`: `actionability=blocked`, no sizing, no plan points.
- `FAILED`: `actionability=failed`, no sizing, no plan points.
- HOLD/watch: `actionability=watch_only`, no sizing unless existing holding context requires non-executable display.
- OPEN/ADD/REDUCE/CLOSE: actionable only if PASS and the effective delta threshold is passed.

**Report Display Change:**

All major action tables and dashboards use `FinalActionDisplay`. `BLOCK` displays only unavailable / observe-only wording and validation reason, never target weight, delta amount, buy point, stop-loss, target price, or executable advice.

**Tests:**

- `BLOCK` always has `can_show_sizing=false`.
- `BLOCK` always has `can_show_plan_points=false`.
- Tiny delta becomes watch, not actionable.
- Recommended action table and dashboard counts match.
- AI prose containing buy/sell does not change display action.
- Dashboard archive tests pass.
- Display object does not mutate underlying deterministic result.

**Acceptance:**

- `python -m pytest tests/test_final_action_display_contract.py tests/test_blocked_action_display.py tests/test_daily_decision_dashboard_archive.py`
- Main report exits show consistent actions.
- `BLOCK` cannot leak pseudo-execution fields.
- Pipeline decision order is unchanged.

**Risks:**

- `src/notification.py` is large.
- Only add the display helper; do not perform broad notification refactoring.

## P0-6 API Auth Guard v1

**Goal:** Add minimal optional Bearer Token auth for API / web console protected endpoints, especially config read/update endpoints.

**Why:** If the FastAPI / web console is exposed beyond local use, configuration endpoints are high risk. Provide a minimal boundary while preserving local and GitHub Actions daily runs.

**Do Not Do:**

- Do not implement users, OAuth, roles, or a full login UI.
- Do not protect `/api/health`.
- Do not affect GitHub Actions CLI daily reports, daily report generation, `close_only`, or analysis pipeline.
- Do not connect brokers or automate trading.

**Expected Files:**

- `api/deps.py`
- `api/app.py`
- `api/v1` endpoints as needed
- `tests/test_api_auth_guard.py`
- `.env.example`
- `README.md` or `README.zh-CN.md`

**Data Structure / Config:**

- `API_AUTH_ENABLED=true | false`
- `API_AUTH_TOKEN=`

Suggested behavior:

- Local development may disable auth.
- Production or non-localhost binding should enable auth.
- If `API_AUTH_ENABLED=true` and token is missing, protected endpoints return 401.
- Wrong token returns 401.
- Correct `Bearer` token allows protected endpoints.
- `/api/health` remains public.
- Optional warning if binding to `0.0.0.0` with auth disabled, if existing config supports it.

**Report Display Change:** None.

**API Documentation Change:** Replace any statement that the API has no auth with optional Bearer Token auth guidance and production/public-access recommendation.

**Tests:**

- Auth disabled preserves compatibility.
- Auth enabled without token returns 401 for `/api/v1/config`.
- Auth enabled with wrong token returns 401.
- Correct Bearer Token grants access.
- `/api/health` does not require auth.
- CORS remains intact.
- CLI / GitHub Actions daily run remains unaffected.

**Acceptance:**

- `python -m pytest tests/test_api_auth_guard.py`
- Existing API tests pass.
- `.env.example` documents the variables.
- API docs no longer claim no auth requirement.
- Daily report / `close_only` / workflow unaffected.

**Risks:**

- Frontend may need later token injection.
- First version should stay backend-and-docs minimal, without a login system.

## P1 Roadmap - Write Only, Do Not Execute Yet

P1 is for calibration, review, and controlled sizing. It is documented here but must not be executed until the user confirms after P0-6.

### P1-1 Backtest Confidence Panel v1

Add a report panel for historical signal confidence using existing backtest service outputs, with sample size, window, win rate, average simulated return, confidence level, and low-sample warnings. Do not alter actions.

### P1-2 Score Bucket Calibration

Group historical results by score buckets such as 60-70, 70-80, and 80-100 to calibrate scoring. Do not change scoring or actions.

### P1-3 Risk-Based Sizing v1

Constrain existing fixed sizing using simple risk budget caps. Do not connect brokers, auto-trade, or remove the old rule in the first version.

### P1-4 Structured Valuation Snapshot

Structure PE, PB, dividend yield, market cap, ROE, and debt-to-equity fields instead of mixing dividend yield into PE strings. Preserve compatibility where needed.

### P1-5 ASX Search Localisation

Make ASX news search ASX / Australia / English-first by default while preserving non-ASX and Chinese compatibility as secondary behavior.

## P2 Roadmap - Write Only, Do Not Execute Yet

P2 is for intraday review and long-term feedback loops. It must not be executed until the user confirms after P1.

### P2-1 Intraday Review Input Contract

Define the input/output contract for future independent `intraday_review`, consuming morning summaries without implementing realtime strategy or changing the daily report.

### P2-2 Intraday Review v1

Implement a separate intraday review mode that reads the morning summary and realtime prices to validate whether the morning plan is still valid. Do not merge it into the daily workflow.

### P2-3 ASX Official Announcement Check Contract

Define a conservative announcement-check abstraction and report display status. Do not implement brittle scraping or claim unchecked announcements are clear.

### P2-4 Daily Review Journal

Create artifact-based review journals linking morning actions, intraday reviews, manual notes, and later observations. Do not connect brokers or real account records.

## P0 Completion Stop

After P0-6, stop and report:

1. P0 completion overview.
2. Created / merged PR list.
3. Test results per P0 PR.
4. Unresolved risks.
5. Whether entering P1 is recommended.
6. Wait for user confirmation.
