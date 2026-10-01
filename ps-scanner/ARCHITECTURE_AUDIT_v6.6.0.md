# PS Scanner v6.6.0 Architecture Audit

This document records the first-principles page/domain audit performed from the v6.5.1 `main` baseline. It describes the code that exists in the repository, not an assumed product taxonomy.

## Page/domain matrix

| UI page | Book(s) | Worker | Scan / update path | Main DB tables | API | Active period / default UI | Freeze / expiry | Recovery / learning |
|---|---|---|---|---|---|---|---|---|
| Intraday | `INTRADAY` | `intraday` + `live_update` | `engine.run_intraday_cycle -> scan_equities`; `update_live_books` | `recommendations`, `trade_decisions` | `/api/book/INTRADAY` | NSE session date; LIVE + CLOSED for today only | publication during live entry window; unresolved SHORT ends by 15:00; unresolved LONG is resolved at session end/rollover | zero-live rotating cached-ready bootstrap, then full breadth; historical CLOSED rows remain learning/performance evidence |
| Weekly | `WEEKLY` | `weekly` | `run_single_horizon_cycle('WEEKLY')` | `recommendations`, `candidate_observations`, `trade_decisions` | `/api/book/WEEKLY` | current relevant NSE week only | frozen identity; preferred 09:00–09:12 IST, normal recovery to 15:25 | deterministic staged current-period recovery; after 15:25 recovery is bounded to market hours; target 5, never a quota |
| Monthly | `MONTHLY` | `monthly` | `run_single_horizon_cycle('MONTHLY')` | same as Weekly | `/api/book/MONTHLY` | current relevant month only | prefer pre-month; frozen identity | staged recovery while horizon remains defensible; an effectively expired current month is not reconstructed with hindsight |
| ETF | `ETF` | `etf` | `specialized.run_etf_cycle -> scan_etfs` | `recommendations`, `candidate_observations` | `/api/book/ETF` | current relevant NSE week only | weekly frozen ETF book | cached-first missed-freeze recovery; no stale fallback or gate relaxation |
| Circuit Radar | `CIRCUIT`, `CIRCUIT_NEXTDAY` | `circuit`, `circuit_nextday`, `live_update` | `specialized.run_circuit_cycle`, `run_circuit_nextday_cycle` | `recommendations` | `/api/circuit/board` | same-day lane shows today only; next-day lane shows current target session | same-day expires 15:00; next-day book freezes around 15:00 for target session | old same-day LIVE rows resolve on rollover; historical WIN/LOSS/MISS retained; VOID separated from P/L |
| International | `INTERNATIONAL`, `GLOBAL_INDIA_LONG`, `GLOBAL_INDIA_SHORT` | `international`, `global_india`, `live_update` | `specialized.run_international_cycle`; `cross_market.run_global_india_cycle` | `recommendations` | `/api/international/board` | US lane: current relevant weekly frozen book; Global→India: current/next target NSE session | US weekly frozen; Global→India next-session identity | external US history transport is subprocess-bounded with whole-call budget and partial success; stale substitution forbidden |
| Strategy Lab | no production book | `strategy` | `strategy_lab.maybe_weekly_jobs`, shadow open/resolve, validation/decay | `strategies`, `strategy_stats`, `shadow_signals`, recommendation ledger | `/api/strategy-lab` | research state, not a trade slate | daily evidence/decay/validation plus weekly discovery/deep validation | Champion/Challenger promotion remains evidence-gated; Wilson intervals added; VOID excluded from trading evidence |
| Regime | context | `market_snapshot` | `regime.classify` | `system_state` | `/api/regime` | current context | refreshed from current cached breadth | historical recommendation rows retain their recorded regime |
| Trade Intelligence | audit | scanner workers | `trade_intelligence.evaluate` + decision journal | `trade_decisions` | `/api/trade-decisions` | recent decision evidence | candidate-time decision | rejected candidates remain diagnosable; family diversity no longer acts as an unvalidated publication veto |
| Performance & History | all books | no signal worker | `analytics.performance`, `analytics.history_rows` | `recommendations`, `strategies` | `/api/performance`, `/api/history/recommendations` | historical by definition | n/a | explicit home for older outcomes; VOID/data errors remain visible but excluded from trading P/L |
| Portfolio & Risk | broker state | broker/reconcile paths | order/risk modules | order/fill tables | `/api/portfolio`, `/api/orders` | current broker/risk state | n/a | never a signal generator |
| Health | operations | supervisor + all workers | cached worker/system state | `system_state`, `health_events` | `/api/health`, `/api/sanity` | current operational state | n/a | bounded DB snapshots; no provider call in sanity |
| Settings | configuration | n/a | config layer | settings JSON/runtime state | `/api/settings` | current config | n/a | Static IP remains order-execution-only |

There is no separate Daily/Tomorrow UI page in this repository. The current next-session concepts are Circuit Next Day and Global→India lanes.

