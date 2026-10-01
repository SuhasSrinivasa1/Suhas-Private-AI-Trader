# PS Scanner v6.7.0 Architecture Audit

## Objective

v6.7.0 hardens the system around a simple principle: before adding more signal complexity, PS Scanner must be able to prove what it searched, why it acted or abstained, what the broker actually executed, and whether an old decision can be reproduced from the information recorded at that time.

The release therefore changes execution integrity, observability, replayability and operational controls. It does not change the existing hard research thresholds in order to increase recommendation counts.

## Data domains and sources of truth

| Domain | Source of truth | v6.7 rule |
|---|---|---|
| Recommendation outcome | `recommendations` | Signal quality, MFE/MAE and WIN/LOSS/MISS remain independent of order fills. |
| Candidate decision | `trade_decisions` | v6.7 rows carry pipeline verdict/stage plus point-in-time audit envelope. |
| Scan completeness | `scan_runs` + current scan state | Full universe, bounded scope and processed count are separate concepts. |
| Manual order intent | `orders` | Immutable local intent plus decision/submission timestamps and live permission snapshot. |
| Actual fills | `order_fills` | Broker fills are never inferred from recommendation prices. |
| Current execution exposure | Groww positions API | Broker position is source of truth; local mismatch blocks new execution. |
| Strategy promotion | Strategy Lab validation/shadow tables | Existing walk-forward/holdout/multiple-testing/live-shadow contract remains unchanged. |
| Operational recovery | SQLite backup set | A backup is healthy only after isolated restore verification. |
| Change attribution | `experiments` | Hypothesis/sample/promotion/rollback are explicit. |

## Why-No-Trade contract

A blank or short book is no longer allowed to collapse multiple explanations into one message. Diagnostics expose:

1. full research universe;
2. actual scan scope and processed count;
3. history/data readiness;
4. liquidity/freshness rejection;
5. strategy-evidence and score rejection;
6. target-feasibility rejection;
7. risk/trade-intelligence rejection;
8. publication-ready count;
9. strongest near misses and hard blockers;
10. completed-pass evidence where zero-live bootstrap is active.

The diagnostic principle is explicit: `NO_QUALIFIED_OPPORTUNITY`, `SEARCH_INCOMPLETE`, `DATA_NOT_READY` and an execution/software bottleneck are different states.

## Execution integrity contract

The normal research/publication engine does not depend on Static IP, broker margin or broker positions. Those controls belong to manual execution only.

At preview/submit time, execution requires:

- manual execution enabled;
- Groww connected;
- configured Static IP matching;
- valid trading session;
- daily manual-order budget available;
- LIVE recommendation on a supported venue;
- side/horizon and short-entry deadline policy;
- portfolio-correlation risk pass;
- live spread/circuit pass;
- current Groww-vs-local session position reconciliation;
- live proposed-order margin/MIS permission;
- available margin;
- positive modeled net edge after execution-cost reserve;
- non-zero quantity under the existing notional and stop-risk caps.

Preview data is not trusted at submit time: price/execution quality and broker permission are refreshed before the order is sent.

## Signal vs execution attribution

The recommendation ledger answers: **Was the signal useful?**

The execution ledger answers: **Did we implement that signal well?**

Order analytics therefore measure decision price, protected limit, average fill, decision slippage, limit slippage, decision-to-submit latency, submit-to-ack latency and decision-to-first-fill latency. Broker realized P&L is exposed as broker telemetry rather than rewriting recommendation outcomes.

## Point-in-time audit envelope

Prospective v6.7 decisions capture safe configuration/policy state, strategy versions, parameter hashes, feature hash, data/context timestamps, universe state and market-snapshot metadata. Secrets, auth material and network identifiers are deliberately excluded.

The envelope is prospective: v6.7 does not pretend that earlier releases captured evidence they did not capture.

## Production replay

The replay service uses stored candidate payloads and audit envelopes to repeat the production gate contract. It classifies legacy decisions as partial. It does not fetch present-day fundamentals/news/prices to "reconstruct" an old answer.

The replay layer is intentionally contract replay, not an unrestricted optimizer. Counterfactual strategy discovery remains in Strategy Lab shadow research.

## Cohort analytics

Opening (09:15–10:00), midday (10:00–14:00) and late-session (14:00–15:30) cohorts are available as performance groupings. Behavior clusters combine recorded regime, ATR-volatility bucket and recorded sector label.

These are **diagnostics, not new gates**. A cohort is only marked evidence-eligible when it has at least the configured sample minimum, sufficiently narrow Wilson interval, positive expectancy and profit factor above one. Even then `automatic_activation=False`; a governed experiment/strategy-validation step is required before live use.

## Backup/restore resilience

The backup worker creates an online-safe SQLite backup, restores it to a temporary independent database, runs `PRAGMA quick_check` and verifies required core tables. The live file is never replaced during validation. Failures appear in health state and do not masquerade as healthy backups.

## Safety invariants retained

- No recommendation is fabricated to meet a count.
- No stale quote is substituted to make an order executable.
- Weekly/Monthly overlapping frozen identity remains enforced by application logic and SQLite trigger.
- Static IP gates execution only.
- Strategy-family diversity remains advisory until validated out of sample.
- VOID rows remain audit/data-integrity rows, not trading wins/losses.
- Existing ₹20,000 maximum order notional and ₹500 modeled stop-risk cap remain unchanged.
- New cohort analytics cannot silently alter production selection.
