# Architecture Audit v6.8.2 — clean public baseline

## Scope

This audit rechecks the final PS Scanner architecture after the v6.8.1 production Mac validation and before migration into a dedicated public repository.

## Confirmed fixed production defects

1. Passive health no longer waits on the history pacer.
2. Runtime sanity no longer performs deep SQLite quick_check inline; deep verification uses backup/restore.
3. Health/execution readiness uses cached broker/static-IP state and bounded database access.
4. Shared evidence producers own external observations; scanner consumers remain cache-first and independently scheduled.
5. Passive performance analytics uses a bounded wall-clock contract, narrow projection, and covering CLOSED-row indexes.
6. The production /api/performance regression was validated on the real ledger with a complete response in milliseconds.
7. News state publication, Global->India calibration reuse, passive worker status, and maintenance watchdog alignment from v6.8.1 remain present.
8. v6.8.2 adds time-leading decision and day/state order indexes and prioritizes execution-critical fields inside the bounded health snapshot.

## Static IP finding

No defect is assigned to Static IP. The production validation showed it unavailable because it was intentionally not configured. The application correctly treated this as an execution blocker only. Research, scanning, evidence collection, performance analytics, and learning must not depend on Static IP.

## Frozen-book shortages

Monthly/ETF/International shortages observed during validation remain explicit recovery states. The system must not create names, replace frozen identities, or loosen evidence gates merely to reach five recommendations.

## Runtime compatibility

The production Mac used Python 3.9 linked to LibreSSL 2.8.3, producing a non-fatal urllib3 v2 warning. v6.8.2 prefers a modern installed Python for the disposable virtual environment and keeps a compatibility dependency marker for legacy Python. It does not auto-install Homebrew/Python and does not mutate system Python.

## Public-repository boundary

The dedicated public repository should contain source, tests, documentation, and CI only. It must not contain:
- Groww credentials/tokens/TOTP secrets;
- runtime SQLite databases or backups;
- logs;
- cached broker responses;
- local.runtime.json;
- .env files;
- generated release signing material;
- machine-specific private state.

## Release conclusion

No recommendation-selection, target, stop, risk, execution-permission, frozen-book, evidence, or learning threshold is loosened in v6.8.2. The release is reliability hardening plus clean-repository preparation.
