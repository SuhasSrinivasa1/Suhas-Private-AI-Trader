# Private AI Trader 1.0 — Production MacBook Setup

This release is designed to run locally on a Mac. The browser UI, FastAPI backend, historical pattern engine, daily recommendation engine, and local LLM all run on the Mac. The only required paid external component is the user's active Groww Trading API subscription. The free news-risk check uses GDELT and the AI reviewer uses a local Ollama model.

## Important boundary

This software is decision support, not a profit guarantee. No model, backtest, AI agent, or historical pattern can guarantee future returns. The production objective is to improve discipline, consistency, risk control, and the quality of trade selection.

## 1. Requirements

- macOS 14 Sonoma or newer.
- Apple Silicon is recommended for local AI performance.
- Internet access for installation, Groww API data, and the free news-risk check.
- A Groww account with an active Groww Trading API subscription.
- Enough free disk space for Homebrew packages and the selected local Ollama model.

## 2. Extract the release ZIP

Move the ZIP to a permanent folder before installation. A recommended location is:

```bash
mkdir -p "$HOME/PrivateAITrader"
```

Extract the ZIP and place the `Suhas-Private-AI-Trader` folder inside that directory.

Then open Terminal and enter the extracted folder, for example:

```bash
cd "$HOME/PrivateAITrader/Suhas-Private-AI-Trader"
```

## 3. Install the complete Mac environment

Run:

```bash
bash INSTALL_MAC.command
```

The installer will:

- verify macOS compatibility;
- request Apple Command Line Tools when missing;
- install Homebrew when missing;
- install Git, GitHub CLI, Python 3.12, Node.js, jq, shellcheck, and Ollama;
- create an isolated Python environment in `backend/.venv`;
- install pinned runtime and development dependencies;
- configure Ollama for local-only operation;
- select a local model based on available Mac memory;
- download the selected local model;
- create local runtime configuration files that are excluded from Git;
- run syntax checks, tests, rule-contract checks, and secret scans;
- install the daily 07:45 local scheduler and login start hook.

### First-run Apple Command Line Tools behavior

On a brand-new Mac, the first installer run may open the Apple Command Line Tools installer and exit. Complete Apple's installation, then run again:

```bash
bash INSTALL_MAC.command
```

## 4. Activate the Groww Trading API

Inside Groww:

1. Ensure the Trading API subscription is active.
2. Open the Groww Cloud API Keys page.
3. Generate an API Key and Secret.
4. Complete the daily approval step when Groww requires it for the API-key/secret flow.

Do not paste your Groww password, OTP, PIN, recovery code, bank password, or card details into this application.

## 5. Store Groww API credentials in macOS Keychain

From the project folder, run:

```bash
bash CONFIGURE_GROWW.command
```

Enter only the Groww Trading API key and API secret when prompted.

The credentials are stored in macOS Keychain under the service name `SuhasPrivateAITrader`. They are not written to the browser, source code, ZIP file, GitHub repository, or local AI prompt.

## 6. Start the production application

Run:

```bash
bash START_TRADER.command
```

The application opens at:

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

## 7. Verify Groww before using recommendations

Open **Broker Connections** and select **TEST READ-ONLY CONNECTION**.

The expected result is:

- configured: yes;
- connected: yes;
- credential source: `macos_keychain`;
- holdings count returned;
- positions count returned.

If authentication fails, first verify Groww's required daily API approval and then use **RECONNECT**.

## 8. Generate the first daily six-month analysis

Open **Daily Recommendations** and select:

**REFRESH 180-DAY ANALYSIS**

The engine will:

1. Fetch up to 180 days of daily Groww candles for the configured liquid NSE universe.
2. Score six-month trend, moving-average structure, multi-horizon momentum, realized volatility, maximum drawdown, consistency, range position, and volume behavior.
3. Run a free GDELT news-risk check on the highest-ranked historical candidates.
4. Produce a daily score and one of:
   - `WATCH_FOR_LIVE_CONFIRMATION`
   - `WAIT`
   - `AVOID`
5. Save the daily snapshot locally under `.runtime/`.

A watchlist entry is not a live BUY instruction.

## 9. Use the local AI daily brief

In **Daily Recommendations**, select **AI DAILY BRIEF**.

The local Ollama model receives only the deterministic watchlist snapshot. It can summarize:

- strongest six-month patterns;
- major risks;
- relative ranking;
- what live confirmation is still required.

The LLM cannot:

- invent a live price;
- change a WAIT into a BUY;
- remove a risk veto;
- access Groww credentials;
- place an order.

## 10. Daily operation

The installer creates a macOS LaunchAgent that:

- checks the app at login;
- starts the local services without opening a browser;
- triggers again at 07:45 local Mac time.

The backend daily engine generates the current day's production watchlist after 07:50 IST when Groww is configured.

Recommended operating routine:

- 08:00 IST: review the generated daily watchlist and overnight context.
- 09:20 IST: review opening conditions.
- 09:25 IST onward: use the live scanner and current data.
- After 11:00 IST: do not lower standards simply because activity slows.
- After market: review journal entries, skips, missed moves, and rule adherence.

## 11. Live execution

Live order execution is disabled by default:

```text
GROWW_LIVE_EXECUTION_ENABLED=false
```

Keep it disabled until:

- Groww read-only authentication is stable;
- holdings and positions are correct;
- live quotes are correct;
- six-month analysis is completing;
- the daily watchlist is correct;
- the live scanner behaves correctly during market hours;
- the Mac validation checklist is complete.

When live execution is deliberately enabled, the backend still requires:

- market-session check;
- active BUY state;
- unexpired signal;
- fresh server-side re-scan;
- minimum confidence;
- anti-chase validation;
- risk-sized quantity;
- explicit human confirmation in the browser.

Automatic linked exit-order automation remains disabled in this release. Target and stop values are decision-support levels and must not be mistaken for guaranteed broker-side protection.

## 12. Stop the application

```bash
bash STOP_TRADER.command
```

## 13. Logs and troubleshooting

Logs are stored under:

```text
.runtime/logs/
```

Run the Mac doctor:

```bash
bash scripts/mac/doctor.sh
```

Run the full local verification suite:

```bash
bash scripts/verify.sh
```

## 14. Remove Groww credentials

```bash
bash scripts/mac/remove_groww_credentials.sh
```

## 15. Remove the daily scheduler

```bash
bash scripts/mac/uninstall_daily_scheduler.sh
```

## 16. Source recovery

GitHub remains the source of truth. The production ZIP is generated from the validated Git commit and contains no `.git` directory, no broker credentials, and no local runtime data.
