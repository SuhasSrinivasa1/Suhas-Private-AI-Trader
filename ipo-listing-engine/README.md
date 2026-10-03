# IPO Sentinel

IPO Sentinel is an isolated Android + backend project for research, shadow trading, and eventually controlled execution around newly listed NSE cash equities.

## Core contract

- Discover IPOs that are scheduled to list on the next NSE trading day.
- Run an after-hours research job after the cash session closes.
- Observe the special pre-open/listing process and continuous trading session.
- Continue monitoring every newly listed IPO for its first **30 exchange trading days** for secondary opportunities.
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
3. **30-day post-listing monitor** — keeps each IPO active for D1-D30 trading days and looks for continuation, healthy pullback, anchored-VWAP reclaim, post-IPO base breakout, failed breakdown/reclaim, volume revival, and eligible intraday fade opportunities.
4. **Decision engine** — regime classification + compatible strategy ensemble.
5. **Risk/execution engine** — broker eligibility, margin, liquidity, slippage, idempotent orders, OCO/exit logic.
6. **Owned-position registry** — isolates IPO Sentinel trades from every unrelated portfolio holding.
7. **Replay & learning** — exact point-in-time replay, MFE/MAE, missed opportunity, exit quality, strategy attribution, champion/challenger promotion.
8. **Shadow ledger** — daily and cumulative net P&L for a fixed virtual capital amount.

## 30-trading-day lifecycle

A listing stays in the active research universe for 30 actual exchange trading days, not 30 calendar days. Weekends and official exchange holidays do not consume the monitoring window.

The engine uses different opportunity families by age:

- **D1-D5:** post-listing continuation, failed listing-day move, VWAP/anchored-VWAP behavior and liquidity normalization.
- **D2-D10:** first healthy pullback, reclaim after shakeout, renewed relative strength.
- **D5-D30:** post-IPO base breakout, volume revival, failed breakdown/reclaim and trend continuation.
- **D1-D30 bearish:** bearish evidence can be tracked every day, but cash short execution is intraday-only and still requires current Groww/exchange eligibility.

Every 30-day decision is also replayed in the INR 100,000 shadow account so the application learns whether listing-day, early-post-listing, or later-base opportunities have the best net expectancy.

## Listing-day timing assumption

IPO Sentinel must treat the listing session as a special market state. For NSE IPO listings, the special pre-open session precedes normal trading. Continuous trading should only be enabled after the exchange transitions the symbol into the normal market session. The backend validates this state from current exchange/broker data rather than relying on a hard-coded clock alone.

## Development phases

- Phase 0: data-only discovery + three-month backfill + UI.
- Phase 1: full shadow engine, D1-D30 monitor and replay.
- Phase 2: one-symbol canary with tiny live quantity.
- Phase 3: controlled scaling up to the user-selected budget.
- Phase 4: adaptive champion/challenger strategy weighting.

See `docs/ARCHITECTURE.md` and `docs/RESEARCH_PLAN.md`.


## Groww settings (v0.4)

The Android UI deliberately hides service-transport details. There is no user-facing backend URL, HTTP/HTTPS field, or admin-key field.

The Settings tab contains only the trading inputs the user actually needs:

- Groww TOTP token / API key
- Groww TOTP secret
- Whitelisted static public IP
- Confirmation that the static IP has been whitelisted in Groww

The Dashboard no longer duplicates Settings with a separate "Configure Groww Connection" button.

### Internal service configuration

The static-IP trading service remains part of the architecture because API order placement must originate from the fixed whitelisted public IP. Its endpoint and device key are deployment/build configuration, not user settings.

Android build variables:
- `IPO_SENTINEL_API_URL`
- `IPO_SENTINEL_DEVICE_KEY`

Trading-service environment:
- `IPO_SENTINEL_DEVICE_KEY`
- `IPO_SENTINEL_MASTER_KEY`
- optional `IPO_SENTINEL_SETTINGS_FILE`

The TOTP token and secret are never returned by the settings APIs. They are encrypted at rest using the master key.

### User flow

1. Open **Settings**.
2. Enter Groww TOTP token/API key and TOTP secret.
3. Enter the fixed static public IP whitelisted in Groww.
4. Confirm the Groww whitelist checkbox.
5. Tap **Save Groww Settings**.
6. Tap **Validate Groww + Static IP**.
7. Live auto-trading remains locked until Groww authentication and the static-IP checks pass.
