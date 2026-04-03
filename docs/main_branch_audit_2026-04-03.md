# Main Branch Audit (2026-04-03)

## Scope and PRs reviewed
- PR #36 (`90f71ba`), PR #39 (`6c7388a`), PR #40 (`5056448`), PR #45 (`2b0571e`)
- PR #48 (`a014831`)
- PR #51 (`aabd114`), PR #54 (`274b905`)
- Current branch tip at audit time: `6c08fad`

---

## 1) Execution price basis / realtime vs close policy
**Status:** PR description does not match merged diff.

**Evidence**
- Runtime execution price is resolved by `StockAnalysisPipeline._resolve_execution_price()` with hard-coded priority realtime -> today.close and no policy argument. `result.current_price` is then set from this result and used for position management. (`process_single_stock` -> `_resolve_execution_price` -> `_apply_position_management`).
- Runtime source label is resolved by `_resolve_execution_price_source()` as `realtime/latest_close/close_only`, but still with no `execution_price_policy` branch.
- `execution_price_policy` exists in config and config registry but is never consumed in pipeline/analyzer runtime.
- Tests in `tests/test_execution_price_policy.py` only validate config parsing/normalization, not runtime pipeline behavior.

**Current behavior on main**
- Execution price basis in runtime is effectively fixed to “prefer realtime, fallback close”, regardless of `EXECUTION_PRICE_POLICY`.
- Price-basis disclosure improvements from PR #36/#39/#40 mostly affect reporting/rendering fields and labels.

**Remaining gap**
- Policy is not wired into execution call chain.
- No end-to-end tests proving `close_only` forces close-only execution path.
- Signal basis vs execution basis separation is only partially explicit: runtime has execution source label, but no policy-controlled behavior split.

**Minimal next fix**
- Thread `config.execution_price_policy` into `_resolve_execution_price` / `_resolve_execution_price_source` and enforce:
  - `close_only`: ignore realtime price for execution.
  - `realtime_if_available`: keep current fallback.
- Add integration test around `process_single_stock` asserting runtime `current_price` and `execution_price_source` under both policy modes.

---

## 2) Missing snapshot metrics guard
**Status:** partially fixed.

**Evidence**
- Guard methods (`_is_missing_snapshot_metric`, `_has_missing_volume_snapshot_metrics`, `_guard_volume_commentary`, `_guard_technical_analysis_volume_commentary`) are implemented in `NotificationService` and used during report rendering.
- Tests in `tests/test_notification_summary_format.py` verify downgraded volume commentary in rendered output when `volume_ratio`/`turnover_rate` are missing.
- Upstream analysis output (`GeminiAnalyzer.analyze` / `_parse_response`) is unchanged by these guards; model can still produce strong volume conclusions before rendering-time downgrade.

**Current behavior on main**
- Human-facing report text suppresses volume conclusions in guarded render paths.
- Structured analysis fields and raw AI outputs may still contain confident volume language.

**Remaining gap**
- No upstream sanitization for structured fields / stored analysis artifacts.
- Guard is presentation-layer centric.

**Minimal next fix**
- Add a post-parse sanitization stage on `AnalysisResult` before persistence/notification to nullify or downgrade volume-dependent fields when required snapshot metrics are missing.

---

## 3) Analysis coverage / valuation provenance
**Status:** partially fixed.

**Evidence**
- Portfolio overview now exposes per-holding valuation source and analyzed-today coverage labels.
- Reconciliation section discloses unmanaged holdings weight.
- Tests verify coverage display and provenance labels.
- No hard gating or degraded decision severity tied to uncovered live holdings in pipeline.

**Current behavior on main**
- Report discloses uncovered holdings but still produces normal portfolio-level recommendation sections.

**Remaining gap**
- “Disclosure-only” fix; no warning escalation / hard-fail when coverage is incomplete.

**Minimal next fix**
- Introduce coverage threshold gate (e.g., analyzed live-holding weight < X%) to append explicit warning and downgrade confidence or suppress “complete-looking” portfolio recommendations.

