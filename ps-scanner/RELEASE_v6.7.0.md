# PS Scanner Quant v6.7.0 — Production Integrity, Replay & Execution Attribution

v6.7.0 completes the production-hardening agenda on top of the v6.6.1 lifecycle/frozen-identity work. It deliberately does **not** add more live strategy families or loosen any recommendation threshold.

## Execution integrity

- Manual order preview and submit remain separate, explicit user actions.
- The execution path now performs a live broker-position reconciliation and hard-blocks new orders when PS Scanner's current-session filled quantity differs from Groww's net current-session position.
- Intraday SHORT execution requires a successful live Groww MIS margin requirement check for the proposed SELL order. A missing/failed permission quote fails closed.
- Available broker margin is checked against the proposed order's required margin.
- The existing live bid/ask spread and circuit-limit protections remain in force.
- The execution-only net-edge reserve now combines the recommendation's gross target, Groww's quoted proposed-leg charges, a conservative second-leg fee reserve, current spread and configurable two-leg slippage reserve. If the expected net edge is not above the configured hurdle, manual execution is blocked. This does not remove the research recommendation from the ledger.
- Decision price/time, submit time, acknowledgement time, fills, decision slippage, limit slippage and decision-to-first-fill latency are persisted separately from recommendation performance.

## Observability and evidence

- Every completed equity scan is persisted to `scan_runs` with full-universe count, actual scan scope, processed count, rejection funnel and strongest near misses.
- `/api/diagnostics/no-trade` makes the distinction between genuine no-qualified-opportunity evidence, incomplete search, data not ready and downstream publication/execution conditions explicit.
- Performance supports `time_bucket` and `behavior_cluster` groupings. These cohorts remain research-only until minimum sample, Wilson confidence width, positive expectancy and profit-factor requirements are met. There is no automatic activation.
- Signal-quality statistics stay in the recommendation ledger. Execution-quality statistics stay in order/fill analytics. One cannot silently contaminate the other.

## Point-in-time audit and deterministic replay

- v6.7+ recommendation and candidate-decision rows carry a point-in-time audit envelope including release version, safe settings hash, selected policy settings, strategy versions/parameter hashes, feature snapshot hash, context timestamps, universe state and market snapshot metadata.
- The production replay endpoint re-evaluates the stored gate contract from stored inputs. It never fetches today's data to rewrite an old decision.
- Pre-v6.7 rows are labelled `LEGACY_PARTIAL`; missing historical context is not fabricated.

## Operational resilience

- The database backup worker uses SQLite's backup API.
- Each backup is restored into an isolated temporary database and must pass `PRAGMA quick_check` plus required-table verification.
- Backups are retained under the runtime data directory and never overwrite the live ledger during verification.
- Existing WAL, per-connection synchronous policy, busy timeout, watchdogs and fail-soft telemetry remain intact.

## Experiment governance

A persistent experiment registry records hypothesis, affected books, change summary, sample requirement, promotion criterion, rollback criterion, release version and status. The release seeds its own v6.7 production-integrity experiment so later analysis can distinguish architectural changes from strategy performance.

## Strategy policy

No new live strategy is introduced by this release. The existing Champion/Challenger, walk-forward, untouched holdout, live-shadow and multiple-testing controls remain authoritative. Time-of-day and behavior cohorts are diagnostic evidence only until they independently earn live use.

## New APIs

- `GET /api/diagnostics/no-trade`
- `GET /api/replay/decisions`
- `GET /api/execution/analytics`
- `POST /api/execution/positions/reconcile`
- `GET /api/experiments`
- `POST /api/experiments`
- `GET /api/maintenance/backups`
- `POST /api/maintenance/backup-now`

## Upgrade policy

The schema migration is additive. Existing recommendations, strategy evidence, settings, Groww credentials, history/cache files and order/fill records remain in the preserved runtime data directory during an in-place v6 upgrade.
