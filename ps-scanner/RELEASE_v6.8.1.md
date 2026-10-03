# PS Scanner Quant v6.8.1 — Bounded Performance Analytics Reliability

## Scope

v6.8.1 is a narrow reliability patch for the production Mac failure:

```
FAIL: GET /api/performance?group_by=book&limit=1000 failed after 4 attempts: timed out
```

The application, engine supervisor and Groww connection were alive. This release does not reinterpret that endpoint timeout as a general scanner or broker failure.

## Root cause

The performance endpoint was passive with respect to the network, but its SQLite path was not passive/bounded:

- it used the normal 10-second SQLite timeout;
- it selected every recommendation column, including large point-in-time JSON envelopes;
- it filtered `state='CLOSED'` and ordered by `COALESCE(closed_at,updated_at,created_at)` without an index matching that access path;
- SQLite therefore could scan/sort a large closed ledger before the 1,000-row limit helped;
- every returned row was JSON-decoded even when `group_by=book` did not need those JSON fields;
- the family grouping opened a second SQLite connection for the strategy-family map;
- no SQL progress handler or wall-clock budget existed.

That design could exceed the validator's six-second HTTP timeout on the production Mac.

## Fix

- Add `idx_recs_state_closed_time` and `idx_recs_book_state_closed_time`.
- Project only the fields needed by each performance grouping.
- Keep family mapping inside the same SQLite snapshot.
- Passive HTTP performance calls use a 2.5-second wall-clock/SQL budget and 0.25-second SQLite busy timeout.
- If the passive budget cannot be met, return explicit `DEGRADED` telemetry with `total=null` and no fabricated group rows.
- Background learning continues to call the unbounded analytics path so evidence is never silently discarded.
- Post-install validation uses a bounded 200-row contract and verifies passive/network-free/single-snapshot telemetry.

## Preserved contracts

v6.8.1 does not change scanner cadence, strategy promotion gates, target/stop logic, Static-IP execution-only scope, broker-position fail-closed behavior, ₹20,000 maximum notional, ₹500 stop-risk cap, 1.5 minimum reward/risk, frozen Weekly/Monthly identity, full-NSE breadth, or the v6.8 shared-evidence architecture.

The lifecycle policy remains `V680_SHARED_EVIDENCE_FABRIC_ADAPTIVE_ALGORITHM`; the new reliability capability is additive.
