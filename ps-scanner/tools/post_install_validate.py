#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import time
import urllib.request

BASE="http://127.0.0.1:8765"


def fail(message):
    print("FAIL:",message,file=sys.stderr)
    raise SystemExit(1)


def request_json(path, *, method="GET", timeout=6.0, attempts=4):
    last=None
    for attempt in range(max(1,int(attempts))):
        try:
            req=urllib.request.Request(BASE+path,method=method)
            with urllib.request.urlopen(req,timeout=float(timeout)) as r:
                return json.load(r)
        except Exception as exc:
            last=exc
            if attempt+1 < attempts:
                time.sleep(0.5*(attempt+1))
    fail(f"{method} {path} failed after {attempts} attempts: {last}")


def get(path, *, timeout=6.0, attempts=4):
    return request_json(path,timeout=timeout,attempts=attempts)


ping=get("/api/ping",timeout=2,attempts=3)
if ping.get("version")!="6.8.2":fail("runtime version is not 6.8.2")

health_started=time.monotonic()
health=get("/api/health",timeout=3,attempts=4)
health_elapsed=time.monotonic()-health_started
if health.get("engine_alive") is not True:fail("engine supervisor is not alive")
contract=health.get("health_contract") or {}
if contract.get("network_calls") is not False:fail("health endpoint is not passive/network-free")
if contract.get("history_pacer_nonblocking") is not True:fail("health endpoint may wait behind history pacer")
if health_elapsed>8:fail(f"health endpoint retries exceeded bounded validation budget: {health_elapsed:.1f}s")

life=get("/api/lifecycle",timeout=4)
if life.get("policy_version")!="V680_SHARED_EVIDENCE_FABRIC_ADAPTIVE_ALGORITHM":fail("lifecycle contract is not v6.8.0")

fabric=get("/api/evidence/fabric",timeout=4)
if fabric.get("policy")!="V680_ONE_OBSERVATION_MANY_CONSUMERS":fail("shared evidence fabric policy missing")
if fabric.get("mode")!="SHARED_PRODUCERS_CACHE_ONLY_CONSUMERS":fail("scanner evidence fabric is not producer/consumer mode")
algorithm=get("/api/algorithm",timeout=6)
if algorithm.get("policy")!="V680_ADAPTIVE_EVIDENCE_GATED_TRADING_ALGORITHM":fail("adaptive algorithm policy missing")
target=algorithm.get("accuracy_target") or {}
if abs(float(target.get("target") or 0)-0.80)>1e-9:fail("algorithm 80% evidence target missing")
if target.get("guaranteed") is not False:fail("algorithm must never represent the 80% target as guaranteed")

sanity_started=time.monotonic()
sanity=get("/api/sanity",timeout=4,attempts=4)
sanity_elapsed=time.monotonic()-sanity_started
sanity_contract=sanity.get("sanity_contract") or {}
if sanity_contract.get("deep_quick_check_inline") is not False:fail("sanity endpoint still performs deep quick_check inline")
if sanity_elapsed>16:fail(f"sanity endpoint retries exceeded bounded validation budget: {sanity_elapsed:.1f}s")
if sanity.get("database_runtime_checks_complete") is not True:
    fail("bounded runtime database sanity checks did not complete: "+str(sanity.get("database_runtime_error") or sanity.get("database_runtime_check")))
if sanity.get("weekly_monthly_collisions"):fail("Weekly/Monthly overlapping frozen-period identity collision detected")
if sanity.get("old_intraday_live_rows"):fail("old Intraday LIVE rows remain")
if sanity.get("old_circuit_live_rows"):fail("old Circuit LIVE rows remain")
if sanity.get("dead_workers"):fail("dead workers: "+",".join(sanity["dead_workers"]))
if sanity.get("hung_workers"):fail("hung workers: "+",".join(sanity["hung_workers"]))

# Deep SQLite integrity is deliberately not part of /api/sanity. Reuse a verified
# backup if one exists; otherwise create + restore-verify one with an explicit long budget.
backups=get("/api/maintenance/backups",timeout=4)
deep=backups.get("last") or {}
if deep.get("restore_verified") is not True or str(deep.get("quick_check") or "").lower()!="ok":
    deep=request_json("/api/maintenance/backup-now",method="POST",timeout=120,attempts=1)
if deep.get("restore_verified") is not True:fail("SQLite backup restore verification failed")
if str(deep.get("quick_check") or "").lower()!="ok":fail("SQLite backup quick_check failed")

for book in ("INTRADAY","WEEKLY","MONTHLY","ETF","CIRCUIT","CIRCUIT_NEXTDAY","INTERNATIONAL"):
    data=get("/api/book/"+book,timeout=6)
    pk=str(data.get("period_key") or "")
    bad=[r for r in (data.get("closed") or []) if str(r.get("period_key") or "")!=pk]
    if bad:fail(f"{book} active payload leaked {len(bad)} historical-period CLOSED rows")

perf=get("/api/performance?group_by=book&limit=1000",timeout=6)
policy=perf.get("outcome_policy") or {}
perf_contract=perf.get("performance_contract") or {}
if "excluded" not in str(policy.get("voids") or "").lower():fail("performance VOID exclusion policy missing")
if perf_contract.get("passive_bounded") is not True:fail("performance endpoint is not using the bounded passive contract")
if perf_contract.get("network_calls") is not False:fail("performance endpoint must not make network calls")
if perf.get("complete") is not True:fail("performance endpoint returned degraded telemetry: "+str(perf.get("degraded_reason") or perf.get("status")))

diag=get("/api/diagnostics/no-trade?limit=4",timeout=6)
execution=get("/api/execution/analytics?limit=20",timeout=6)

print(json.dumps({
    "ok":True,
    "version":ping.get("version"),
    "lifecycle":life.get("policy_version"),
    "database_runtime":sanity.get("database_runtime_check"),
    "database_deep_quick_check":deep.get("quick_check"),
    "database_restore_verified":deep.get("restore_verified"),
    "workers":len(health.get("workers") or {}),
    "health_elapsed_seconds":round(health_elapsed,3),
    "sanity_elapsed_seconds":round(sanity_elapsed,3),
    "health_contract":contract,
    "sanity_contract":sanity_contract,
    "evidence_fabric_policy":fabric.get("policy"),
    "algorithm_version":algorithm.get("algorithm_version"),
    "algorithm_accuracy_target":target,
    "performance_rows_scanned":perf.get("rows_scanned"),
    "performance_contract":perf_contract,
    "diagnostic_books":len(diag.get("books") or {}),
    "execution_orders_scanned":execution.get("orders_scanned"),
    "backup_policy":backups.get("policy"),
    "frozen_book_shortages":sanity.get("frozen_book_shortages") or {},
},indent=2))
