# Changelog

This changelog summarizes behavior that is visible on current `main`, with emphasis on recently merged PRs.

## [Unreleased]

### Fixed
- **System config update race condition (PR #31):** `.env` optimistic-lock updates now perform compare-and-apply under the same lock path, reducing TOCTOU conflicts during concurrent writes.
- **Portfolio denominator fallback correctness (PR #28):** position-sizing calculations now avoid stale denominator contamination in pipeline fallback paths.
- **Snapshot/AI volume consistency guard NaN handling (PR #51):** notification-layer missing-metric detection now treats `NaN` forms (e.g., numeric `nan`, `\"nan\"`, `\"nan%\"`) as unavailable, ensuring volume commentary is downgraded when key snapshot fields are effectively missing.

### Changed
- **Deterministic quantity propagation (PR #30):** pipeline now propagates deterministic `target_quantity` into position-management results and downstream report/journal fields more consistently.
- **Manual workflow write discipline (PR #29):** `init-portfolio` and `record-trade` workflows execute within explicit portfolio write-lock + transaction boundaries aligned with core write paths.
- **Recommended-action semantics in reports (PR #27):** dashboard/recommendation presentation is aligned to deterministic action output, and AI narrative is treated as secondary commentary when conflicting.

### User-impacting behavior notes
- **Config API conflict behavior is stricter and more predictable:** stale `config_version` submissions continue returning conflict, but now with lower race-window risk.
- **Portfolio/account values shown in reports are more deterministic:** fallback logic and target quantity propagation reduce drift between suggested action text and accounting fields.

### Breaking / semantic changes
- **No API path removals detected in recent merged PRs (#27-#31).**
- **Semantic tightening:** recommendation display should be treated as deterministic-action-first; if users previously interpreted narrative text as primary action, behavior will look stricter now.
