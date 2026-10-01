# PS Scanner Quant v6.7.3 — Execution Cache & Health Latency Hardening

v6.7.3 is a narrow final reliability pass based on the successful v6.7.2 production install.

## Static-IP cache reliability

The v6.7.2 production output showed a configured Static IP with a null cached detected IP. Research was unaffected, but the UI uses cached execution readiness to decide whether order buttons may be shown.

v6.7.3 therefore:
- refreshes public-IP status in the independent background broker-probe worker;
- keeps `/api/health` network-free;
- uses the existing primary public-IP lookup plus an independent fallback;
- records provider, cache age, state and last lookup error in passive telemetry;
- still performs a live Static-IP verification again at order preview/submit time.

No order can be submitted solely because a cached value says the IP matches.

## Health latency

The successful v6.7.2 validator needed retries before receiving health. v6.7.3 consolidates health's SQLite work into one bounded connection/snapshot and derives execution readiness without additional DB or network calls.

The health route remains passive and fail-soft. A temporarily busy database produces degraded telemetry rather than blocking the service.

## Position reconciliation

Groww's documented positions payload exposes total `quantity` and `net_carry_forward_quantity`. PS Scanner continues to treat their difference as current-session position quantity.

v6.7.3 makes this auditable by persisting:
- credit quantity;
- debit quantity;
- carry-forward credit/debit quantities;
- the exact session-quantity formula;
- an explicit mismatch classification such as `EXTERNAL_CNC_SESSION_POSITION`.

The safety behavior is unchanged: a verified broker/local current-session mismatch remains a hard execution block.

## Non-changes

No recommendation thresholds, full-NSE breadth rules, frozen-book identity rules, publication windows, target feasibility, execution spread/margin gates, ₹20,000 notional cap, ₹500 stop-risk cap, learning rules, or Champion/Challenger rules change in this release.
