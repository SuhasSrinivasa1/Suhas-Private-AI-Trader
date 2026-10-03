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

The first v6.8.1 production candidate exposed a second-order SQLite storage cost: although the SELECT was narrow, the chronology index was not covering. Ordinary performance statistics still had to revisit full recommendation table rows, and needed scalar columns such as created/updated/closed timestamps and result occur after large JSON payload fields in the record layout. On the preserved production ledger, those row visits exhausted the 2.5-second passive budget.

## Real-Mac follow-up

After the covering-index candidate was installed on the preserved production ledger,
`group_by=book&limit=1000` completed successfully with `status=COMPLETE`,
`selected_index=idx_recs_state_closed_perf_cover`, and about 32.7 ms internal elapsed time.

The same fresh runtime audit exposed three independent producer/health reliability issues:
- the news producer called `set_state()` without importing it;
- Global→India recomputed the same two book-level calibration values inside the full-NSE
  symbol loop, opening SQLite twice per stock and stretching a cycle beyond its 600-second watchdog;
- passive health/sanity called the detailed worker-status path, opening an extra SQLite
  connection even though health advertised a one-connection passive snapshot;
- low-priority maintenance's 360-second watchdog was shorter than the transport envelope
  of its existing paced multi-request history hydration batch.

## Fix

v6.8.1:
- adds CLOSED chronology expression indexes plus compact covering indexes for global and per-book passive analytics;
- projects only columns required by the requested grouping;
- forces ordinary non-JSON performance modes onto the covering index so SQLite does not revisit large recommendation rows merely to reach scalar columns stored after audit/evidence JSON payloads;
- reuses one SQLite snapshot for family metadata when needed;
- gives the passive API a 0.5-second SQLite busy timeout and 2.5-second SQL/CPU wall-clock budget;
- uses SQLite's progress handler and explicit Python deadline checks;
- returns `DEGRADED_BOUNDED` with `complete=false` and no partial groups if the request cannot finish inside the budget;
- leaves unbounded internal learning analytics unchanged so evidence is not silently discarded;
- leaves the validator timeout at 6 seconds and requires a complete bounded performance response;
- imports the missing news telemetry state writer;
- reads Global→India LONG/SHORT calibration once per cycle with identical scoring semantics;
- gives health/sanity a DB-free in-memory worker-liveness snapshot while preserving detailed /api/workers telemetry;
- aligns only the low-priority maintenance watchdog with its existing paced history-transport workload; scanner cadences are unchanged.

## Regression coverage

`tests/test_v681_performance_reliability.py` verifies:
- the CLOSED chronology query uses `idx_recs_state_closed_perf_cover` as a SQLite COVERING INDEX;
- book analytics do not decode large JSON evidence columns;
- busy/aborted bounded reads return explicit degraded telemetry with no partial statistics;
- internal learning does not silently degrade;
- the API route uses the short passive budget;
- news producer telemetry has its state writer;
- Global→India calibration is outside the symbol loop;
- passive health/sanity worker status is DB-free while /api/workers remains detailed;
- maintenance watchdog telemetry reflects the existing paced batch envelope.

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


## Production Mac validation — 2026-10-03

The final v6.8.1 installable artifact was validated on the preserved production Mac installation.

Observed results:
- archive integrity check passed and the v6.8.1 installer completed in upgrade mode;
- existing v6 runtime data, credentials, settings, recommendation ledger, and strategy state were preserved;
- Groww authentication remained connected after installation;
- the local regression suite completed successfully: 269 tests passed;
- post-install validation returned `ok=true`, `version=6.8.1`, lifecycle `V680_SHARED_EVIDENCE_FABRIC_ADAPTIVE_ALGORITHM`, runtime database check `ok`, deep backup/restore verification `ok`, and 25 workers;
- the bounded performance validation scanned 196 CLOSED rows and completed in about 6.3 ms internally;
- a direct request to `/api/performance?group_by=book&limit=1000` returned `status=COMPLETE`, `complete=true`, used `idx_recs_state_closed_perf_cover`, and completed in about 11 ms internally, well inside the unchanged 6-second HTTP validation budget.

Execution readiness remained correctly fail-closed during this validation because the cached Static-IP observation was unavailable, the NSE market was closed, and the daily order count was unavailable. This did not block research/analytics validation and is consistent with the execution-only Static-IP contract.

The validator also reported frozen-book recovery shortages for Monthly, ETF, and International. These remain explicit recovery states; no recommendation quota was fabricated and no frozen identity was replaced.

The installation emitted an urllib3 warning because the existing Python 3.9 runtime is linked against Apple LibreSSL 2.8.3 while urllib3 v2 prefers OpenSSL 1.1.1+. Groww connectivity, tests, and validation all succeeded, so no dependency-policy change is included in v6.8.1. A future runtime-baseline upgrade can move the Mac installation to a modern OpenSSL-backed Python without changing this release's trading semantics.
