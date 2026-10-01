# PS Scanner v6.7.2 Architecture Audit

## Scope

v6.7.2 changes only runtime observability and post-install database verification. It preserves all v6.7.1 recommendation/execution behavior.

## Failure mode

A request handler that executes `PRAGMA quick_check` directly against a live preserved SQLite ledger has no reliable HTTP latency bound. SQLite `busy_timeout` limits lock waiting, not statement execution time. The same applies to sufficiently large aggregate/join queries.

Therefore a deep integrity check must not be part of a latency-sensitive health/sanity route.

## Runtime sanity contract

`GET /api/sanity` performs only bounded runtime integrity checks. The SQLite connection has a short busy timeout and a progress handler interrupts work after the configured wall-clock budget. The endpoint reports whether the runtime database checks completed.

It retains:
- Weekly/Monthly overlapping frozen-identity detection;
- old Intraday/Circuit LIVE row detection;
- LIVE rows missing entry/target/stop;
- duplicate LIVE identity detection;
- stale same-session LIVE rows;
- worker dead/hung/restart telemetry;
- learning-validation status;
- frozen-book shortage telemetry;
- execution-integrity cached state.

It does not run a deep SQLite quick-check.

## Deep integrity contract

Deep integrity uses the existing production-integrity backup path:

live SQLite database
→ SQLite online backup
→ isolated temporary restore
→ `PRAGMA quick_check`
→ required core-table verification
→ verified backup status persisted.

Post-install validation requires this contract to pass. If no verified backup is available, it explicitly starts one with a long maintenance timeout.

## Safety rationale

This design avoids two bad outcomes:
1. increasing API timeouts until runtime diagnostics appear healthy while remaining unbounded;
2. deleting the deep integrity check to make installation appear successful.

v6.7.2 keeps both guarantees: fast bounded runtime telemetry and a real deep corruption check.

## Trading invariants

No trading/research policy changes. Existing frozen identity, no-fabrication, full-NSE breadth, Static-IP execution-only, strategy validation, execution integrity and risk-cap contracts remain authoritative.
