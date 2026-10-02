# Book-to-Rule Extraction Contract

This file defines how complete books supplied by the user are converted into machine-testable research rules.

## Important source rule

A screenshot of a cover, search result, review or summary is not enough to claim that a book has been fully studied. Full-book extraction begins only when the complete user-provided PDF/EPUB/scan is available to the project.

For every book, IPO Sentinel will maintain two separate outputs:

1. **Source-faithful knowledge notes** — what the author actually teaches, with chapter/page provenance.
2. **Quantifiable hypotheses** — only ideas that can be expressed as measurable market, execution, risk or behavioral variables.

No metaphor, anecdote or psychological principle becomes an automatic trading signal merely because it appears in a book.

## Extraction schema

Every actionable concept is stored as:

- book
- chapter
- page/range
- concept name
- exact market context
- long / short / both / risk-only / psychology-only
- required data
- deterministic formula or state condition
- entry condition
- add condition
- exit condition
- invalidation
- position sizing implication
- timeframe
- applicability to listing day / D1-D5 / D6-D30
- assumptions
- known ambiguity
- test status
- replay sample count
- net expectancy after costs
- maximum adverse excursion
- maximum favorable excursion
- promotion status: RESEARCH_ONLY / SHADOW / CHALLENGER / CHAMPION

## Strategy conversion principles

- Candlestick names alone never trigger an order. Candle geometry is combined with location, trend, volume, spread, depth and regime.
- Psychology/risk material modifies execution discipline, sizing, invalidation and stopping rules rather than predicting price direction.
- Fundamental material is time-stamped so replay cannot use information that was not known at the decision timestamp.
- Multiple compatible strategies can vote in parallel.
- Conflicting strategies are retained in the audit trail; the ensemble must explain why one regime/family received more weight.
- Every registered strategy is replayed after market close, including strategies that did not win the live vote.
- Strategy selection is based on repeatable out-of-sample evidence, not on which rule best explains one historical move after the fact.

## Books visible in the current request

The screenshots show:
- *Super Trader* by Van K. Tharp
- *Trading in the Zone* by Mark Douglas
- *The Alchemist* by Paulo Coelho

The first two are trading/performance material. *The Alchemist* is a novel, so if it is intentionally included, its material should be treated only as general mindset/reflection unless the user supplies a specific trading interpretation. It should not be converted into market-direction formulas by invention.
