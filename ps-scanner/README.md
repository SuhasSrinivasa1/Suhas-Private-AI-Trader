# PS Scanner Quant v6.7.3 — Execution Cache & Health Latency Hardening

v6.7.3 closes the remaining operational gaps observed after v6.7.2 passed production validation.

- The background broker probe now refreshes both Groww auth status and the cached public IP, so the UI does not remain falsely Static-IP locked after a restart.
- Public-IP detection has a second independent read-only provider if the primary lookup is temporarily unavailable.
- `/api/health` now uses one bounded SQLite snapshot and a pure cached execution-readiness projection; it no longer opens separate DB connections for order count and position reconciliation.
- Broker-position telemetry records credit/debit/carry-forward fields and explicitly labels external CNC/MIS session positions.
- Position mismatches remain fail-closed; v6.7.3 does not waive broker-vs-local reconciliation.
- No recommendation, strategy, target/stop, risk, short, execution-permission, lifecycle, or learning gate is loosened.

See `RELEASE_v6.7.3.md`.

# PS Scanner Quant v6.7.2 — Bounded Runtime Sanity & Deep DB Verification

v6.7.2 fixes the remaining post-install timeout discovered after v6.7.1. The runtime sanity endpoint is now explicitly bounded, while deep SQLite integrity remains verified through an isolated backup restore.

- `/api/sanity` no longer runs `PRAGMA quick_check` inline against the live production database.
- Runtime integrity queries use a SQLite progress handler with a 1.5-second wall-clock budget and short lock timeouts.
- Deep database verification is still required: backup → isolated restore → `PRAGMA quick_check` → required-table verification.
- The validator reuses a verified same-day backup when available; otherwise it explicitly calls `/api/maintenance/backup-now` with a 120-second maintenance budget.
- Backup-status telemetry is itself bounded and fails soft if the live state DB is temporarily busy.
- No scanner, strategy, target/stop, risk, execution, lifecycle or learning gate is loosened.

See `RELEASE_v6.7.2.md` and `ARCHITECTURE_AUDIT_v6.7.2.md`.

# PS Scanner Quant v6.7.1 — Nonblocking Health & Validation Reliability

v6.7.1 is a narrow reliability update over v6.7.0. It preserves all scanner, execution, risk, lifecycle and learning behavior while fixing the production observability defect found on the Mac install.

- `/api/health` is passive: no broker/network calls, no universe refresh, and no wait behind the Groww history pacing lock.
- Health DB snapshots use short bounded timeouts and fail soft with explicit degraded telemetry instead of hanging.
- Cached execution readiness uses bounded order-count and position-reconciliation reads.
- `/api/evidence/status` uses the same passive/nonblocking history and bounded evidence snapshots.
- `/api/sanity` no longer performs unbounded final state reads for execution-integrity telemetry.
- The post-install validator retries bounded endpoint checks and now correctly initializes the v6.7 diagnostics, execution analytics and backup status checks.
- New regression tests reproduce a busy history pacer and verify health still returns promptly.

See `RELEASE_v6.7.1.md`.

# PS Scanner Quant v6.7.0 — Production Integrity, Replay & Execution Attribution

v6.7.0 completes the next production-hardening agenda without adding strategy sprawl or weakening any recommendation safety gate.

