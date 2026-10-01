# PS Scanner handoff

Current source version: **6.7.3**.

The canonical source is this `ps-scanner/` directory. Runtime state is intentionally not committed. On a Mac installation, runtime state remains under `~/Applications/PS_Scanner_Final/data`, logs under `~/Applications/PS_Scanner_Final/logs`, and local credentials under the secure runtime data path.

## v6.7.3 execution-cache / health-latency hardening

v6.7.3 is the final reliability pass after the successful v6.7.2 production validation. The background broker probe now refreshes Static-IP state, public-IP detection has an independent fallback provider, the health route derives execution readiness from a single bounded SQLite snapshot plus in-memory caches, and broker-position mismatch telemetry explicitly records Groww's quantity-minus-carry-forward semantics. Position mismatches remain fail-closed.

## v6.7.2 bounded sanity / deep database verification

v6.7.2 is a narrow follow-up to v6.7.1. Runtime `/api/sanity` no longer performs an inline `PRAGMA quick_check` on the live production ledger. Runtime sanity uses a wall-clock-bounded SQLite progress handler and short connection timeouts. Deep database integrity remains mandatory during post-install validation through SQLite backup → isolated restore → `PRAGMA quick_check`, with an explicit long-running maintenance budget.

## v6.7.1 health/validation reliability

v6.7.1 is a narrow reliability patch on top of v6.7.0. It does not change recommendation selection, trading thresholds, target/stop logic, execution permission, or learning policy. It makes `/api/health` passive and bounded, prevents it from waiting behind the Groww history pacer lock, bounds cached execution-readiness DB reads, and fixes the post-install validator so the new diagnostics/execution/backup checks are actually initialized and retried.

## v6.7.0 production-integrity architecture

Start with `ARCHITECTURE_AUDIT_v6.7.0.md` and `RELEASE_v6.7.0.md`. The v6.6.1 audit remains the frozen-identity/search-exhaustion baseline. The central runtime lifecycle definition is `psscanner_quant/lifecycle.py`; historical analytics are in `psscanner_quant/analytics.py`.

v6.7.0 completes the production-integrity roadmap on top of v6.6.1. It adds execution-only broker permission checks, position reconciliation, decision-to-fill attribution, first-class no-trade diagnostics, deterministic stored-input production replay, point-in-time audit envelopes, verified SQLite backup/restore, experiment governance and evidence-gated time-of-day/behavior cohorts. No live recommendation threshold is loosened and cohort analytics do not auto-activate as trading gates.

v6.6.1 was a first-principles follow-up to the v6.6.0 restructure. It fixes four integrity gaps found by re-reading the implementation rather than trusting the prior handoff: Weekly/Monthly exclusion now follows overlapping frozen-period identity even after early closure; zero-live Intraday recovery accumulates complete-pass funnel evidence before it may claim no qualified opportunity; ETF missed-freeze recovery is bounded to the live NSE session; and every short-lived SQLite connection explicitly reasserts synchronous=NORMAL.

Active pages are now current-period views, not history views:
- Intraday: current NSE session only.
- Weekly: current relevant NSE week.
- Monthly: current relevant month.
- ETF: current relevant NSE week.
- Circuit Radar: current same-day session plus current next-session forecast lane.
- International: current relevant US weekly book plus current/next Global→India forecast session.
- Older rows remain in SQLite and are exposed through Performance & History, never deleted merely because they leave the active UI.

The v6.6.0 audit found and corrected two recommendation-volume accounting defects without weakening safety: strategy-family diversity was acting as an unvalidated publication veto in two layers, and Intraday scanned at score 72 but silently refused publication below 76. Family diversity is now advisory/shadow until validated out of sample. Intraday's effective threshold remains 76 but exists in exactly one visible funnel stage.

Weekly/Monthly symbol mutual exclusion is enforced both by the application transaction and SQLite INSERT/UPDATE triggers. Same-session Intraday and Circuit identities have deterministic rollover closure. International external-history transport remains subprocess-bounded with no stale fallback. Missed-freeze recovery never fabricates a five-name book.

Performance and learning treat WIN/LOSS/MISS as trading evidence and report VOID/data-integrity rows separately. Wilson confidence intervals are exposed so tiny samples cannot masquerade as established edge. Daily strategy decay excludes VOID rows.

Workers remain independent domain threads. Health/sanity use bounded snapshots; worker telemetry exposes state, timing, stage, progress, rejection counters, timeout/hung state, recovery state and watchdog restart count.

## Safety contract

Do not weaken hard risk, freshness, liquidity, data-quality, target-feasibility, execution-permission, Groww budget, stop-risk or order-safety gates to force recommendation counts. Never fabricate names, use stale prices, reconstruct hindsight books, replace frozen identities to improve results, or count VOID/data errors as wins.

Static IP is an order-execution control only. It must not gate recommendation research/publication.

## Validation

Run:

```bash
python -m unittest discover -s tests -v
python3 tools/post_install_validate.py
```

The dedicated `.github/workflows/ps-scanner-ci.yml` runs the regression suite on Ubuntu and macOS, validates embedded UI JavaScript and zsh syntax, and builds `PS_Scanner_Quant_v6.7.3.zip` only after tests pass.
