# Private AI Trader 2.0 — Production MacBook Setup

Production 2.0 runs locally on the Mac. The dashboard, FastAPI backend, Groww live-feed bridge, six-month pattern engine, continuous news engine, SQLite memory, local embeddings, local LLM, outcome tracker and exit agent all run on the Mac.

The only expected paid external component is the user's active Groww Trading API subscription. The default LLM and embedding models run locally through Ollama. The default Internet-news layer uses free sources.

## 1. Requirements

- macOS 14 Sonoma or newer.
- Apple Silicon recommended for local AI performance.
- Internet access for installation, Groww, and live news.
- Active Groww Trading API subscription.
- Sufficient disk space for Homebrew, the selected Ollama chat model, `embeddinggemma`, and the local trading database.

## 2. Extract the release ZIP

```bash
mkdir -p "$HOME/PrivateAITrader"
cd "$HOME/PrivateAITrader"
unzip "$HOME/Downloads/Suhas-Private-AI-Trader-Mac-Production-2.0.zip"
cd Suhas-Private-AI-Trader
```

## 3. Install the Mac environment

```bash
bash INSTALL_MAC.command
```

The installer verifies macOS, handles Apple Command Line Tools, installs Homebrew dependencies, creates `backend/.venv`, installs pinned Python dependencies, configures Ollama local-only, selects and downloads the chat model, downloads `embeddinggemma`, creates safe local runtime configuration, runs verification and installs the 07:45 local scheduler/login hook.

On a brand-new Mac, the first run may open the Apple Command Line Tools installer and exit. Complete the Apple installation, return to the project folder and run `bash INSTALL_MAC.command` again.

## 4. Configure Groww securely

Inside Groww, ensure the Trading API subscription is active, generate the API key and secret, and complete Groww's approval step whenever required. Then run locally:

```bash
bash CONFIGURE_GROWW.command
```

Enter the Groww Trading API key and API secret only in the local Terminal prompt. The secrets are stored in macOS Keychain under the service `SuhasPrivateAITrader`.

Do not paste passwords, OTPs, PINs, recovery codes, TOTP seeds, bank credentials, or broker API secrets into ChatGPT, the browser UI, GitHub, issues, logs or AI prompts.

## 5. Start Production 2.0

```bash
bash START_TRADER.command
```

Dashboard:

```text
http://127.0.0.1:8080
```

Backend health:

```text
http://127.0.0.1:8000/health
```

Production status:

```text
http://127.0.0.1:8000/api/production/status
```

## 6. Verify Groww read-only and the feed

Open **Broker Connections** → **TEST READ-ONLY CONNECTION**.

Verify:

- configured: yes;
- connected: yes;
- credential source: `macos_keychain`;
- correct holdings and positions counts;
- Groww Feed moves from `STARTING` to `LIVE`.

Also open **Live Intelligence** and confirm feed status, subscribed symbol count, market events during NSE hours, provider health and local memory counts.

## 7. Local database

Default database:

```text
~/Library/Application Support/SuhasPrivateAITrader/trader.db
```

Backups:

```text
~/Library/Application Support/SuhasPrivateAITrader/backups/
```

SQLite WAL memory stores sampled prices, six-month patterns, news, embeddings, signals, outcomes, LLM analyses, provider health, agent statistics and exit signals.

Default retention:

- price samples: 30 days;
- news: 365 days;
- LLM analyses: 180 days.

A local backup is created daily after 16:00 IST while the backend is running.

## 8. Automatic daily operation

The macOS scheduler starts/checks the application at login and at approximately 07:45. After 07:50 IST, the backend automatically generates the day's 180-day watchlist when Groww is available. The browser does not need to be open.

Recommended workflow:

- 08:00 IST: review daily intelligence and overnight/news context.
- 09:20 IST: opening-condition recheck.
- 09:25 IST onward: live event-driven scanner and current data.
- After 11:00 IST: maintain standards despite slower activity.
- After market: review journal, outcomes and rule adherence.

## 9. Continuous intelligence

During market hours, Groww Feed pushes live LTP events, the backend updates prices without browser refresh, material moves trigger deterministic re-evaluation, broad periodic scanning remains as discovery/fallback, and BUY alerts still require current live conditions and all risk rules.

The system intentionally does not poll REST endpoints every millisecond.

The backend also monitors Internet news automatically: priority symbols on a faster loop, broader universe on a rotating loop, GDELT as primary free discovery, best-effort Google News RSS failover, local URL deduplication, and automatic rescan/LLM analysis for new material news.

## 10. Local semantic memory and automatic AI

Ollama runs both the selected local chat model and `embeddinggemma` for local embeddings. New headlines can be embedded locally and semantically similar historical local news can be retrieved.

Automatic local LLM analysis is triggered for material events such as a new BUY transition, signal-state changes, material new news and the daily watchlist. The LLM is not called for every price tick.

## 11. Outcome learning

The local engine records outcomes at 15, 30 and 60 minutes. Agent accuracy is calculated locally. After enough outcomes, agent weight multipliers can move only within 0.75x–1.25x.

These never self-modify: max risk per trade, minimum reward/risk, market-time rules, anti-chase rules, human confirmation requirements and execution safety boundaries.

## 12. SELL / exit intelligence

Open **Live Intelligence** → **SELL / exit intelligence**. The exit engine can show `HOLD`, `BOOK_PARTIAL_REVIEW`, `TRIM_15`, or `REVIEW_SELL`.

Live execution remains disabled while:

```text
GROWW_LIVE_EXECUTION_ENABLED=false
```

When deliberately enabled after validation, a SELL still requires explicit human confirmation, market-session check, available Groww quantity, fresh Groww quote and fresh pattern/news revalidation. The 3% booking reference is review-only; the 5% rule can propose at most an approximately 15% trim.

## 13. Diagnostics

```bash
bash scripts/mac/doctor.sh
bash scripts/verify.sh
```

Do not enable real-money execution until the physical Mac, Safari, local Ollama performance, read-only Groww authentication, holdings, positions and live feed have all been validated.
