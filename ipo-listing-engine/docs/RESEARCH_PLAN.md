# Three-Month IPO Research, 30-Day Monitoring and Replay Plan

The research job separates three questions:

1. **Issue-price listing gain:** first traded/listed price versus IPO issue price.
2. **Tradable listing-day edge:** return available after continuous trading starts.
3. **Post-listing edge:** additional long or eligible intraday-short opportunities during the first 30 exchange trading days.

A strong listing premium does not automatically imply a profitable buy at the continuous-market open. A stock can list far above issue price and immediately mean-revert. Likewise, a profitable D1 long does not imply the correct direction on D5; the 30-day engine can move LONG -> FLAT -> eligible intraday SHORT -> FLAT -> LONG again as evidence changes.

## Required cohort

For every NSE mainboard and SME equity listing in the rolling previous 3 months:

- issue price
- discovered/listing price
- continuous-session first tradable quote
- 1m bars from continuous-market start to close
- every trading-day bar through D30
- D1-D30 intraday high, low, close, volume and turnover
- listing-anchored VWAP and rolling anchored VWAP state
- circuit events / T2T / ASM-GSM flags where applicable
- special-pre-open equilibrium and imbalance where available
- subscription by QIB/NII/retail
- issue size, fresh issue/OFS split, market cap/free float
- sector and benchmark return
- fundamental snapshot available at each decision timestamp
- buyer/seller depth, spread, relative volume and trade velocity where available

## Metrics

For long and short counterfactuals calculate:

- D0 open-to-close, high/low excursions
- D1 through D30 return paths
- MFE / MAE at 1m, 5m, 15m, 30m, 60m, close and subsequent trading days
- time to MFE / MAE
- VWAP and listing-anchored-VWAP hold/failure/reclaim
- opening range break/retest
- RVOL and liquidity
- spread/impact/fill assumptions
- net P&L after charges
- profit factor, expectancy, drawdown, tail loss
- calibration by mainboard vs SME, trading-day age, subscription regime, listing-premium bucket, sector and market regime

## Long-to-short transition

The directional model may turn bearish after an earlier profitable long. When that occurs:

1. Exit only the delivery shares owned by IPO Sentinel.
2. Reconcile with Groww and confirm the app-owned long is flat.
3. Re-run the current shortability/liquidity/risk checks.
4. Only then may the system open an intraday MIS short.
5. IPO Sentinel begins its force-flat process at **15:05 IST**. This is an internal early cutoff designed to create a buffer before Groww's published stock-MIS auto-squareoff window.

The engine never converts unrelated user holdings into sell inventory.

## Replay tournament

Every registered strategy gets the same point-in-time market tape after close, whether or not it was selected live.

For each candidate strategy/version, replay records:
- whether it would have entered
- entry timestamp and modeled fill
- add/reduce events
- stop and target behavior
- exit timestamp
- gross P&L
- brokerage/statutory costs
- modeled spread/slippage/impact
- net P&L
- MFE/MAE
- drawdown
- latency sensitivity
- missed opportunity versus the live-selected strategy

The report explicitly answers:
- Was the chosen strategy profitable?
- Did another already-known strategy produce more net yield?
- Was the difference caused by signal quality, entry timing, sizing, exit timing or execution?
- Was the better result stable across prior out-of-sample cases, or only a hindsight winner?

## No look-ahead

A replay at 10:07 may only use information that existed at 10:07. D0 close, next-day behavior and later filings cannot leak into the decision.

## Strategy promotion

Use rolling walk-forward windows. Candidate strategies are CHALLENGERS. A strategy can become CHAMPION only after minimum sample, positive net expectancy after costs, acceptable drawdown/tail loss, and stability across more than one regime.

The job must be allowed to conclude that a listing had no reliable tradable edge.
