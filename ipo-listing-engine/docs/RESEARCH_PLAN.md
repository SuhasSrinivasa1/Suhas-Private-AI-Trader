# Three-Month IPO Research and Replay Plan

The research job separates two questions that are often confused:

1. **Issue-price listing gain:** first traded/listed price versus IPO issue price.
2. **Tradable post-listing edge:** return available after continuous trading starts.

A strong listing premium does not automatically imply a profitable buy at the continuous-market open. A stock can list far above issue price and immediately mean-revert.

## Required cohort

For every NSE mainboard and SME equity listing in the rolling previous 3 months:

- issue price
- discovered/listing price
- continuous-session first tradable quote
- 1m bars from continuous-market start to close
- D0 close
- D+1 through D+5 trading-day closes
- D0/D+1/D+5 high, low, volume and turnover
- circuit events / T2T / ASM-GSM flags where applicable
- special-pre-open equilibrium and imbalance where available
- subscription by QIB/NII/retail
- issue size, fresh issue/OFS split, market cap/free float
- sector and benchmark return
- fundamental snapshot available before listing

## Metrics

For long and short counterfactuals calculate:

- D0 open-to-close, high/low excursions
- D+1 and D+5 returns
- MFE / MAE at 1m, 5m, 15m, 30m, 60m, close, D+1, D+5
- time to MFE / MAE
- VWAP hold/failure
- opening range break/retest
- RVOL and liquidity
- spread/impact/fill assumptions
- net P&L after charges
- profit factor, expectancy, drawdown, tail loss
- calibration by mainboard vs SME, subscription regime, listing-premium bucket, sector and market regime

## No look-ahead

A replay at 10:07 may only use information that existed at 10:07. D0 close, next-day behavior and later filings cannot leak into the decision.

## Strategy promotion

Use rolling walk-forward windows. Candidate strategies are CHALLENGERS. A strategy can become CHAMPION only after minimum sample, positive net expectancy after costs, acceptable drawdown/tail loss, and stability across more than one regime.

The job must be allowed to conclude that a listing had no reliable tradable edge.
