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


def get(path, *, timeout=6.0, attempts=4):
    last=None
    for attempt in range(max(1,int(attempts))):
        try:
            with urllib.request.urlopen(BASE+path,timeout=float(timeout)) as r:
                return json.load(r)
        except Exception as exc:
            last=exc
            if attempt+1 < attempts:
                time.sleep(0.5*(attempt+1))
    fail(f"GET {path} failed after {attempts} attempts: {last}")


ping=get("/api/ping",timeout=2,attempts=3)
if ping.get("version")!="6.7.1":fail("runtime version is not 6.7.1")

health_started=time.monotonic()
health=get("/api/health",timeout=3,attempts=4)
health_elapsed=time.monotonic()-health_started
if health.get("engine_alive") is not True:fail("engine supervisor is not alive")
contract=health.get("health_contract") or {}
if contract.get("network_calls") is not False:fail("health endpoint is not passive/network-free")
if contract.get("history_pacer_nonblocking") is not True:fail("health endpoint may wait behind history pacer")
if health_elapsed>12:fail(f"health endpoint retries exceeded bounded validation budget: {health_elapsed:.1f}s")

life=get("/api/lifecycle",timeout=4)
if life.get("policy_version")!="V671_NONBLOCKING_HEALTH_AND_VALIDATION":fail("lifecycle contract is not v6.7.1")

sanity=get("/api/sanity",timeout=6)
if sanity.get("database_quick_check")!="ok":fail("SQLite quick_check failed")
if sanity.get("weekly_monthly_collisions"):fail("Weekly/Monthly overlapping frozen-period identity collision detected")
if sanity.get("old_intraday_live_rows"):fail("old Intraday LIVE rows remain")
if sanity.get("old_circuit_live_rows"):fail("old Circuit LIVE rows remain")
if sanity.get("dead_workers"):fail("dead workers: "+",".join(sanity["dead_workers"]))
if sanity.get("hung_workers"):fail("hung workers: "+",".join(sanity["hung_workers"]))

for book in ("INTRADAY","WEEKLY","MONTHLY","ETF","CIRCUIT","CIRCUIT_NEXTDAY","INTERNATIONAL"):
    data=get("/api/book/"+book,timeout=6)
    pk=str(data.get("period_key") or "")
    bad=[r for r in (data.get("closed") or []) if str(r.get("period_key") or "")!=pk]
    if bad:fail(f"{book} active payload leaked {len(bad)} historical-period CLOSED rows")

perf=get("/api/performance?group_by=book&limit=1000",timeout=6)
policy=perf.get("outcome_policy") or {}
if "excluded" not in str(policy.get("voids") or "").lower():fail("performance VOID exclusion policy missing")

diag=get("/api/diagnostics/no-trade?limit=4",timeout=6)
execution=get("/api/execution/analytics?limit=20",timeout=6)
backups=get("/api/maintenance/backups",timeout=6)

print(json.dumps({
    "ok":True,
    "version":ping.get("version"),
    "lifecycle":life.get("policy_version"),
    "database":sanity.get("database_quick_check"),
    "workers":len(health.get("workers") or {}),
    "health_elapsed_seconds":round(health_elapsed,3),
    "health_contract":contract,
    "performance_rows_scanned":perf.get("rows_scanned"),
    "diagnostic_books":len(diag.get("books") or {}),
    "execution_orders_scanned":execution.get("orders_scanned"),
    "backup_policy":backups.get("policy"),
    "frozen_book_shortages":sanity.get("frozen_book_shortages") or {},
},indent=2))
