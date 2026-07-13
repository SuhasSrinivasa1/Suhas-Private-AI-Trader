# Trading Rules and Feature Contract

This document is the human-readable companion to `config/trading_rules.json`. The JSON file is the machine-readable source of truth for tests and future integrations.

## 1. Non-negotiable safety rules

1. Paper mode is the default.
2. Live execution is disabled unless it is explicitly enabled in the backend environment.
3. A human confirmation click is required before any live order submission.
4. Every live order must be revalidated on the backend using a fresh quote immediately before submission.
5. A stale signal, stale quote, changed market regime, new risk veto, excessive chase, invalid quantity, or out-of-session request must be blocked.
6. A local or cloud LLM is advisory only. It cannot change BUY / SELL / WAIT, remove a risk veto, or submit an order.
7. Passwords, OTPs, PINs, TOTP seeds, recovery codes, broker secrets, API secrets, bank credentials, and withdrawal-enabled secrets must never be stored in frontend code, browser storage, logs, Git, or GitHub.

## 2. Live-data discipline

- Use the current market time and a fresh live quote before an actionable recommendation.
- Maximum quote age: 120 seconds.
- BUY alert validity: 20 seconds by default.
- At least two independent confirmation sources are required when a decision claims external confirmation.
- News, technical setup, and portfolio exposure are mandatory checks.
- If a news provider is not connected, news stays neutral. The application must never invent headlines or sentiment.

## 3. Risk and anti-chase rules

- Maximum risk per trade: 1% of portfolio value.
- Minimum reward/risk ratio: 2.0.
- Maximum chase distance: 1.5% beyond the reference level.
- Maximum position value: 20% of portfolio value.
- Maximum spread: 0.35% for the configured intraday profile.
- Maximum intraday range for a new long setup: 7% by default.
- BUY confidence threshold: 72.
- WATCHING threshold: 58.
- Missing a move is not a reason to weaken the anti-chase rule.

## 4. Intraday operating routine

These are workflow checkpoints, not guarantees of a trade:

- 08:00 IST: pre-market call sheet.
- 09:20 IST: pre-open recheck.
- 09:25 IST: opening revalidation using current market data.
- Opening minutes: use extra caution because conditions can change rapidly.
- 11:00 IST onward: show a slowdown advisory; do not assume the market is inactive.
- A stock-specific instruction such as “wait until 09:45” is a temporary trade note, not a permanent global rule.

## 5. Profit discipline

The user preference defaults are:

- A 1% profit can be acceptable for an intraday or short-swing trade.
- 3% is the default base profit-booking reference.
- At 5% profit, a planning rule may suggest trimming 15% of the quantity.
- These are planning and alert defaults only. Automatic exit-order placement is disabled until an explicit, tested exit-order workflow is implemented.

## 6. Dynamic scanner contract

The automatic scanner is not limited to a fixed watchlist.

It performs:

1. Dynamic liquid-universe coarse scan.
2. Deep scan of the strongest candidates.
3. Multi-agent scoring using momentum, technical structure, liquidity, order flow, market regime, news context, and portfolio exposure.
4. A separate risk veto that can block a high score.
5. Ranked BUY / WATCHING / WAIT output.
6. Expiring BUY alerts.
7. Server-side revalidation before live execution.

Default scanner settings:

- Scan interval: 15 seconds.
- Deep-scan candidates: 10.
- Displayed opportunities: 8.
- Signal validity: 20 seconds.

## 7. GTT planning rule

A local GTT planner may save proposed entry, target, stop, quantity, and notes in the browser.

- It does not submit a broker GTT order.
- It must validate price relationships and risk before saving.
- A saved GTT plan must be revalidated with current live data before any future broker submission feature can use it.

## 8. Missed-trade / “Trent mistake” rule

When a move is missed, record:

- the symbol;
- the time and market context;
- the entry that was considered;
- which rule or delay blocked the entry;
- whether the decision was correct given the information available at the time;
- what process improvement is possible without weakening risk controls.

The system must not convert regret into a chase entry.

## 9. Market capability boundary

Manual evaluator and local portfolio support:

- NSE
- BSE
- NASDAQ
- NYSE

Automatic live scanner today:

- NSE through the configured Groww backend.

U.S. live scanning or execution must remain disabled until an approved market-data source and broker integration are explicitly added and tested.

## 10. Research-source registry

The research workflow should consider the user-specified source set when data is legally and technically available:

### Screeners and market research

- TradingView
- Economic Times
- Reuters
- Investing.com
- Moneycontrol
- Screener.in
- MarketsMojo
- Tickertape
- TipRanks
- ChartInk

### News

- Yahoo Finance
- Economic Times
- Moneycontrol
- CNBC
- CNBC-TV18
- Reuters

The application must use official, licensed, or explicitly permitted APIs/feeds. A provider name in the registry does not mean the app is currently connected to that provider.

## 11. Local AI rule

The Mac-local model may:

- explain a deterministic recommendation;
- summarize the strongest evidence;
- identify risks and missing data;
- state invalidation conditions;
- help write a post-trade review.

It may not:

- invent live prices or news;
- override deterministic rules;
- bypass a veto;
- request or receive broker secrets;
- place or approve an order.

## 12. Source of truth

- Machine-readable rules: `config/trading_rules.json`
- Runtime backend safety checks: `backend/trading_policy.py` and `backend/main.py`
- Local browser settings: convenience only; they do not override backend live-execution policy.