## Structural inconsistencies found in v6.5.1

1. **Historical rows were mixed into active pages.** Only Intraday had a current-day closed filter. Weekly, Monthly, ETF and specialized books returned up to 100 historical CLOSED rows in their normal active payload.
2. **Strategy-family diversity was an unvalidated production veto twice.** `scan_equities` required two distinct families, and Trade Intelligence filter 50 separately required two strategy IDs for Intraday/Weekly/Monthly. This could eliminate otherwise valid candidates before or during the production decision without evidence that diversity improved out-of-sample expectancy.
3. **Intraday had a hidden duplicate score gate.** The scan accepted candidates at score 72, then `run_intraday_cycle` silently refused publication below 76. The effective threshold was therefore 76, but 72–75.99 candidates were misreported as eligible rather than score rejects.
4. **Same-session lifecycle cleanup was incomplete.** Intraday LONG and same-day Circuit identities could remain LIVE after a missed close/restart path.
5. **Weekly/Monthly uniqueness depended primarily on application code.** The application used `BEGIN IMMEDIATE`, but the database itself had no invariant preventing a future alternate write path from creating a live symbol collision.
6. **Learning decay could ingest VOID rows.** Strategy-decay evidence selected all CLOSED recommendations instead of restricting trading evidence to genuine WIN/LOSS/MISS outcomes.
7. **Performance was not a first-class surface.** The active UI became the accidental history view, and statistical uncertainty was not exposed.
8. **Worker status was too shallow.** It reported thread liveness but not elapsed runtime, timeout/hung state, progress, funnel counts, recovery state or restart count.
9. **Health aggregation performed repeated state reads.** The API had no bounded bulk snapshot helper even though worker status is operationally latency-sensitive.
10. **The repository had no dedicated PS Scanner CI.** Existing repository CI did not run this application's regression suite on a clean environment.

## v6.6.0 corrections

- Active book payloads now return LIVE and CLOSED rows for the same active `period_key` only. History remains immutable in SQLite and is exposed explicitly through History/Performance.
- A central `lifecycle.py` defines the page/book contract and `/api/lifecycle` exposes it.
- Family diversity is now **shadow/advisory metadata**. At least one audited strategy is still required; suspended strategies still fail. Diversity contributes neither a hard veto nor a production score penalty until validated out of sample.
- The effective Intraday score threshold remains 76; it is now applied exactly once in the candidate funnel so every score rejection is counted.
- Candidate telemetry exposes universe/history/score/target/risk/intelligence counts and bounded strongest near misses with stage, reason and threshold distance.
- Intraday and same-day Circuit have deterministic session rollover closure paths. Historical rows stop masquerading as LIVE.
- SQLite triggers enforce live Weekly/Monthly symbol mutual exclusion on INSERT and UPDATE, defense-in-depth behind the application transaction.
- Missed-freeze horizon recovery is deterministic but bounded to market hours after the normal 15:25 window; no overnight publication from stale closing data is introduced.
- International transport remains killable subprocess-based, budgeted and partial-success; no stale fallback was added.
- Performance separates WIN/LOSS/MISS from VOID and reports sample size, Wilson 95% win-rate interval/width, expectancy, return statistics, profit factor when mathematically defined, average R and descriptive drawdown.
- Daily learning records ledger evidence by book, and decay no longer treats VOID/data-integrity events as strategy losses.
- `/api/sanity` checks DB integrity, Weekly/Monthly collisions, historical-session LIVE leakage, missing trade levels, duplicate live identities, stale current-session rows, dead/hung workers, overdue daily validation and frozen-book shortages.
- Worker telemetry now includes state, start/last-ok, elapsed/duration, timeout/hung flag, current stage, processed/remaining, rejection funnel, recovery state and watchdog restart count.
- A dedicated Ubuntu/macOS CI workflow compiles Python, initializes a clean database, runs the full regression suite, parses UI JavaScript, checks zsh syntax, and builds the installable ZIP only after tests pass.

## Safety invariants intentionally unchanged

- No recommendation is fabricated to satisfy a count target.
- Groww budget/notional and risk-to-stop controls are unchanged.
- Freshness, liquidity, data-quality, execution permission and risk gates remain fail-closed.
- Static IP remains an order-execution gate only, not a research-publication gate.
- No stale market-data fallback was added.
- Frozen identities are not replaced to improve reported performance.
- VOID/data-error events remain auditable rather than being hidden or counted as wins.
- No backtest leakage, future information, or hindsight reconstruction was introduced.

## What v6.6.0 can and cannot prove

The source audit can prove which software gates and lifecycle defects existed. It cannot prove whether a particular live trading day genuinely contained only two valid opportunities because the private runtime market-data cache and recommendation database are intentionally not committed. After installation, the new funnel, near-miss, sanity and performance APIs provide the evidence needed to distinguish **NO OPPORTUNITY** from **SOFTWARE FAILED TO FIND OPPORTUNITY** without weakening hard safety gates.
