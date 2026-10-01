# PS Scanner v6.7.3 Architecture Audit

## Scope

v6.7.3 is an operational hardening release. It does not change trading or research policy.

## Static-IP lifecycle

The UI consumes cached execution readiness, while actual order preview and submission perform live verification. After a process restart, the cached public IP could remain unknown because the background broker probe refreshed authentication only.

v6.7.3 moves public-IP refresh into the independent broker-probe worker. Health remains passive and network-free. Public-IP lookup uses a primary and fallback provider and records the selected provider plus lookup errors in cache telemetry.

This changes only availability of cached readiness information. It does not weaken the execution requirement: preview/submit still require a live Static-IP match.

## Health latency

Health previously composed several bounded DB helpers. Each helper was individually bounded, but sequential connection attempts under write contention could accumulate enough latency to force validator retries.

v6.7.3 uses one bounded SQLite connection for:
- recent health events;
- recommendation counts;
- 24-hour decision counts;
- current-day manual order count;
- cached system-state keys;
- fundamental snapshot aggregate;
- event aggregate.

The rest of health is in-memory/cached: worker status, broker status, Static-IP cache, history-pacer cache, sector cache and execution readiness projection.

## Broker-position reconciliation

The hard block is intentionally retained. Groww exposes both total position quantity and net carry-forward quantity. Current-session exposure remains:

`session_quantity = quantity - net_carry_forward_quantity`

v6.7.3 adds raw credit/debit/carry-forward fields and explicit mismatch classification to make the reason inspectable without changing the decision.

## Invariants

- broker/local session mismatch remains fail-closed;
- missing Static-IP evidence never unlocks execution;
- health never performs external network I/O;
- recommendation generation remains independent of Static IP;
- full NSE breadth and all existing safety gates remain unchanged.
