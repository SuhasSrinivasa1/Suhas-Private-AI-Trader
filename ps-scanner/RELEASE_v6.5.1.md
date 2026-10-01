# PS Scanner v6.5.1 Reliability Hotfix

This source snapshot contains the PS Scanner code through v6.5.1.

Included reliability work:
- Weekly/Monthly symbol-level publication isolation.
- ETF missed-freeze recovery without relaxing hard risk, freshness, or quality gates.
- International bounded recovery transport with a hard wall-clock escape.
- SQLite fail-soft worker protection and sanity diagnostics.
- `/api/sanity` coverage for DB integrity, worker liveness, learning status, horizon collisions, stale intraday rows, and frozen-book state.
- Intraday default-view hygiene for previous-session closed rows.

Runtime databases, credentials, logs, caches, patch backups, and virtual environments are intentionally excluded from source control.
