# PS Scanner Quant v6.8.0 — Shared Evidence Fabric & Adaptive Trading Algorithm

## Purpose

v6.8.0 addresses two architecture requirements: every research engine should consume the same point-in-time evidence rather than independently re-fetching identical external data, and the product should expose one adaptive trading-algorithm surface covering all recommendation lanes.

## Shared Market Evidence Fabric

The release introduces a producer/consumer evidence fabric.

External observations are produced by dedicated background workers at their natural cadence:
- priority Groww quotes;
- full-market Groww quotes and full-NSE regime breadth;
- global/cross-asset context;
- point-in-time fundamentals;
- sector/industry breadth;
- priority news;
- prospective earnings/events;
- institutional intelligence;
- international daily/intraday batch data.

Intraday, Weekly, Monthly, ETF, Circuit, International and Global→India remain independently supervised scanners, but consume these shared caches. No scanner frequency is lowered. A dedicated 60-second priority-quote producer replaces duplicate live-book quote fetching.

## Institutional / accumulation intelligence

The institutional layer combines:
- NSE FII/FPI and DII market-level activity;
- NSE large-deal disclosure observations;
- point-in-time institutional ownership;
- CMF20;
- MFI14;
- OBV and short-horizon OBV trend;
- relative volume.

Direct exchange disclosures and inferred OHLCV accumulation are deliberately labeled separately. Market-level FII/DII flow is only a low-weight context term and is never represented as proof that a particular stock was bought by institutions.

The new INSTITUTIONAL_ACCUMULATION family is seeded CHALLENGER-only. It must satisfy the unchanged OOS/holdout/cost/stability/live-shadow Champion contract before it can become an active production strategy.

## Adaptive Trading Algorithm

A new Trading Algorithm API/UI presents:
- a deterministic algorithm version derived from date + active validated strategy manifest;
- current Champion/seed family manifest;
- all live output lanes: Intraday, Weekly, Monthly, ETF, Circuit, next-day Circuit, International weekly, Global→India LONG and SHORT;
- actual resolved target-hit rate;
- actual directional accuracy;
- Wilson 95% confidence intervals;
- per-book evidence;
- algorithm-version history;
- shared-fabric freshness and producer/consumer lineage;
- institutional evidence status.

The algorithm updates automatically when daily strategy validation promotes/suspends strategies. It does not bypass the underlying recommendation engines or their safety gates.

## Accuracy policy

80% is a target, not a guaranteed value.

The application marks the 80% target as:
- EVIDENCE_BUILDING_OR_BELOW_TARGET;
- OBSERVED_TARGET_MET_NOT_CONFIDENCE_SUPPORTED; or
- CONFIDENCE_SUPPORTED.

Confidence-supported 80% requires at least 50 resolved samples and a Wilson 95% lower bound of at least 80%. No synthetic accuracy value is generated.

## Preserved invariants

v6.8.0 does not loosen:
- full-NSE discovery;
- Static-IP execution-only scope;
- broker position source-of-truth / mismatch hard block;
- live Groww margin/MIS permission;
- ₹20,000 maximum notional;
- ₹500 maximum modeled stop risk;
- minimum 1.5 reward/risk;
- 15:00 Indian SHORT hard exit;
- Weekly/Monthly/ETF LONG-only multi-session execution;
- Weekly/Monthly overlapping frozen identity;
- no fabricated quota filling;
- data freshness and liquidity gates;
- signal/execution attribution separation;
- point-in-time replay/audit;
- manual Groww preview/confirm execution flow.

## Transparent remaining evidence gaps

The following are not fabricated in v6.8.0:
- historical point-in-time fundamentals before prospective capture began;
- direct promoter pledge/governance and insider-transaction feeds;
- authoritative per-stock deliverable-volume percentage history;
- derivatives OI/PCR/IV/skew;
- full Level-2 depth and market-impact history;
- mapped sector ETF confirmation for every industry.
