# Multyfi Delivery Buy — v1.1.0

This is an in-place update to v1.0.1. The existing Multyfi notification BUY engine stays unchanged; v1.1.0 adds a separate manual LONG / SHORT launcher.

## Existing Multyfi automation — unchanged

- Intraday release → ₹1,00,000 nominal budget → Groww `NSE / CASH / CNC / MARKET / BUY`.
- Swing release → ₹10,000 nominal budget when Swing toggle is ON.
- Multibagger release → ₹10,000 nominal budget when Multibagger toggle is ON.
- Later Multyfi close/exit/profit/stop notifications remain ignored.
- Static-IP and Groww authentication readiness remain required before ARM.
- The Multyfi notification path still contains no SELL, MIS, GTT, stop-loss, target, trailing, re-entry, P&L, position or holdings logic.

## New manual budget

- Shared LONG/SHORT slider from ₹0 to ₹1,00,000 in ₹10,000 increments.
- Default is ₹50,000.
- The saved amount is a nominal notional budget. Because entry is a MARKET order, the final executed notional can differ slightly as the market moves.

## New LONG section

- Search/select an NSE CASH equity from the Groww instrument master.
- A single LTP lookup is made only at button press to calculate quantity: `floor(budget / LTP)`.
- Entry: `NSE / CASH / CNC / MARKET / BUY`.
- The app polls only the Groww order-detail endpoint briefly to confirm actual fill quantity and average fill price; it does not monitor the stock price.
- Target: actual average fill × 1.01, rounded in the favourable direction to the instrument tick size.
- A broker-hosted Groww GTT is then created with `SELL`, `UP`, `CNC`, `LIMIT` at the target.
- No stop-loss.

## New SHORT section

- Shorting necessarily opens with `SELL`, not `BUY`.
- Entry: `NSE / CASH / MIS / MARKET / SELL`, producing a negative intraday position when accepted/executed.
- Target: actual average fill × 0.99, rounded in the favourable direction to the instrument tick size.
- A `DAY` `LIMIT BUY` with product `MIS` is then placed at the 1% lower target to cover the short. This target is broker/exchange hosted and needs no app price monitoring.
- No stop-loss.
- MIS cannot be carried overnight. Groww/exchange end-of-day square-off behaviour is outside this app.

## Important interpretation of “no sell logic”

The app still has no active exit engine, price watcher, trailing logic, stop-loss engine, or reaction to Multyfi closure messages. However, a LONG +1% GTT target is technically a future SELL instruction stored at Groww. That one-time broker-hosted target is required by the requested LONG target behaviour. For SHORT, the target is a same-day BUY-to-cover limit order, not a persistent GTT, so it does not survive the intraday position into a later session.

## Stock universe

The APK bundles an NSE CASH EQ snapshot generated from Groww's official instrument CSV during CI. The app also refreshes that universe from the same official Groww CSV in the background when stale, keeping autocomplete available immediately from the bundled/cached list.
