# PS Scanner Quant v6.6.0 — Current-Period Lifecycle & Statistical Audit

v6.6.0 is the first structural cleanup release after the v6.5.1 hotfix sequence. It redefines the scanner around explicit page/book lifecycle contracts instead of allowing historical display behavior, recovery rules and strategy-vote assumptions to emerge independently in each module.

## Highlights

- Current-period-only default payloads and UI for Intraday, Weekly, Monthly, ETF, Circuit and International.
- Explicit Performance & History page/API; historical records remain in the immutable learning ledger.
- Central page/book contract API at `/api/lifecycle`.
- Strategy-family diversity moved to advisory/shadow mode until its incremental out-of-sample value is demonstrated.
- Intraday's duplicated hidden 72/76 score gate collapsed to one visible threshold: the effective 76 threshold is unchanged and now appears in rejection telemetry.
- Structured funnel and near-miss diagnostics.
- Database-level Weekly/Monthly live-symbol exclusivity triggers.
- Deterministic session rollover for stale Intraday/Circuit live identities.
- Bounded missed-freeze recovery without stale overnight publication.
- Wilson confidence intervals and VOID-separated performance/learning.
- Rich worker progress/hung/restart telemetry and bounded health/sanity snapshots.
- Dedicated Linux/macOS PS Scanner CI plus installable ZIP artifact and post-install validator.

## Upgrade safety

The installer remains an in-place v6 upgrade. It preserves `data/`, credentials, settings, the recommendation ledger, strategy state, feature/history caches and logs. Existing historical rows are not deleted merely because they no longer appear on the active page.

The release does **not** loosen Groww budget controls, freshness guards, liquidity requirements, target/risk geometry, order-execution permissions, or stop-risk controls. A target count of five remains a target rather than a quota.

## Validation

The v6.6.0 regression suite adds direct temporary-SQLite tests for current-period/history separation, database-enforced Weekly/Monthly exclusivity, VOID performance semantics, Wilson uncertainty, advisory strategy diversity, single Intraday score-gate accounting, rollover recovery and worker telemetry. GitHub Actions validates both Ubuntu and macOS before packaging.
