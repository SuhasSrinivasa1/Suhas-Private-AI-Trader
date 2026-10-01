# PS Scanner Quant v6.7.1 — Nonblocking Health & Validation Reliability

v6.7.1 fixes the production observability/validation defect discovered after installing v6.7.0 on macOS. The running service answered `/api/ping` immediately, but `/api/health` could wait behind the history pacing lock and exceed both the validator's 5-second timeout and a manual 30-second curl timeout.

## Root cause

The history request pacer intentionally holds its process lock while sleeping through Groww request spacing/rate-limit cooldowns. The v6.7.0 health endpoint called the detailed history-control status synchronously, so a passive health request could queue behind that cooldown even though the scanner itself remained alive.

Several passive health subpaths also used ordinary SQLite helpers with the default 10-second timeout. Separately, the v6.7.0 post-install validator referenced `diag`, `execution`, and `backups` without assigning them; the health timeout masked that later failure.

## Fixes

- Added a nonblocking history-control telemetry path. If the history pacer is busy, health returns a truthful `PACER_BUSY_NONBLOCKING_SNAPSHOT` instead of waiting.
- Rebuilt `/api/health` around passive cached state and bounded SQLite reads only.
- Removed potentially network-backed universe status work from the health path.
- Fundamental/event health summaries use bounded database snapshots.
- Cached execution readiness uses bounded order-count and cached position-reconciliation reads.
- `/api/evidence/status` is now passive/nonblocking for the same lock-sensitive evidence paths.
- `/api/sanity` reuses its bounded state snapshot for execution-integrity telemetry.
- The validator uses bounded retries with endpoint-specific errors and now actually fetches diagnostics, execution analytics and backup status before printing them.
- Installer/version/package metadata updated to v6.7.1.

## Non-changes

No recommendation threshold, strategy score, liquidity/freshness gate, target feasibility rule, position/risk cap, short policy, horizon identity rule, learning promotion rule, or order-execution permission rule was loosened or changed.

## Validation contract

The regression suite now includes tests that hold the history pacer lock in a different thread and assert that cached history telemetry and `/api/health` return promptly. It also checks that cached execution readiness fails fast when its order-count DB read is unavailable, and that the validator initializes all v6.7 production-integrity checks.
