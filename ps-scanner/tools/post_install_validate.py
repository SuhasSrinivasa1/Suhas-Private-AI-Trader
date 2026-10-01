#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import urllib.request

BASE="http://127.0.0.1:8765"


def get(path):
    with urllib.request.urlopen(BASE+path,timeout=5) as r:
        return json.load(r)


def fail(message):
    print("FAIL:",message,file=sys.stderr)
    raise SystemExit(1)


ping=get("/api/ping")
if ping.get("version")!="6.6.0":fail("runtime version is not 6.6.0")
health=get("/api/health")
if health.get("engine_alive") is not True:fail("engine supervisor is not alive")
life=get("/api/lifecycle")
if life.get("policy_version")!="V660_CURRENT_PERIOD_LIFECYCLE":fail("lifecycle contract is not v6.6.0")
sanity=get("/api/sanity")
if sanity.get("database_quick_check")!="ok":fail("SQLite quick_check failed")
if sanity.get("weekly_monthly_collisions"):fail("Weekly/Monthly live symbol collision detected")
if sanity.get("old_intraday_live_rows"):fail("old Intraday LIVE rows remain")
if sanity.get("old_circuit_live_rows"):fail("old Circuit LIVE rows remain")
if sanity.get("dead_workers"):fail("dead workers: "+",".join(sanity["dead_workers"]))
if sanity.get("hung_workers"):fail("hung workers: "+",".join(sanity["hung_workers"]))

for book in ("INTRADAY","WEEKLY","MONTHLY","ETF","CIRCUIT","CIRCUIT_NEXTDAY","INTERNATIONAL"):
    data=get("/api/book/"+book)
    pk=str(data.get("period_key") or "")
    bad=[r for r in (data.get("closed") or []) if str(r.get("period_key") or "")!=pk]
    if bad:fail(f"{book} active payload leaked {len(bad)} historical-period CLOSED rows")

perf=get("/api/performance?group_by=book&limit=1000")
policy=perf.get("outcome_policy") or {}
if "excluded" not in str(policy.get("voids") or "").lower():fail("performance VOID exclusion policy missing")

print(json.dumps({
    "ok":True,
    "version":ping.get("version"),
    "lifecycle":life.get("policy_version"),
    "database":sanity.get("database_quick_check"),
    "workers":len(health.get("workers") or {}),
    "performance_rows_scanned":perf.get("rows_scanned"),
    "frozen_book_shortages":sanity.get("frozen_book_shortages") or {},
},indent=2))
