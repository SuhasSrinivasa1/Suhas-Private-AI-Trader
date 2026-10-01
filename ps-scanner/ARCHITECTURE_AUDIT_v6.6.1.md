# PS Scanner v6.6.1 Architecture Audit

This is the first-principles follow-up audit of the repository's actual v6.6.0 implementation. Runtime market-data caches and the live SQLite ledger are intentionally not committed, so source inspection can prove software lifecycle behavior but cannot retrospectively prove how many valid setups existed on a particular live day.

## Page/domain matrix

| UI page | Book(s) | Worker | Scan/update path | Active period shown by default | Freeze / expiry | Recovery | Learning/history |
|---|---|---|---|---|---|---|---|
| Intraday | `INTRADAY` | `intraday`, `live_update` | `run_intraday_cycle -> scan_equities`; `update_live_books` | current NSE session only | identity immutable after publication; same-session expiry | rotating cached-ready zero-live pass, then normal full breadth; no gate relaxation | all valid CLOSED rows retained; older sessions only in Performance/History |
| Weekly | `WEEKLY` | `weekly` | `run_single_horizon_cycle('WEEKLY')` | current relevant NSE week | target five; frozen identity | pre-period preferred; deterministic market-hours recovery | outcomes remain learning evidence after week rolls |
| Monthly | `MONTHLY` | `monthly` | `run_single_horizon_cycle('MONTHLY')` | current relevant month | target five; frozen identity | no hindsight reconstruction of an effectively expired month | outcomes remain learning evidence |
| ETF | `ETF` | `etf` | `run_etf_cycle -> scan_etfs` | current relevant week | weekly frozen book | cached-first missed-freeze recovery only through NSE close | history/performance separate from active page |
| Circuit Radar | `CIRCUIT`, `CIRCUIT_NEXTDAY` | `circuit`, `circuit_nextday`, `live_update` | specialized circuit cycles | same-day today; forecast target session | same-day cutoff 15:00; next-day identity frozen | no same-day hindsight reconstruction | WIN/LOSS/MISS are trading evidence; VOID is separate |
| International | `INTERNATIONAL`, `GLOBAL_INDIA_LONG/SHORT` | `international`, `global_india` | bounded international batch history; cross-market cycle | U.S. current weekly book; current/next India forecast session | U.S. weekly frozen; India forecast-session identity | hard-bounded subprocess chunks and partial success; no stale substitution | historical resolved rows retained |
| Strategy Lab | research state | `strategy` | shadow resolve/run, daily validation, decay | current research state | no direct production slate | daily evidence + weekly discovery/deep validation | Champion/Challenger evidence, holdout, Wilson uncertainty, live shadow |
| Performance & History | all | analytics/API | `analytics.performance/history_rows` | historical by definition | n/a | n/a | explicit home for older outcomes |
| Health | all domains | supervisor | cached worker/system state, `/api/sanity` | current operational state | n/a | watchdog + fail-soft telemetry | sanity performs no provider call |

## Findings from re-inspecting v6.6.0

1. **Weekly/Monthly exclusion was state-based rather than frozen-identity-based.** The triggers and application conflict query considered only LIVE rows. A Weekly pick that closed early could therefore become eligible for an overlapping Monthly period, breaking frozen identity and performance independence.
2. **Intraday batch telemetry could overstate search completeness.** During zero-live bootstrap, `funnel.universe_total` was the current bounded batch, not the full NSE universe, and rejection counters were not accumulated across the rotating pass. A no-candidate batch could look like a market-level no-opportunity conclusion.
3. **ETF recovery was not actually market-hours bounded.** Its recovery predicate required a regular trading date and a time after the preferred window, but lacked the `<= MARKET_CLOSE` bound used by Weekly/Monthly.
4. **SQLite synchronous mode was not explicitly applied per connection.** WAL is persistent at database level, but `synchronous` is connection-scoped; the intended NORMAL policy is now reasserted on every independent connection.
5. **Outcome diagnostics needed explicit loss/miss rates and close-reason grouping.** These are now available without mixing VOID into trading P/L.

## v6.6.1 invariants

- A symbol cannot be a non-VOID Weekly and Monthly recommendation when the frozen calendar periods overlap, even if one identity has already closed.
- Frozen-book completion counts include early-closed valid identities, so target hits/losses do not cause replacement picks.
- Intraday reports `SEARCH_INCOMPLETE` while its deterministic cached-ready pass is still in progress. `NO_QUALIFIED_OPPORTUNITY_IN_CACHED_READY_UNIVERSE` requires a completed pass whose actually processed count covers that cached-ready set.
- `universe_total` is full breadth; bounded scans separately expose their scope and processed count.
- ETF current-week missed-freeze recovery stops at NSE close and resumes safely on a later valid session rather than publishing after hours.
- No hard trading safety gate was weakened.
