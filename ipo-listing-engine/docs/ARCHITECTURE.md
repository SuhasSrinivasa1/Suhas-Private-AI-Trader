# IPO Sentinel Architecture

## High-level flow

```text
NSE/BSE listing calendar + offer docs + company filings + market context
                              |
                              v
                    After-hours Research Job
                              |
                              v
Android APK <---- TLS/HMAC ---- Static-IP FastAPI Backend ---- Groww Trading API
   |                              |       |       |
   |                              |       |       +-- Order/position reconciler
   |                              |       +---------- Strategy + scoring engine
   |                              +------------------ Market data / feature engine
   |
   +-- Live toggle
   +-- Budget INR 10k..100k
   +-- Next listings
   +-- Shadow P&L
   +-- Decisions / reason codes
   +-- Kill switch
```

## Services

### ListingCalendarService
Determines the next exchange trading day and all securities scheduled to list. Weekends are trivial; holidays and exceptional exchange sessions must come from an official calendar feed. Live mode fails closed if the calendar is stale or unavailable.

### IPOResearchService
Stores only point-in-time information available before listing: RHP/DRHP facts, issue price, issue size, fresh issue vs OFS, subscription cohorts, anchor allocation, promoter ownership, financial growth, profitability, leverage, cash flow, valuation comparables, sector, use of proceeds, litigation/risk flags, and recent official company/exchange announcements.

### ListingSessionService
Tracks the special pre-open and the continuous market. It records discovered/equilibrium price, listing premium, imbalance, transition time, 1m/3m/5m/15m bars, VWAP, RVOL, spread, depth, trade velocity, buy/sell pressure, circuit band distance, and NIFTY/sector context.

### StrategyEngine
Patterns are features, not standalone commands. Regime classification selects a small compatible family set. Initial families:
- special-pre-open equilibrium stability / imbalance
- opening drive
- 5m and 15m opening-range breakout
- gap-and-go / gap-fade
- VWAP hold / pullback / reclaim / failure
- breakout-retest
- failed breakout / failed breakdown
- liquidity sweep
- exhaustion-volume reversal
- order-book imbalance + tape acceleration
- relative strength vs NIFTY and sector
- end-of-day continuation classifier for delivery hold

### MetaScorer
Produces expected net value and action class. It explicitly models fees, spread, slippage, estimated impact, fill probability and circuit-lock risk.

### RiskEngine
The budget slider is not silently reduced by an arbitrary conservative percentage. Position size is chosen dynamically up to the selected budget. Hard operational constraints remain non-bypassable: stale data, auth failure, unavailable shorting, unacceptable spread/impact, circuit trap, insufficient buyers/sellers, position mismatch, order uncertainty, and configured loss/stop conditions.

### OwnedPositionRegistry
Every order uses an IPO Sentinel strategy/order identifier. The registry only manages positions attributable to this application. Existing portfolio holdings are classified as EXTERNAL and are read-only.

### ReplayTrainer
Persists every feature snapshot, decision, order intent, acknowledgement, fill, exit and reason code. Nightly replay reconstructs the session without look-ahead bias. New/changed strategies remain shadow challengers until walk-forward evidence supports promotion.

## State machine

```text
DISCOVER -> RESEARCHED -> PREOPEN_WATCH -> CONTINUOUS_WATCH
                                        -> WAIT
                                        -> PROBE_LONG -> BUILD_LONG -> HOLD/REDUCE/EXIT
                                        -> PROBE_SHORT -> BUILD_SHORT -> HOLD/COVER
                                        -> HALTED
```

Long delivery transitions are separate from intraday short states. A short is force-covered before the applicable broker/exchange intraday cutoff.

## Persistence

Recommended production store: PostgreSQL + TimescaleDB (or PostgreSQL hypertables where available). SQLite is acceptable for local development only.

Core tables:
- ipo_issue
- listing_schedule
- research_snapshot
- market_tick
- candle
- order_book_snapshot
- feature_snapshot
- strategy_decision
- order_intent
- broker_order
- fill
- owned_position
- shadow_trade
- replay_run
- strategy_version
- strategy_evidence
- daily_audit

All time-series rows include `event_time`, `ingested_at`, `source`, and `source_version`.

## Security

- TOTP/API secret stays server-side in encrypted secret storage.
- No credentials in Git, APK resources, logs, analytics or crash reports.
- API order traffic originates from a broker-whitelisted static public IP.
- Android authenticates to the backend with device-bound credentials and signed requests.
- Order submission is idempotent.
- Live toggle state is server-authoritative and expires on credential/session uncertainty.