- **Execution integrity:** every manual order preview/submit re-checks Groww connectivity, Static IP, market session, live spread/circuit conditions, broker positions, dynamic margin/MIS permission, portfolio limits, stop-risk sizing and expected net edge after live execution-cost reserves.
- **Broker position is the execution source of truth:** current-session Groww positions are reconciled to PS Scanner fills. Any mismatch or external non-zero session position hard-blocks new execution until reconciled.
- **Signal and execution quality are separate:** recommendations retain their own outcome/MFE/MAE ledger; orders/fills now carry decision price/time, submit/ack timestamps, fill slippage and decision-to-fill latency.
- **Why No Trade is first-class:** the Performance surface distinguishes search incomplete, data not ready, true qualified-opportunity scarcity, and downstream publication/execution conditions using funnel coverage, blockers and near misses.
- **Deterministic production replay:** v6.7+ candidate decisions include a point-in-time audit envelope and can replay their stored production gate contract. Legacy rows remain explicitly partial rather than having historical inputs invented.
- **Audit lineage:** new recommendations/decisions store release version, settings hash, strategy versions/parameter hashes, input hashes and context timestamps.
- **Verified backups:** SQLite backups are produced with the SQLite backup API, restored into an isolated temporary database, and accepted only after `PRAGMA quick_check` and required-table verification.
- **Experiment governance:** changes can be registered with hypothesis, affected books, sample requirement, promotion criterion and rollback criterion.
- **Evidence-gated cohorts:** opening/midday/late-session and behavior-cluster analytics are visible, but remain shadow-only until minimum sample, Wilson-width, positive-expectancy and PF requirements are satisfied. They never auto-activate.

See `ARCHITECTURE_AUDIT_v6.7.0.md` and `RELEASE_v6.7.0.md`.

# PS Scanner Quant v6.6.1 — Frozen Identity & Search Exhaustion Integrity

v6.6.1 is a structural follow-up to the v6.6.0 lifecycle audit. It does not loosen any trading threshold or hard safety gate. It strengthens frozen-book identity integrity, makes zero-live Intraday shortage claims depend on an actually completed cached-ready universe pass, bounds ETF missed-freeze recovery to market hours, reasserts SQLite durability policy per connection, and adds loss/miss rates plus result/close-reason performance grouping.

See `ARCHITECTURE_AUDIT_v6.6.1.md` and `RELEASE_v6.6.1.md` for the current page/domain matrix, findings, invariants and tests.

# PS Scanner Quant v6.6.0 — Current-Period Lifecycle & Statistical Audit

v6.6.0 restructures PS Scanner around explicit page/book lifecycle contracts. Active pages show the current actionable period only; historical outcomes remain in SQLite for learning and are available in the dedicated Performance & History surface. The release adds `/api/lifecycle`, `/api/performance`, `/api/history/recommendations`, a broader bounded `/api/sanity`, rejection-funnel telemetry, numerical uncertainty metrics and richer worker health.

The audit removed two accidental recommendation-volume bottlenecks without lowering hard safety gates: the unvalidated two-family strategy requirement is now advisory/shadow, and Intraday's hidden second score gate was consolidated so the unchanged effective score-76 threshold is visible and countable. Weekly/Monthly symbol exclusivity is additionally enforced by SQLite triggers. Same-session stale LIVE rows are deterministically resolved; VOID/data errors remain auditable and are excluded from trading P/L/decay evidence.

See `ARCHITECTURE_AUDIT_v6.6.0.md` for the page/domain matrix and first-principles findings, and `RELEASE_v6.6.0.md` for release notes.

# PS Scanner Quant v6.4.3 — Full-Breadth Data Hydration

v6.4.3 keeps the 3,395-share full NSE equity discovery and v6.4.2 Circuit evidence gates, but fixes the data-hydration bottleneck exposed by the live diagnostic. One failed Groww LTP batch can no longer abort the entire 3k+ symbol refresh; successful batches are preserved and client-side symbol errors get a bounded 10-symbol fallback. Universe telemetry now exposes the LTP batch result directly.

History warm-up is useful-first without narrowing research breadth: active recommendations and new listings first, then mapped industry/benchmark anchors, actual live movers, and finally the remaining full NSE rotation. Missing-cache names are no longer given a fake activity rank, warm telemetry avoids constructing thousands of pandas DataFrames, and sector-context refresh is accelerated so breadth/peer evidence becomes usable as anchor histories arrive.

