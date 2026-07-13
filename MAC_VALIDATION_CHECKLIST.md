# Physical Mac and broker validation checklist

This checklist must be completed on the actual MacBook Pro. Repository-level tests cannot prove hardware performance, Safari behavior, local Ollama performance, or live broker connectivity.

## A. Mac installation

- [ ] macOS 14 Sonoma or newer confirmed.
- [ ] Apple Command Line Tools installed.
- [ ] Homebrew installed and available in a fresh Terminal session.
- [ ] `git`, `gh`, `python3.12`, `node`, `jq`, `shellcheck`, and `ollama` available.
- [ ] GitHub authentication completed with `gh auth login`.
- [ ] Private repository cloned successfully.
- [ ] `bash scripts/mac/bootstrap.sh` completes successfully.
- [ ] `make doctor` reports zero failures.
- [ ] `make verify` passes.

## B. Safari and local frontend

- [ ] `make start` opens `http://127.0.0.1:8080`.
- [ ] Dashboard loads without a JavaScript error.
- [ ] Navigation works for Dashboard, Trade Evaluator, GTT Planner, Portfolio, Trade Journal, Broker Connections, and Privacy & Settings.
- [ ] The layout works in Safari at desktop width.
- [ ] The layout remains usable when the browser window is narrow.
- [ ] Local portfolio entries persist after browser refresh.
- [ ] GTT plans persist locally after browser refresh.
- [ ] Journal entries persist locally after browser refresh.
- [ ] Clear-all local data removes local portfolio, GTT, journal, evaluator, skipped-signal, and AI settings.

## C. Deterministic evaluator

- [ ] Valid sample returns BUY.
- [ ] Stale quote returns WAIT.
- [ ] Missing news/technical/portfolio confirmation returns WAIT.
- [ ] Insufficient independent source count returns WAIT.
- [ ] Reward/risk below 2.0 returns WAIT.
- [ ] Position risk above 1% returns WAIT.
- [ ] Chase above 1.5% returns WAIT.
- [ ] Manual live-execution request remains blocked by default.
- [ ] Short/SELL setup enforces target < entry < stop.

## D. Local GTT planner

- [ ] Invalid price structure is rejected.
- [ ] Reward/risk below the configured minimum is rejected.
- [ ] Portfolio risk above the configured maximum is rejected.
- [ ] Valid plan saves locally.
- [ ] Saved plan clearly states that fresh revalidation is required.
- [ ] No broker GTT request is sent.

## E. Trade journal and missed-trade rule

- [ ] Missed trade can be recorded with market context and lesson.
- [ ] “Trent rule” is visible.
- [ ] Journal does not create or submit an order.
- [ ] A missed trade is treated as a postmortem, not a reason to bypass anti-chase rules.

## F. Local AI

- [ ] Ollama API is reachable only on the expected local interface.
- [ ] Selected model is installed.
- [ ] Privacy & Settings reports the model as ready.
- [ ] AI REVIEW returns an explanation for a selected opportunity.
- [ ] AI output explicitly preserves the deterministic state.
- [ ] AI cannot create a broker request.
- [ ] AI never receives broker credentials or secrets.
- [ ] Local model performance is acceptable on the actual Mac hardware.

## G. Groww read-only validation

Keep:

```text
GROWW_LIVE_EXECUTION_ENABLED=false
```

until this entire section passes.

- [ ] Official API credentials are stored only in `backend/.env`.
- [ ] `backend/.env` remains ignored by Git.
- [ ] Authentication succeeds.
- [ ] Holdings retrieval succeeds.
- [ ] Positions retrieval succeeds.
- [ ] Quote retrieval succeeds.
- [ ] Dynamic scanner obtains current NSE data.
- [ ] Scanner universe size is correct.
- [ ] Market regime calculation updates.
- [ ] BUY/WATCHING/WAIT opportunities are produced from current data.
- [ ] News remains neutral if no approved provider is connected.
- [ ] No provider data is fabricated.

## H. Scanner and risk-veto validation

- [ ] Dynamic universe is not limited to a manually fixed watchlist.
- [ ] Coarse scan ranks candidates.
- [ ] Deep scan evaluates top candidates.
- [ ] Weak market regime can veto a long BUY.
- [ ] Excessive spread can veto a BUY.
- [ ] Excessive intraday range can veto a BUY.
- [ ] Portfolio concentration can veto a BUY.
- [ ] Negative news score can veto a BUY when a real provider is eventually connected.
- [ ] Risk-sized quantity is at least one share before BUY can pass.
- [ ] BUY alert expires after the configured validity window.
- [ ] Skipped signals do not immediately re-alert in the same browser session.

## I. Current-time and live-price discipline

- [ ] Asia/Kolkata routine clock is correct.
- [ ] Weekend review mode appears on weekends.
- [ ] 08:00 call-sheet stage is correct.
- [ ] 09:20 recheck stage is correct.
- [ ] 09:25 active-revalidation stage is correct.
- [ ] Post-11:00 slowdown advisory appears without relaxing risk rules.
- [ ] Post-market review stage appears after the configured session window.
- [ ] Actionable opportunities use fresh current quotes.
- [ ] Stale quotes are rejected.

## J. Pre-live execution gate

Do **not** enable live execution until all previous sections pass.

Then perform a separate, deliberate review of:

- [ ] live-execution environment flag;
- [ ] market-session enforcement;
- [ ] human confirmation dialog;
- [ ] recommendation expiry;
- [ ] fresh server-side rescan;
- [ ] confidence threshold recheck;
- [ ] anti-chase recheck;
- [ ] quantity recheck;
- [ ] order type, product, exchange, and validity mapping;
- [ ] broker response handling;
- [ ] failure and timeout behavior;
- [ ] duplicate-order prevention strategy;
- [ ] exit/stop handling strategy.

## Current live-execution limitation

The application can submit a guarded intraday BUY only when explicitly enabled, but linked automatic target/stop exit orders are not yet enabled. Target and stop are currently protective levels shown to the user, not guaranteed linked broker orders.

That limitation must remain visible and understood before any real-money use.
