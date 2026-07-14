# Private AI Trader 2.0 Production Release

## Major upgrade: always-on event-driven intelligence

Production 2.0 replaces browser-driven/manual refresh with a backend intelligence service that remains active while the Mac application is running.

### Live market events

- Groww `GrowwFeed` callback integration for live NSE equity LTP events.
- Up to the configured universe can be subscribed through official exchange tokens.
- Material price changes trigger deeper deterministic rescans.
- The periodic REST scanner remains as broad discovery/fallback and fresh quote revalidation.
- Live events are pushed to the browser automatically through the local WebSocket.

### Continuous news intelligence

- Always-on priority-symbol and rotating-universe news loop.
- GDELT DOC 2.0 primary free provider.
- Best-effort Google News RSS failover when GDELT is unavailable.
- Local deduplication prevents repeated processing of the same URL.
- Material new headlines can trigger stock rescoring and automatic local LLM analysis.

### Local SQLite market memory

Production data is stored outside the repository by default at:

```text
~/Library/Application Support/SuhasPrivateAITrader/trader.db
```

The database stores sampled prices, patterns, news, embeddings, signals, outcomes, LLM analyses, provider health, exit signals and agent statistics.

- SQLite WAL mode.
- 30-day sampled-price retention by default.
- 365-day news retention by default.
- 180-day LLM-analysis retention by default.
- Daily local database backup after 16:00 IST.

### Local semantic memory

- `embeddinggemma` installed through Ollama.
- New headlines can be embedded locally.
- Similar historical local news can be retrieved with cosine similarity.
- Local RAG context is supplied to automatic event analysis without sending broker secrets to the LLM.

### Automatic local LLM triggers

The local LLM is invoked automatically for material events such as new BUY transitions, BUY/WAIT state changes, material new news and the daily watchlist. It is deliberately not called on every price tick.

### Recommendation outcome tracking and bounded learning

- Signal outcomes tracked at 15, 30 and 60 minutes.
- Agent directional accuracy stored locally.
- Agent weight multipliers remain neutral until enough outcomes exist.
- Adaptive multipliers are bounded to 0.75x–1.25x.
- Risk rules never self-modify.

### SELL / exit intelligence

- Current holdings and positions receive deterministic exit/trim analysis.
- 1%, 3%, and 5% profit-discipline preferences are incorporated.
- Strong negative news, pattern deterioration, or loss boundaries can escalate an exit review.
- No automatic SELL order.
- The 3% booking reference is review-only.
- The 5% rule can propose at most an approximately 15% trim.
- Enabled live SELL requires human confirmation, available-quantity checking, fresh Groww quote and fresh exit revalidation.

### Provider health and recovery

Health is tracked for market feed, Groww REST/historical data, news, local embeddings, local LLM and local database backup. The runtime retries a missing Groww feed instead of silently remaining blind.

## Deliberate boundaries

- No millisecond Internet polling.
- No LLM call on every market tick.
- No guaranteed-profit claim.
- No automatic BUY or SELL order from an AI agent.
- No self-modifying risk limits.
- No browser, GitHub, or LLM storage of Groww secrets.
- Live execution remains disabled by default until real Mac and real Groww validation are complete.
