# PS Scanner Quant v6.8.1 — Bounded Performance Analytics Reliability

## Production defect

The v6.8.0 Mac installation itself was healthy, but post-install validation timed out on:

```
GET /api/performance?group_by=book&limit=1000
```

The defect was isolated to passive historical analytics rather than scanner, broker, or application liveness.

## Root cause

`psscanner_quant/analytics.py::performance()` used the general `db()` connection contract, whose SQLite busy timeout is 10 seconds. The request selected `*` from CLOSED recommendations, ordered by `COALESCE(closed_at,updated_at,created_at)`, and only then applied the row limit. The schema had no index matching that state/order expression.

That combination allowed a grown production ledger to:
- scan/sort more CLOSED rows than the requested 1,000-result contract;
- wait behind SQLite activity longer than the validator's 6-second HTTP budget;
- read and JSON-decode strategy, rationale, feature-snapshot and audit-envelope payloads even for `group_by=book`, where they are not needed;
- continue Python grouping/statistics work without an end-to-end passive deadline.

No network/broker call was found in the performance route.

## Fix

v6.8.1:
- adds CLOSED chronology expression indexes for global and per-book analytics;
- projects only columns required by the requested grouping;
- reuses one SQLite snapshot for family metadata when needed;
- gives the passive API a 0.5-second SQLite busy timeout and 2.5-second SQL/CPU wall-clock budget;
- uses SQLite's progress handler and explicit Python deadline checks;
- returns `DEGRADED_BOUNDED` with `complete=false` and no partial groups if the request cannot finish inside the budget;
- leaves unbounded internal learning analytics unchanged so evidence is not silently discarded;
- leaves the validator timeout at 6 seconds and requires a complete bounded performance response.

## Regression coverage

`tests/test_v681_performance_reliability.py` verifies:
- the CLOSED chronology query uses `idx_recs_state_closed_order`;
- book analytics do not decode large JSON evidence columns;
- busy/aborted bounded reads return explicit degraded telemetry with no partial statistics;
- internal learning does not silently degrade;
- the API route uses the short passive budget.

## Safety / architecture impact

No recommendation or execution rule changes in this release. The following remain unchanged:
- FULL NSE BREADTH;
- scanner worker cadences;
- v6.8 one-observation/many-consumers evidence fabric;
- Static IP is execution-only;
- Groww broker position is execution source of truth and mismatches fail closed;
- ₹20,000 maximum manual notional;
- ₹500 maximum modeled stop risk;
- minimum 1.5 reward/risk;
- same-day Indian SHORT hard exit;
- frozen Weekly/Monthly identity and no quota fabrication;
- point-in-time replay and historical evidence integrity;
- WAL + NORMAL SQLite policy and no process-wide Python database lock.

The lifecycle/evidence policy identifiers remain v6.8 because v6.8.1 is additive reliability hardening, not a lifecycle migration.
