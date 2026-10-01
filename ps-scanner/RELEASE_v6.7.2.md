# PS Scanner Quant v6.7.2 — Bounded Runtime Sanity & Deep DB Verification

v6.7.2 fixes the second observability defect exposed by the production Mac upgrade.

## Observed failure

After v6.7.1 fixed `/api/health`, post-install validation advanced to `/api/sanity` and timed out. The scanner service remained responsive, but sanity still ran several ledger checks plus `PRAGMA quick_check` synchronously on the live SQLite database.

SQLite's connection/busy timeout only limits lock acquisition. It does not cap the wall-clock time of `PRAGMA quick_check` or a long query, so a preserved production ledger can exceed an HTTP request timeout without being corrupt.

## v6.7.2 behavior

### Fast runtime sanity
`/api/sanity` is now a runtime endpoint, not a deep maintenance job.

- short SQLite connection timeout;
- SQLite progress-handler deadline for runtime ledger checks;
- no broker/network calls;
- no inline `PRAGMA quick_check`;
- explicit `database_runtime_checks_complete` and degradation details;
- existing collision, stale-LIVE, duplicate identity, worker, lifecycle and frozen-book checks retained.

### Deep database integrity
Deep integrity is still mandatory for post-install validation.

The validator:
1. reads the latest verified backup status;
2. reuses it when its isolated restore already passed;
3. otherwise explicitly invokes `POST /api/maintenance/backup-now` with a 120-second maintenance budget;
4. requires `restore_verified=true`;
5. requires the restored backup's `PRAGMA quick_check` to equal `ok`.

This makes the expensive operation explicit and separates it from latency-sensitive runtime API health.

## Non-changes

No recommendation logic, publication threshold, liquidity/freshness gate, target feasibility rule, horizon identity rule, short policy, order execution permission, position reconciliation, notional/risk cap, learning rule, or Champion/Challenger rule changes in v6.7.2.
