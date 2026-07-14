# Private AI Trader 1.0 Production Release

## Production additions

- No preloaded sample trade values in the production UI.
- Production backend entry point: `backend/production_main.py`.
- Groww credentials resolved from macOS Keychain with environment fallback only for CI/advanced manual use.
- Read-only Groww connection verification and reconnect controls.
- Six-month pattern agent using a rolling 180-day Groww daily-candle window.
- Pattern scoring for trend, moving-average structure, momentum, consistency, volatility, drawdown, range position, and volume behavior.
- Free GDELT news-risk checks with fail-closed handling for live BUY decisions.
- Daily ranked watchlist with `WATCH_FOR_LIVE_CONFIRMATION`, `WAIT`, and `AVOID` states.
- Local Ollama AI daily briefing over deterministic recommendations.
- Daily 07:45 macOS scheduler and login start hook.
- macOS Keychain Groww credential configuration command.
- Production release packaging in GitHub Actions.
- Runtime dependency vulnerability audit is a release gate.

## Deliberate boundaries

- No guaranteed-profit claim.
- No automatic conversion of a premarket watch item into a BUY.
- No LLM authority over deterministic trade state.
- No broker passwords, OTPs, PINs, recovery codes, TOTP seeds, or API secrets in the frontend.
- No automatic linked stop/target exit orders in this release.
- Live execution remains disabled by default until physical-Mac and broker validation are complete.