v6.4.3 is a live-telemetry correctness release. It preserves the full 3,395-share dynamic NSE research universe introduced in v6.4.1, but prevents stale v6.4.0 breadth counters from being displayed after a universe rebuild. Breadth/live-price/limited-history totals are now accepted only when they belong to the current universe; otherwise the API reports `AWAITING_CURRENT_UNIVERSE_PASS` until the next full discovery pass.

Same-day Circuit publication is now fail-closed. A verified circuit band and modeled 15:00 capacity remain necessary but are no longer sufficient. An actionable Circuit call also requires a fresh current-session intraday bar, confirmed live turnover, non-failed relative-volume/liquidity evidence, an executable counterparty side, and Groww-side buy/sell/intraday permission. Names that fail those evidence checks remain research/watch candidates rather than executable recommendations. Pre-v6.4.3 LIVE Circuit rows are preserved in the ledger as VOID with `V642_CIRCUIT_EVIDENCE_RESET`.

# Previous v6.4.1 notes

v6.4.1 is the corrective follow-up to the first full-breadth release. Live telemetry proved that Groww's NSE CASH master can label debt/government and other non-share securities with a cash-equity style instrument type, so `instrument_type=EQ` alone is not a safe stock-universe test. The stock universe is now grounded in NSE's official equity-share series families: fully-paid equity `EQ/BE/BZ`, SME equity `SM/ST/SZ`, plus partly-paid `E*/X*` equity series. Debt/NCD, government securities, mutual funds, REIT/InvIT, preference shares, warrants and ETFs are excluded from the stock universe; ETFs remain in their dedicated book.

The no-cap requirement is unchanged: **every actual NSE equity share** in the Groww master is discovered regardless of market cap, liquidity, index membership, execution permission or listing age. Newly appearing equity symbols are retained and prioritized for history warm-up. Missing history never removes the symbol from discovery, but it prevents evidence-dependent strategy votes from being fabricated.

v6.4.1 also fixes two live telemetry/performance issues exposed by the 4,290-instrument run: `/api/universe/status.daily_ready` now uses the current full-breadth snapshot instead of a stale warmer count, and full-universe scans avoid constructing pandas DataFrames for thousands of symbols that do not yet have cache files. Closed-window Weekly/Monthly status now reports the current equity universe separately from the last scan universe, so a preserved pre-upgrade `80` cannot masquerade as the active discovery breadth.

Architecture in v6.4.1:
- Batched LTP discovery covers the full dynamic NSE equity-share universe; no market-cap or liquidity top-N research cap.
- Intraday, Weekly and Monthly scan the full discovered universe from cache. Daily/intraday history readiness is reported separately from universe discovery.
- Market regime breadth is computed from all data-ready NSE equities rather than a fixed sample of 80.
- Circuit Radar performs a cheap full-market coarse screen first, then requests exact exchange circuit bands only for plausible/new/limited-history candidates.
- Global→India maps global cues across the full NSE equity research universe before producing a small actionable next-session slate.
- New listings are not excluded for lacking long history. They remain in discovery and are explicitly marked limited-evidence until enough real observations accumulate.
- Legacy `universe_size`, `intraday_scan_size` and `horizon_scan_size` settings are migrated to zero and can no longer silently truncate research.
- The v6.3.8 safety contract is retained: Weekly/Monthly/ETF executable books are LONG-only; bearish multi-session signals are research-only; Indian SHORT execution remains same-day with the 15:00 IST cutoff.

The UI now exposes **NSE universe discovered / breadth evaluated / daily ready / intraday ready / limited-history** counts. A small frozen output slate is an intentional selection result; a small discovery universe is no longer acceptable.

Release validation: 149 tests pass, including dynamic 4,201-equity synthetic-universe coverage, official NSE equity-series filtering, debt/NCD exclusion, new-listing discovery, readiness telemetry correction, missing-cache fast-path scanning and nonblocking full-market LTP-cache concurrency.

---


