# PS Scanner Quant v6.8.1 — Performance / Evidence-Fabric Reliability Audit

## Production symptom

The v6.8.0 Mac install passed 260 local regressions, started normally and connected to Groww, but post-install validation timed out on `/api/performance?group_by=book&limit=1000`.

## Performance-path audit

`/api/performance` has no broker or internet call. The latency defect was local analytics work.

The pre-fix query was:

```sql
SELECT *
FROM recommendations
WHERE state='CLOSED'
ORDER BY COALESCE(closed_at,updated_at,created_at) ASC
LIMIT ?
```

The schema had no index beginning with `state` and the close-time expression. The request also loaded and decoded heavy rationale, feature and audit JSON that book-level aggregation never reads. The endpoint used the default 10-second DB timeout and had no progress handler.

v6.8.1 adds matching expression indexes, grouping-specific projections, one connection/snapshot, short passive lock waiting, and a 2.5-second request budget with explicit degraded telemetry.

## v6.8 evidence-fabric spot audit

The v6.8 producer/consumer design remains intact:

- ETF, Global→India and ordinary scanner feature reads use cached history / cached evidence context.
- live-book repricing uses cached prices rather than initiating its own LTP transport.
- institutional HTTP is owned by its dedicated producer.
- news/fundamental/event modules still contain producer-side network refresh functions; scanners consume their persisted/cached outputs.
- Circuit retains its deliberate evidence-triggered exact Groww quote for plausible candidates, consistent with the Circuit contract.
- International retains one shared bounded batched Yahoo transport reused across weekly selection and live repricing freshness windows.

No network path was found from performance analytics. No process-wide DB lock is introduced. WAL/NORMAL and short-lived connection policy remain unchanged.

## Contention policy

Passive performance analytics may not wait indefinitely behind SQLite work. If the bounded snapshot cannot finish, the API says so explicitly instead of returning partial statistics. Deep/learning analytics remain outside this passive budget so correctness is not traded for latency.

## Validator contract

The validator now checks a lightweight 200-row performance call and asserts:

- `complete=true`;
- passive mode;
- no network calls;
- bounded query budget;
- exactly one SQLite snapshot connection;
- VOID exclusion policy remains present.

The separate 1,000-row diagnostic remains available for production verification after upgrade.
