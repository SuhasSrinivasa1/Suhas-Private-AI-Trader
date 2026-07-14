# Production 2.0 Architecture

## Data plane

```text
Groww Feed callback ──► local event queue ──► in-memory prices ──► material-change detector
       │                                                         │
       └─────────────────────────────────────────────────────────► deterministic rescan

GDELT ──► news collector ──► dedupe ──► SQLite ──► local embeddings ──► semantic memory
   │             │                                                        │
   └─ failover ─► Google News RSS                                         ▼
                                                                    local Ollama analysis

180-day Groww candles ──► pattern engine ──► SQLite cache ────────────────┘

signals ──► outcome tracker ──► agent accuracy ──► bounded weight multipliers

holdings/positions + live price + pattern + news ──► exit agent ──► HOLD / TRIM / SELL REVIEW
```

## Why not every millisecond?

Network news sources and REST broker APIs are not millisecond market feeds. Blind millisecond polling would generate duplicates, throttling and delayed useful work. Production 2.0 instead uses:

- provider-supported Groww callback feed for market events;
- fast deterministic processing for price events;
- adaptive news polling by priority;
- local cache/database reuse;
- local LLM only for material events.

## Execution plane

```text
Recommendation
   ▼
Human confirmation
   ▼
Fresh server-side validation
   ▼
Market/session/risk/quantity/anti-chase checks
   ▼
Groww order API
```

The local LLM is outside the execution authority path.
