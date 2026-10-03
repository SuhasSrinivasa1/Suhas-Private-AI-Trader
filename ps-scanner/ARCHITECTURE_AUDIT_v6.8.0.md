# PS Scanner v6.8.0 Architecture Audit

## Audit question

Do all engines work hand-in-hand without independently re-reading the same external evidence, while preserving high scan frequency?

## Pre-v6.8 findings

The scanner architecture was already mostly cache-first, but orchestration was worker-centric:
1. full-market prices were centrally refreshed, while live-book maintenance could still invoke network-enabled price reads;
2. news was consumed cache-only but had no background producer;
3. prospective earnings refresh existed but was not scheduled;
4. U.S. weekly selection and live repricing could independently invoke international batch history;
5. global, sector and fundamental workers had no unified producer/consumer lineage;
6. institutional evidence was limited mainly to ownership and price/volume proxies.

## v6.8 architecture

### Producer layer
Dedicated producers own external observation:
- Groww full-market LTP;
- Groww priority LTP;
- Groww instrument/universe and historical cache warmers;
- batched global/cross-asset data;
- fundamentals;
- priority news;
- earnings/events;
- institutional NSE observations;
- shared international batch data.

### Consumer layer
Intraday, Weekly, Monthly, ETF, Circuit, International, Global→India, algorithm analytics and lifecycle maintenance consume caches. Scanner threads do not synchronously refresh news/fundamentals/global context or institutional feeds while scoring candidates.

### Frequency
Existing scanner intervals remain unchanged. New producers run independently, so removing redundant transport does not reduce the number of scan/evaluation cycles.

### Failure semantics
Producer failure never fabricates a pass. Consumers see UNKNOWN, stale or prior point-in-time evidence. Existing hard data/risk gates remain authoritative.

## Institutional semantics

Three concepts are explicitly separated:

1. **Direct disclosure evidence:** large-deal rows from the exchange.
2. **Market-level institutional context:** aggregate FII/FPI and DII flow.
3. **Inferred accumulation/distribution:** CMF/MFI/OBV/RVOL derived from OHLCV.

Only (1) is direct symbol-level institutional disclosure. (2) cannot identify the buyer of an individual stock. (3) cannot identify the actor at all.

## Adaptive algorithm

The trading algorithm is not a second scanner that duplicates the existing engines. It is the versioned adaptive manifest coordinating them:
- engines create recommendation candidates under their existing lifecycle contracts;
- active strategy Champions/seeds determine the current algorithm manifest;
- daily OOS validation, live shadow evidence and decay monitoring can change that manifest;
- current outputs from all books are presented as one algorithm surface;
- performance is measured on resolved recommendation outcomes.

This avoids a competing duplicate decision engine while making daily adaptation visible and auditable.

## 80% target

A fixed 80% display would be statistically invalid. v6.8 records actual outcomes and computes Wilson confidence intervals. A confidence-supported 80% status requires both a minimum sample and a lower confidence bound ≥80%.

## Efficiency outcome

The architecture targets “one observation, many consumers” without introducing a process-wide lock:
- market data remains in existing in-memory/file caches;
- evidence-fabric state stores metadata and lineage, not duplicate heavy datasets;
- SQLite WAL remains the persistence coordination mechanism;
- scanner workers remain independently supervised and restartable.

## Remaining gaps

v6.8 does not pretend to implement data that is not reliably sourced: promoter/pledge/insider disclosures, authoritative deliverable-volume series, derivatives positioning and Level-2 historical depth remain explicit UNKNOWN gaps.