v6.3.8 corrects the Indian horizon execution contract exposed by the live Monday run. WEEKLY, MONTHLY and ETF are now **LONG-only executable books** because Indian cash SHORT positions cannot be carried across sessions for this user. Bearish multi-session signals continue to be scored and retained as **RESEARCH ONLY** so they can inform same-day short lanes, but they are never published with an order button.

The upgrade preserves the ledger and converts any LIVE Weekly/Monthly/ETF SHORT rows to CLOSED/VOID with reason `V638_HORIZON_SHORT_RESEARCH_ONLY_RESET`. Runtime order readiness independently blocks any surviving horizon SHORT. VOID audit rows do not poison the corrected period book; a later valid LONG recovery freeze remains possible within the normal morning recovery contract.

v6.3.8 also clears persisted `running:true` scan state on process restart, stops re-running expensive horizon scans once a valid frozen period book exists, and applies the same no-rescan/morning-window guard to ETF. No target threshold, risk cap, Static-IP rule or strategy score threshold is loosened. Release validation: 131 tests pass.

v6.3.7 fixes the live first-symbol scanner freeze exposed after v6.3.6 restored full daily history. The SQLite helper no longer holds a process-wide Python RLock for the entire lifetime of every connection; WAL + busy_timeout handle short concurrent access. Shadow-signal resolution now performs cached-history/as-of price work outside its DB write context, then commits only the finished updates. This prevents maintenance/research workers from starving Intraday, Weekly and Monthly progress/state/fundamental reads for minutes. No strategy, target, publication, risk, Static-IP or execution threshold is loosened. Release validation: 121 tests pass; an 8-thread read/write SQLite stress test completed without lock errors.

v6.3.7 fixes the live daily-cache defect identified from the on-device audit: Groww history contained ~237 HLCV rows per symbol, but after the first ~14 rows the daily `open` field was `None`. Older parser logic discarded every row missing any OHLC field, leaving Weekly/Monthly with only 14 rows. v6.3.7 treats the daily open as optional for horizon HLCV analytics, preserves real high/low/close/volume without inventing an open, disables open-dependent gap/candlestick signals when the current open is unavailable, and reports those filters as UNKNOWN.

v6.3.7 fixes a horizon-blocking daily-history cache parser defect observed in the live v6.3.4 audit: raw daily cache files contained ~237 rows per symbol while only ~14 rows survived parsing, leaving Weekly/Monthly at `ready=0`. The parser now accepts current Groww ISO timestamps plus legacy epoch seconds, numeric-string epochs, millisecond/microsecond/nanosecond epochs, legacy dict candle rows, comma-formatted numeric fields, and non-critical bad volume values without discarding valid OHLC. Existing cache files are reused; no strategy threshold is loosened.

v6.3.7 fixes the real in-place installer import-context bug that could cause the Morning Freeze settings migration to modify the extracted source tree instead of the target app. The migration now runs from `$APP`, independently verifies `$APP/data/settings.json`, and the runtime loader self-heals legacy 6/4 observation gates to 1/1 while preserving all unrelated settings.

## Morning-freeze upgrade migration hotfix

v6.3.7 fixes the in-place upgrade path for the v6.3.2 Morning Freeze release. Older runtime settings could preserve `weekly_min_observations=6` (and an older monthly observation count), causing the post-copy regression suite to fail and correctly roll back the install. v6.3.7 migrates only those two persisted observation-gate settings to `1` before tests run; credentials, Static IP, execution preferences, recommendation ledger, caches and all other settings remain preserved.

The U.S. weekly low-turnover research book from v6.3.1 and the Morning Freeze behavior from v6.3.2 are otherwise unchanged.

## U.S. weekly low-turnover research book

### U.S. weekly contract

