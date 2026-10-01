# PS Scanner Quant v6.6.1 — Frozen Identity & Search Exhaustion Integrity

v6.6.1 is a first-principles follow-up to v6.6.0. No score, liquidity, freshness, target-feasibility, risk, Groww-budget, or order-execution threshold is loosened.

## Structural fixes

- **Weekly/Monthly identity exclusion follows the frozen period, not LIVE state.** An early WIN/LOSS/MISS no longer releases a symbol to the overlapping horizon. SQLite enforces overlapping-period exclusion atomically on insert, and the application uses the same period-overlap rule.
- **Legacy current/future collisions are repaired deterministically.** Current-period priority and publication time choose the surviving book; invalid opposite-book identities become VOID so they do not contaminate P/L or learning evidence.
- **Intraday zero-live recovery proves search coverage.** Rotating cached-ready batches accumulate funnel counters and strongest near misses across a complete pass. The scanner reports SEARCH_INCOMPLETE until the pass has actually scanned the cached-ready set.
- **Funnel universe accounting is explicit.** `universe_total` means the full NSE universe; `scan_scope_total` and `scan_scope_processed` identify the bounded batch actually examined.
- **ETF missed-freeze recovery is market-hours bounded.** It may recover after the preferred window only while the NSE session is still open; it does not create a current-week book after hours from cached closing data.
- **SQLite connection policy is explicit.** Every independent connection reasserts `PRAGMA synchronous=NORMAL`; WAL, busy timeout, foreign keys and fail-soft health logging remain unchanged.
- **Performance diagnostics are richer.** Loss rate and miss rate are first-class metrics, and `result` / `close_reason` can be used as performance groupings for Circuit and other outcome diagnostics.

## What was deliberately not changed

The release does not force five recommendations, fabricate replacements, lower liquidity or risk requirements, substitute stale prices, use future information, or replace a frozen identity after publication. Strategy-family diversity remains advisory/shadow until validated out of sample. VOID/data-integrity outcomes remain audit records and are excluded from genuine trading P/L.

## Regression additions

The v6.6.1 suite directly tests closed Weekly identities blocking overlapping Monthly publication, non-overlapping period reuse, application conflict lookup semantics, exhaustive Intraday pass classification, ETF recovery stopping at market close, per-connection SQLite WAL/synchronous policy, and explicit loss/miss rates.
