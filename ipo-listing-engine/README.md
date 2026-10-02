# IPO Sentinel

IPO Sentinel is an isolated Android + backend project for research, shadow trading, and eventually controlled execution around newly listed NSE cash equities.

## Core contract

- Discover IPOs that are scheduled to list on the next NSE trading day.
- Run an after-hours research job after the cash session closes.
- Observe the special pre-open/listing process and continuous trading session.
- Produce one of: WAIT, PROBE_LONG, BUILD_LONG, HOLD_LONG, REDUCE_LONG, FLAT, PROBE_SHORT, BUILD_SHORT, HOLD_SHORT, COVER_SHORT.
- Long positions may persist as delivery when the thesis remains valid.
- Short positions are intraday only and require live broker/exchange eligibility.
- Only positions/orders created by IPO Sentinel are managed by IPO Sentinel.
- Shadow mode is the default. Shadow capital defaults to INR 100,000.
- Live budget is user-selectable from INR 10,000 to INR 100,000.
- Live execution is an explicit user toggle and is OFF by default.
- Broker credentials are never stored in the APK or committed to Git.

## Architecture

Android (Kotlin/Jetpack Compose) is the control surface. A static-IP backend performs broker authentication, live market-data processing, strategy evaluation, position reconciliation, replay, and order routing.

The first implementation is deliberately split into:

1. **Discovery & research** — next-listing calendar, issue/fundamental data, market/sector context.
2. **Listing-session intelligence** — special pre-open equilibrium data, 1m/3m/5m/15m bars, VWAP, RVOL, depth, spread, order-flow, circuit proximity.
3. **Decision engine** — regime classification + compatible strategy ensemble.
4. **Risk/execution engine** — broker eligibility, margin, liquidity, slippage, idempotent orders, OCO/exit logic.
5. **Owned-position registry** — isolates IPO Sentinel trades from every unrelated portfolio holding.
6. **Replay & learning** — exact point-in-time replay, MFE/MAE, missed opportunity, exit quality, strategy attribution, champion/challenger promotion.
7. **Shadow ledger** — daily and cumulative net P&L for a fixed virtual capital amount.

## Listing-day timing assumption

IPO Sentinel must treat the listing session as a special market state. For NSE IPO listings, the special pre-open session precedes normal trading. Continuous trading should only be enabled after the exchange transitions the symbol into the normal market session. The backend validates this state from current exchange/broker data rather than relying on a hard-coded clock alone.

## Development phases

- Phase 0: data-only discovery + three-month backfill + UI.
- Phase 1: full shadow engine and replay.
- Phase 2: one-symbol canary with tiny live quantity.
- Phase 3: controlled scaling up to the user-selected budget.
- Phase 4: adaptive champion/challenger strategy weighting.

See `docs/ARCHITECTURE.md` and `docs/RESEARCH_PLAN.md`.
