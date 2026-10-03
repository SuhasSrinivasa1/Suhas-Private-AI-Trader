# PS Scanner v6.8.1 Architecture Audit

## Scope

This audit was performed while diagnosing the production `/api/performance` timeout. It rechecked the v6.8 shared-evidence architecture for scanner-side network calls, duplicate transport, producer freshness/dependencies, SQLite contention and analytics contention.

## Performance analytics finding

The concrete v6.8.0 reliability defect was in passive analytics, not the evidence fabric. `/api/performance` used the general 10-second SQLite timeout and a wide, unindexed CLOSED recommendation query. On a grown ledger, the route could wait, scan/sort and decode enough data to exceed the post-install validator's 6-second HTTP budget.

v6.8.1 aligns performance with the bounded health/sanity philosophy:
- one WAL read snapshot;
- 0.5-second busy timeout;
- 2.5-second end-to-end SQL/CPU budget;
- SQLite progress interruption;
- narrow projection by grouping;
- CLOSED chronology expression indexes;
- explicit degraded telemetry instead of a hung request or fabricated partial statistics.

Internal learning keeps the complete analytics path and is not forced through the passive budget.

## Evidence-fabric re-audit

### Cache-only scanner consumers

Intraday, Weekly and Monthly scanning read live prices with `allow_network=False` and histories with `allow_network=False`. Live recommendation maintenance also reads the shared priority-quote cache. ETF and Global→India use cached prices/history in their scanner paths. Sector breadth uses cached daily history.

### Shared producers

Independent worker threads own:
- full-market Groww LTP;
- priority Groww LTP;
- instrument/universe refresh and history warmers;
- global/cross-asset context;
- fundamentals;
- priority news;
- prospective events;
- institutional observations;
- algorithm snapshot refresh.

The scheduler remains watchdog-supervised by domain. A slow producer is not serialized into the scanner workers.

### International transport

International daily/intraday history uses the shared bounded batch helper and is reused by weekly selection and lifecycle repricing within freshness windows. No duplicate scanner-side yfinance transport was found in those consumers.

### Circuit exception is intentional

Circuit performs full-market coarse screening from cached LTP, then calls exact Groww quote only for shortlisted evidence-triggered candidates. That is the existing Circuit contract; it is not a return to full-universe per-symbol broker fetching.

### SQLite concurrency

The release preserves:
- WAL;
- `synchronous=NORMAL`;
- short-lived independent connections;
- no process-wide Python database lock;
- external/network work outside performance reads.

The new performance indexes reduce scan/sort pressure without changing recommendation data or write semantics.

## No release-scope changes

No scanner frequency, scoring threshold, target/stop rule, strategy promotion gate, horizon side policy, execution permission, risk cap or evidence freshness rule was changed. Warm-up states such as unavailable fundamentals/events or incomplete breadth immediately after restart remain telemetry states to be distinguished from defects rather than fabricated into READY values.