---

## 4) Market review quality
**Status:** not fixed.

**Evidence**
- ASX path explicitly skips `_get_market_statistics` and `_get_sector_rankings` in `get_market_overview`.
- Template fallback still renders zero-valued breadth/turnover and empty leaders/laggards sections.
- Market review uses a dedicated markdown prompt builder (`_build_review_prompt`) and does not reuse stock JSON dashboard prompt.
- Missing stats blocks are omitted in `_inject_data_into_review`, but template fallback can still output “healthy-looking” skeleton with zeros.

**Current behavior on main**
- Dedicated prompt exists (good).
- Missing upstream market stats can still lead to placeholder sections in template mode.

**Remaining gap**
- No strict N/A rendering or section suppression for unavailable breadth/turnover/sector stats in template fallback.

**Minimal next fix**
- In `_generate_template_review`, render “N/A/不可用” and hide sections when stats/sectors are unavailable instead of outputting zero placeholders.

---

## 5) Data sanitization
**Status:** not fixed.

**Evidence**
- Prompt assembly directly injects `context['fundamentals']` key-values into fundamentals table without hard numeric validation bounds.
- No centralized sanitizer found for unrealistic dividend yield/PE/growth values before prompt/report usage.

**Current behavior on main**
- Potentially abnormal fundamentals can flow into prompts and downstream narrative.

**Remaining gap**
- Missing hard validation/clamping/drop rules on key fundamental ratios.

**Minimal next fix**
- Add a `sanitize_fundamentals()` step in pipeline/analyzer input preparation with explicit bounds and anomaly flags, then surface “data abnormality” warnings in reports.

---

## 6) Prompt time hardcoding
**Status:** not fixed.

**Evidence**
- System prompt hardcodes: “currently in February 2026 earnings season”.
- Prompt body also hardcodes “check whether currently in February or August earnings month”.

**Current behavior on main**
- Time-sensitive prompt text is static and can become stale.

**Remaining gap**
- No dynamic season/month derivation from run date.

**Minimal next fix**
- Generate earnings-season instruction dynamically from runtime date and market calendar metadata.

---

## 7) Search cost / duplication audit
**Status:** partially fixed.

**Evidence**
- Query-level in-memory TTL cache exists (`_cache`, `_cache_key`, `_get_cached`, `_put_cache`) and is used in `search_stock_news`.
- Comprehensive intel path executes 5 dimensions per stock and does not use `max_searches` to limit dimension count.
- No same-day ticker-level shared cache across dimensions; each dimension issues separate provider calls.
- No portfolio-level macro/news reuse for per-stock runs.

**Current behavior on main**
- Basic query cache exists but duplication remains high in multi-dimension per-stock flow.

**Remaining gap**
- Missing tiered depth strategy, dimension dedupe, and portfolio-session reuse.

**Minimal next fix**
- Respect `max_searches` by slicing dimensions.
- Add same-day `(ticker, date)` cache for comprehensive intel and URL/source dedupe across dimensions.
- Reuse portfolio-level macro context for all stocks in one run.

---

## 8) Disabled module / unavailable feature rendering
**Status:** partially fixed.

**Evidence**
- Pipeline forcibly disables chip distribution at init (`self.config.enable_chip_distribution = False`).
- Chip data is only injected when available; dashboard chip section is rendered only if chip structure exists.
- Core prompt still includes chip-health oriented guidance/checklist language, so AI can emit confident chip conclusions despite disabled upstream module in some cases.

**Current behavior on main**
- Render layer generally avoids explicit chip section when data missing.
- Upstream prompt intent can still encourage confident chip-related narratives.

**Remaining gap**
- No hard guard ensuring disabled/unavailable modules produce N/A/hidden commentary everywhere.

**Minimal next fix**
- Pass explicit availability flags (e.g., `chip_data_available=false`) to analyzer and enforce parser/renderer guardrails that replace confident module conclusions with N/A when unavailable.