- Universe: liquid U.S.-listed stocks plus liquid ETFs such as SPY, QQQ, IWM, DIA, XLK, SOXX, SMH, XLF, XLE, XLV, XLI, XLY, XLP, XLB, GLD, SLV and TLT.
- Side: LONG only.
- Freeze: first actual U.S. trading session of the week, after opening-price validation (default 09:45 ET; latest normal freeze 11:00 ET).
- Holding horizon: the remainder of that U.S. trading week.
- No rank replacement and no backfill after a recommendation closes.
- Exit: weekly target reached, stop/thesis invalidation, or U.S. week end.
- Targets are volatility/capacity based for the remaining week, not sized to the current day's remaining minutes.
- Ranking objective: highest **expected net weekly edge** among the screened universe after a configurable turnover/friction reserve. This is an ex-ante ranking, not a guarantee that the selected security will be the hindsight-best performer.
- Foreign rows remain research-only in this application; Groww execution buttons are not exposed for U.S. securities.

The default friction reserve is deliberately a generic turnover/cost reserve, not an individualized tax calculation. Tax treatment varies by investor/account/jurisdiction. The low-turnover architecture reduces repeated entry/exit activity without pretending to know the user's exact tax liability.

Legacy LIVE International daily-session rows are retained in the immutable ledger but migrated to CLOSED/VOID with reason `V631_US_WEEKLY_RESET`. They are not retroactively reinterpreted as weekly calls.

### International screen

The foreign SHORT panel is removed. The screen is ordered as:

1. **U.S. WEEKLY LONG — STOCKS + ETFs**
2. **GLOBAL → INDIA OVERNIGHT MAP — INDIA LONG / INDIA SHORT**
3. Closed / Resolved audit ledger

During the International view the market pill reflects the U.S. session rather than the NSE session, and the regime card identifies the U.S. weekly research mode.

### Global → India unchanged in horizon

Global → India continues to use major U.S./European/Asian indices, sector ETFs, selected global companies, commodities, DXY, USD/INR and volatility as evidence for the **next NSE session**. Signals remain provisional overnight and freeze under the existing 09:00 IST policy. India SHORT forecasts retain the user's 15:00 IST exit rule.

### Existing protections retained

- Static IP never gates recommendation generation; it gates Indian order execution only.
- Circuit same-day calls remain deadline-aware to 15:00 IST.
- Circuit 3:00 PM next-session LONG list remains frozen.
- Intraday SHORT keeps the hard 15:00 IST lifecycle.
- Weekly 10%, Monthly 50% and ETF 5% Indian books keep frozen-period target gates and are LONG-only for executable multi-session holdings; bearish horizon signals remain research-only.
- ₹20,000 maximum Indian order notional and ₹500 modeled stop-risk cap remain unchanged.
- Recommendation targets are forecasts/admission gates, never guaranteed returns.

## Useful APIs

```text
/api/international/board
/api/recommendations/INTERNATIONAL
/api/global/markets
/api/workers
/api/scan/status
/api/health
```

## Installation

```zsh
cd ~/Downloads
unzip -t PS_Scanner_Quant_v6.7.3.zip || exit 1
rm -rf PS_Scanner_Quant_v6.7.3
unzip -q PS_Scanner_Quant_v6.7.3.zip
cd PS_Scanner_Quant_v6.7.3
chmod +x install.sh
./install.sh
```

UI: `http://127.0.0.1:8765`


## v6.3.7 Morning Freeze
- Weekly/ETF research begins pre-open and freezes trade-ready slates from 09:20 IST on the first NSE session of the week.
- Monthly uses the same morning window; if an official monthly book is missing because of downtime/older bugs, a morning recovery freeze is allowed without lowering the 50% target gate.
- Recovery window ends at 12:00 IST. Existing frozen books are never replaced or backfilled.
- Same-morning repeated scans are telemetry, not independent evidence; publication no longer waits for 4-6 pseudo-independent observation buckets.
- Weekly missing fundamentals remain UNKNOWN and can only be compensated by stricter quantitative evidence; Monthly remains fundamentals-sensitive.
- Empty horizon tabs show research near-misses and gate reasons. Circuit Radar shows near-band WATCH names even when they are not yet deadline-qualified.
- International weekly history is separated from legacy daily/audit rows in the UI.
