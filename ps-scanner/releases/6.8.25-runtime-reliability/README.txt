PS Scanner 6.8.25 — Runtime Reliability & Data-Plane Resilience
==================================================================

This is an installer package for an existing PS Scanner 6.8.24 installation.
It does not replace the application database and does not weaken any trading safety gate.

Included changes
----------------
1. Runtime heartbeat + durable daily session ledger.
   Detects SYSTEM_SUSPEND_OR_LONG_PAUSE_DETECTED after a process resumes from a
   >=120-second suspension/stall. One compact daily row is updated in place; it does
   not create an unbounded high-frequency heartbeat table.

2. Passive data-quality telemetry:
   GET /api/runtime/reliability
   GET /api/data-quality
   GET /api/runtime/session-ledger?limit=14

   Reports full-market LTP coverage, Intraday/Daily history coverage, latest Intraday
   scan, recent Groww/history warnings and the current history-pacer status.

3. Website runtime/data-quality strip.
   Adds only external JS/CSS. No recommendation or execution button semantics change.

4. Adaptive historical-data pressure pacing.
   Extends the existing Groww historical-candle pacer after HTTP 429 pressure.
   Applies only to historical candles. Live quote/order traffic is not routed through
   this added delay.

5. Bounded read-only compact support exporter.
   Excludes raw history caches, large institutional directories and huge feature/audit
   blobs from the default compact diagnostic archive. It never deletes recommendation
   history.

Intentionally unchanged
-----------------------
- Static IP execution enforcement
- Groww broker source-of-truth reconciliation
- Market hours and NSE holiday blocking
- Manual preview/confirm execution model
- Preview expiry/single-use/price-drift protection
- Order sizing/risk limits
- Book execution/research-only policy
- Recommendation qualification thresholds
- Publication freshness
- Circuit Next-Day remains RESEARCH_ONLY

Intentionally deferred
----------------------
- No automatic SQLite pruning or destructive DB compaction.
- No blind pandas pct_change(fill_method=None) rewrite; that needs installed-pipeline
  output regression tests because missing-value semantics can change.
- No automatic macOS pmset/caffeinate policy changes.
- No full-market Groww LTP transport rewrite in this release; 6.8.24 already has a
  priority-quote lane and broker transport changes need an exact installed-source
  regression pass.

Install
-------
From this directory:

  python3 apply_runtime_6825.py --dry-run

If dry-run passes:

  python3 apply_runtime_6825.py

Restart the backend once, then:

  ./verify_6825.sh

The default app root is:
  ~/Applications/PS_Scanner_Final

You can override it:
  python3 apply_runtime_6825.py --app-root /path/to/PS_Scanner_Final --dry-run

The installer requires:
- installed VERSION 6.8.24 (or an already-installed 6.8.25 for idempotent validation)
- V6824_CANONICAL_BOOK_EXECUTION_AND_PRESENTATION_POLICY
- V6824_PREVIEW_PRICE_DRIFT_REVALIDATION
- working /static FastAPI mount

Before an actual apply it writes a tar.gz backup under:
  data/hotfix_backups/

Compact support export after install:
  ~/Applications/PS_Scanner_Final/scripts/export_support_6825.py

Safety note
-----------
Execution may remain LOCKED after this upgrade. That is expected whenever Static IP,
market-hours/holiday, broker reconciliation or another existing gate blocks execution.
Do not acknowledge broker positions or change safety settings merely to make the UI green.
