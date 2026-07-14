# Suhas Private AI Trader — Production 2.0

Private, Mac-first, always-on trading decision-support system for NSE trading. The application combines Groww market data, a rolling six-month pattern engine, continuous Internet news monitoring, local SQLite memory, local Ollama AI, deterministic risk rules, recommendation outcome tracking, bounded adaptive agent weights, and human-confirmed Groww BUY/SELL execution.

## Core architecture

Production 2.0 is event-driven:

1. **Groww Feed** pushes live market events for the configured NSE universe.
2. The backend updates in-memory prices and a sampled local price history.
3. Material price changes trigger deterministic re-evaluation instead of wasteful millisecond REST polling.
4. The continuous news engine checks priority symbols frequently and rotates through the broader universe.
5. New headlines are deduplicated into local SQLite memory.
6. Local Ollama embeddings create semantic news memory for similarity/RAG.
7. Material news or signal-state changes automatically trigger a local LLM explanation.
8. BUY/WAIT state remains deterministic; the LLM cannot override a veto or place an order.
9. Recommendation outcomes are measured at configured horizons and can adjust agent weights only within bounded limits.
10. Risk limits never self-modify.

The browser is a live dashboard. It is not responsible for refreshing market intelligence.

## Safety boundaries

- Paper/safe mode is the default.
- `GROWW_LIVE_EXECUTION_ENABLED=false` by default.
- BUY and SELL requests require an explicit human confirmation action.
- The backend performs fresh broker-side revalidation before an enabled live order.
- Stale, changed, chased, vetoed, invalid, over-quantity, or out-of-session orders are blocked.
- The local LLM is advisory only.
- No password, OTP, PIN, recovery code, TOTP seed, broker API secret, or bank credential is stored in the frontend or Git.
- Groww API credentials are stored in macOS Keychain.
- No profit is guaranteed.

## Production 2.0 features

### Always-on market intelligence

- Groww callback feed for live equity LTP events.
- Periodic REST scanner remains as broad discovery/fallback and deep revalidation.
- Dynamic liquid NSE universe.
- Event-triggered rescans on material price movement.
- Automatic WebSocket push to the browser; no manual browser refresh required.
- Provider-health monitoring and automatic Groww feed restart attempts.

### Continuous Internet news intelligence

- GDELT DOC 2.0 as the primary free news discovery source.
- Best-effort Google News RSS failover when the primary source is unavailable.
- Priority-symbol monitoring and broad-universe rotation.
- URL-level local deduplication.
- News sentiment/risk scoring.
- New material news can automatically rescore the affected stock.
- Missing required news dependencies fail closed for a fresh BUY.

### Local Mac memory

Default macOS database:

```text
~/Library/Application Support/SuhasPrivateAITrader/trader.db
```

Stored locally: sampled market prices, six-month patterns, news, local news embeddings, signals, 15/30/60-minute outcomes, local LLM analyses, provider health, agent performance and exit signals.

SQLite runs in WAL mode. Price samples are retained for 30 days by default, news for 365 days, and LLM analyses for 180 days. A local database backup is created daily after 16:00 IST.

### Six-month pattern agent

Uses rolling 180-day Groww daily candles and scores multi-horizon returns, moving-average structure, trend slopes, realized volatility, drawdown, positive-session consistency, recent-range position, volume behavior and recurring weekday edge. Historical results are cached locally.

### Local AI and semantic memory

- Ollama runs locally on the Mac.
- Chat model is selected based on available memory.
- `embeddinggemma` is installed for local semantic news memory.
- Automatic LLM triggers occur only on material events, not every price tick.
- Similar historical news can be retrieved from the local database and supplied to the local LLM.
- The LLM never receives Groww secrets and cannot execute orders.

### Outcome learning

Every stored signal can be evaluated at 15, 30 and 60 minutes. Agent accuracy is tracked. After sufficient outcomes, agent weight multipliers can move only within `0.75x` to `1.25x`. Risk rules, market-time rules, human confirmation and execution safeguards never adapt automatically.

### SELL / exit intelligence

The exit agent evaluates current Groww holdings/positions using current P&L, six-month pattern deterioration, current news risk and the 1%, 3% and 5% profit-discipline preferences.

Possible states:

- `HOLD`
- `BOOK_PARTIAL_REVIEW`
- `TRIM_15`
- `REVIEW_SELL`

No SELL occurs automatically. An enabled live SELL requires a human click, available-quantity validation, a fresh Groww quote and fresh pattern/news revalidation.

## Mac installation

Read `PRODUCTION_MAC_SETUP.md`. From the extracted release folder:

```bash
bash INSTALL_MAC.command
bash CONFIGURE_GROWW.command
bash START_TRADER.command
```

Open `http://127.0.0.1:8080`.

Diagnostics:

```bash
bash scripts/mac/doctor.sh
```

Full validation:

```bash
bash scripts/verify.sh
```

## Rule contract

- Human-readable rules: `TRADING_RULES.md`
- Machine-readable contract: `config/trading_rules.json`
- CI enforcement: `scripts/check_rules_contract.py`

The Production 2.0 contract enforces the always-on feed architecture, no browser-refresh dependency, local memory, local semantic embeddings, bounded outcome learning, continuous news, human-confirmed BUY/SELL and non-adaptive risk rules.

## Source and release integrity

GitHub is the source of truth. Release ZIPs are generated only after Linux, macOS, test, secret-scan, rule-contract, JavaScript, shell, dependency-consistency and dependency-vulnerability gates pass.
