# Suhas Private AI Trader

Private, Mac-first trading decision-support application for Indian and U.S. markets, with an automatic NSE intraday scanner, deterministic safety rules, local portfolio/GTT/journal tools, optional Groww connectivity, and a private local LLM reviewer.

## Safety status

- Paper mode is the default.
- Live Groww execution is disabled by default.
- A human confirmation click is required before a live order request.
- The backend re-runs the opportunity logic using a fresh quote before submitting an enabled live order.
- Stale, changed, chased, vetoed, invalid, or out-of-session orders are blocked.
- The local LLM is advisory only and cannot override BUY / SELL / WAIT logic, remove a risk veto, or place an order.
- Passwords, OTPs, PINs, TOTP seeds, recovery codes, API secrets, broker credentials, and bank credentials are forbidden in the frontend and Git repository.

## Current features

### Dashboard and automatic scanner

- Dynamic liquid NSE universe instead of a fixed watchlist only.
- Market-wide coarse scan followed by deep analysis of top candidates.
- Ranked `BUY`, `WATCHING`, and `WAIT` opportunities.
- Multi-agent scores for momentum, technical structure, liquidity, order flow, market regime, news context, and portfolio exposure.
- Independent risk-veto layer.
- Expiring BUY alerts.
- Live holdings/positions when the Groww backend is configured.
- Market/news panel that stays neutral when no approved news provider is connected.
- Asia/Kolkata routine clock for the 08:00, 09:20, 09:25, post-11:00, and post-market workflow checkpoints.

### Trade Evaluator

- Manual `BUY`, `SELL`, or `WAIT` evaluation.
- NSE, BSE, NASDAQ, and NYSE input support.
- Quote freshness check.
- Minimum confirmation-source check.
- Mandatory news, technical, and portfolio checks.
- Reward/risk, capital-risk, and anti-chase checks.
- Manual live-execution requests are blocked by default.

### GTT Planner

- Local-only proposed entry, target, stop, quantity, and note storage.
- Validates price structure, reward/risk, and portfolio risk before saving.
- Does **not** submit a broker GTT order.
- Every saved plan is marked for fresh validation before any future broker integration may use it.

### Portfolio

- Local browser portfolio for testing.
- Groww holdings and positions take priority when the backend is configured.
- No broker secrets are stored in browser storage.

### Trade Journal and missed-trade review

- Records entered, closed, skipped, missed, and rule-blocked opportunities.
- Captures market context, the rule/reason involved, and the lesson.
- Implements the “do not repeat the Trent mistake” process: study a missed move without weakening the anti-chase rule.

### Private local AI

- Runs through Ollama on the Mac.
- The bootstrap selects a model based on available memory, with an environment override when required.
- Receives only the selected machine-generated trade snapshot.
- Explains decision context, evidence, risks, missing data, and invalidation conditions.
- Cannot execute or approve a trade.

## Brand-new MacBook Pro setup

Start with:

```text
NEW_MAC_FIRST_RUN.md
```

After the repository is cloned, the full one-command bootstrap is:

```bash
bash scripts/mac/bootstrap.sh
```

It installs the reproducible Homebrew toolset, creates the Python environment, installs dependencies, configures Ollama for local-only use, selects and downloads a local model, creates safe local configuration files, and runs the verification suite.

Start the app:

```bash
make start
```

Stop the app:

```bash
make stop
```

Run the Mac health check:

```bash
make doctor
```

Run all repository validation:

```bash
make verify
```

The frontend opens at:

```text
http://127.0.0.1:8080
```

Backend health is available at:

```text
http://127.0.0.1:8000/health
```

## Repository rule contract

The complete workflow and safety rules are stored in two forms:

- `TRADING_RULES.md` — human-readable rules and feature contract.
- `config/trading_rules.json` — machine-readable contract validated by the test/verification pipeline.

The contract covers live-price freshness, market-time discipline, anti-chase behavior, mandatory checks, scanner settings, risk limits, paper/live boundaries, GTT planning, profit-discipline preferences, the intraday routine, missed-trade postmortems, source registries, and privacy restrictions.

## Default guardrails

- Maximum risk per trade: 1% of portfolio value.
- Minimum reward/risk: 2.0.
- Maximum chase distance: 1.5%.
- Maximum quote age: 120 seconds.
- Minimum independent confirmation sources: 2.
- Maximum position value: 20% of portfolio value.
- BUY confidence threshold: 72.
- WATCHING threshold: 58.
- Mandatory checks: news, technical setup, portfolio exposure.
- Live execution: disabled by default.

## Research-source registry

The rule contract records the user-specified research set, including TradingView, Economic Times, Reuters, Investing.com, Moneycontrol, Screener.in, MarketsMojo, Tickertape, TipRanks, ChartInk, Yahoo Finance, CNBC, and CNBC-TV18.

A provider name in the registry does **not** imply that the application is currently connected to that provider. Only official, licensed, or explicitly permitted APIs/feeds should be integrated. Until a provider is connected, the application must not invent its data or sentiment.

## Groww configuration

The Mac bootstrap creates:

```text
backend/.env
```

from the safe example file. Add official Groww API values only to the local `.env` file when ready:

```text
GROWW_API_KEY=
GROWW_API_SECRET=
```

Keep this disabled during paper validation:

```text
GROWW_LIVE_EXECUTION_ENABLED=false
```

`backend/.env` is ignored by Git and must never be committed.

## Development and CI

GitHub Actions validates the project on Linux and a GitHub-hosted macOS runner. Local verification checks:

- Python syntax.
- Canonical trading-rules contract.
- Secret-leakage patterns.
- JavaScript syntax for `app.js` and `features.js`.
- Bash syntax.
- Python tests.
- Shell lint when shellcheck is available.

The dependency audit is informational and does not automatically enable or change trading behavior.

## Important boundary

This project is decision-support software, not a guarantee of profit. The deterministic rules, data sources, broker integration, and physical Mac installation must be validated before any live-execution setting is considered.
