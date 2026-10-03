# PS Scanner Quant v6.8.2

v6.8.2 is a narrow production-reliability and clean-baseline release on top of the fully validated v6.8.1 performance fix.

## Production evidence carried forward

v6.8.1 was validated on the preserved production Mac:
- 269 local tests passed;
- post-install validation returned ok=true;
- Groww remained connected;
- runtime and restored-backup SQLite checks passed;
- /api/performance?group_by=book&limit=1000 returned COMPLETE over 196 CLOSED rows using idx_recs_state_closed_perf_cover in about 11 ms internally.

Static IP was intentionally not configured during that validation. Static IP remains an execution-only control and is not a research/scanner gate.

## Additional concrete defect

The bounded /api/health snapshot used one one-second SQLite budget, but it evaluated the 24-hour trade-decision aggregation before the daily manual-order count. The existing trade_decisions indexes were led by book or symbol, not ts. On a grown audit ledger, that historical scan could consume the passive health budget before the execution order-count query ran. Health would then truthfully return db_snapshot_error=interrupted but today_manual_orders=null, making the diagnostic execution snapshot less useful and potentially showing daily_order_count_unavailable.

This did not bypass safety: actual execution remains fail-closed and performs its own bounded order-count/position checks. v6.8.2 fixes the passive snapshot reliability without weakening those gates.

## Fixes

- adds idx_trade_decisions_ts_decision on (ts DESC, decision) for the 24-hour health aggregation;
- adds idx_orders_created_day_state on (substr(created_at,1,10), state) for the daily order-count contract;
- queries execution-critical order count and persisted reconciliation/system state before optional health telemetry;
- preserves one bounded SQLite snapshot and the existing one-second health wall-clock budget;
- exposes execution_snapshot_available in health_contract;
- adds the v6.8.2 INDEXED_EXECUTION_CRITICAL_HEALTH_SNAPSHOT telemetry contract;
- leaves Static IP execution-only and does not fabricate execution readiness;
- prefers Python 3.12/3.11/3.10 for fresh/rebuilt Mac virtual environments when already installed;
- rebuilds the disposable .venv during install/upgrade so a newer interpreter can replace an older runtime without mixing site-packages;
- on Python <3.10, pins urllib3 to the latest 1.26 line to remain compatible with Apple LibreSSL-based legacy Python runtimes.

## Regression coverage

tests/test_v682_health_snapshot_runtime.py verifies:
- runtime version 6.8.2;
- execution-critical health queries occur before optional trade-decision/fundamental telemetry;
- the recent decision query uses idx_trade_decisions_ts_decision;
- the daily order count uses idx_orders_created_day_state;
- installer runtime-Python selection and clean venv rebuild;
- the legacy-Python urllib3 compatibility marker.

All existing v6.8.1 performance, evidence-fabric, execution-integrity, frozen-book, point-in-time, database concurrency, and risk tests remain part of the suite.

## Safety / audit invariants unchanged

- FULL NSE BREADTH;
- V680 one-observation/many-consumers evidence fabric;
- no synchronous network calls from passive health/performance endpoints;
- WAL + NORMAL SQLite and no process-wide DB lock;
- Static IP is order-execution only;
- Groww position reconciliation remains fail-closed;
- ₹20,000 maximum manual notional;
- ₹500 maximum modeled stop risk;
- minimum reward/risk 1.5;
- same-day Indian SHORT hard exit;
- frozen Weekly/Monthly identity;
- no rank replacement or quota fabrication;
- VOID/data-integrity rows are not counted as wins;
- point-in-time replay/evidence integrity;
- Champion/Challenger promotion remains evidence-gated;
- the 80% accuracy target remains a target, never a guarantee.

## Migration intent

v6.8.2 is also the clean source baseline intended for migration into a dedicated public PS Scanner repository. Runtime data, logs, credentials, broker secrets, SQLite ledgers, caches, and local machine state must remain outside Git.
