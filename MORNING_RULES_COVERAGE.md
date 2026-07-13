# Morning Rules and Feature Coverage Matrix

This matrix maps the trading workflow and feature decisions discussed for the Private AI Trader to the current Mac-first implementation.

Status meanings:

- **Implemented** — present in code and covered by repository validation where practical.
- **Implemented, physical validation pending** — code is present, but the actual MacBook Pro or real broker connection must still be tested.
- **Registered, provider integration pending** — the source or rule is recorded, but no unapproved scraping or fabricated data is used.
- **Deliberately disabled** — intentionally blocked until a safer, tested implementation exists.

| Requirement / rule | Status | Implementation |
|---|---|---|
| Brand-new Mac with no Git or development tools | Implemented, physical validation pending | `NEW_MAC_FIRST_RUN.md`, `Brewfile`, `scripts/mac/bootstrap.sh` |
| Apple Silicon and Intel-aware Mac setup | Implemented | Architecture/memory detection in `scripts/mac/bootstrap.sh` |
| macOS 14+ compatibility gate | Implemented | Bootstrap and doctor checks |
| Homebrew setup | Implemented, physical validation pending | Bootstrap uses official Homebrew install flow when missing |
| Git and GitHub CLI setup | Implemented, physical validation pending | `Brewfile`, first-run guide |
| Python 3.12 isolated environment | Implemented | `backend/.venv` created by bootstrap |
| Reproducible runtime dependencies | Implemented | Direct runtime versions pinned in `backend/requirements.txt` |
| Automatic dependency update monitoring | Implemented | `.github/dependabot.yml` |
| Mac start / stop / health workflow | Implemented | `scripts/mac/start.sh`, `stop.sh`, `doctor.sh`, `Makefile` |
| Double-clickable Mac launcher | Implemented, physical validation pending | `run-mac.command` |
| Safari / macOS UI compatibility | Implemented, physical validation pending | `mac.css`, request-timeout handling in `app.js` |
| Local-first storage | Implemented | Browser `localStorage` for local portfolio, GTT plans, journal, evaluator settings |
| No passwords, OTPs, PINs, recovery codes, TOTP seeds, API secrets, broker credentials, or bank credentials in the frontend | Implemented | Security rules, `.gitignore`, secret-leakage scan, backend-only `.env` |
| Paper mode default | Implemented | Rules contract and backend environment default |
| Live execution disabled by default | Implemented | `GROWW_LIVE_EXECUTION_ENABLED=false` |
| Human confirmation before an enabled live BUY | Implemented | Frontend confirmation plus backend checks |
| Server-side revalidation before an enabled live BUY | Implemented | Fresh `_deep_scan()` in `backend/main.py` |
| Current market-time check before live execution | Implemented | NSE session enforcement in backend |
| Fresh live quote requirement | Implemented | Signal expiry, quote-age policy, stale broker timestamp veto |
| Maximum quote age 120 seconds | Implemented | Rules contract and trading policy |
| BUY signal validity 20 seconds | Implemented | Scanner and execution path |
| Minimum two independent confirmation sources when external confirmation is claimed | Implemented | Evaluator and rules contract |
| Mandatory news check | Implemented as a rule; live provider pending | Evaluator/rules contract; live news stays neutral until a real provider is connected |
| Mandatory technical check | Implemented | Evaluator and scanner agents |
| Mandatory portfolio-exposure check | Implemented | Evaluator and scanner risk veto |
| Maximum 1% portfolio risk per trade | Implemented | Position sizing and risk checks |
| Minimum reward/risk 2.0 | Implemented | Evaluator, GTT planner, scanner target construction |
| Maximum chase 1.5% | Implemented | Evaluator and live-order revalidation |
| Maximum position value 20% | Implemented | Scanner risk sizing |
| Maximum spread 0.35% | Implemented | Risk veto |
| Maximum configured intraday range 7% | Implemented | Risk veto |
| BUY confidence threshold 72 | Implemented | Scanner policy |
| WATCHING threshold 58 | Implemented | Scanner policy |
| Dynamic market universe, not fixed watchlist only | Implemented | NSE universe coarse scan + deep scan |
| Market-wide coarse scan | Implemented | `coarse_rank()` and `_coarse_scan()` |
| Deep scan of strongest candidates | Implemented | `_deep_scan()` |
| Momentum agent | Implemented | Trading policy ensemble |
| Technical-structure agent | Implemented | Trading policy ensemble |
| Liquidity agent | Implemented | Trading policy ensemble |
| Order-flow agent | Implemented | Trading policy ensemble |
| Market-regime agent | Implemented | Broad-leader market-regime scoring |
| News-context agent | Hook implemented; provider pending | Neutral until approved feed is connected |
| Portfolio-exposure agent | Implemented | Exposure calculation and veto |
| Independent risk veto | Implemented | Can block a high-confidence candidate |
| Ranked BUY / WATCHING / WAIT opportunities | Implemented | Dashboard opportunity board |
| BUY alert popup | Implemented | Browser modal and audio attempt |
| BUY / SKIP actions | Implemented | Session skip state and guarded BUY path |
| Current live prices on dashboard | Implemented, broker validation pending | `latest_prices` backend state + periodic frontend hydration |
| Live Groww holdings | Implemented, broker validation pending | Official Groww backend call |
| Live Groww positions | Implemented, broker validation pending | Official Groww backend call |
| Current Groww SDK compatibility | Implemented | Groww 1.5.0 pin and current batch adapter with legacy fallback |
| Safe no-credentials startup | Implemented and tested | Scanner status `broker_not_configured` |
| Safe market-closed scanner state | Implemented | Scanner pauses outside configured NSE session |
| 08:00 IST pre-market call-sheet checkpoint | Implemented | IST routine clock/status |
| 09:20 IST opening recheck | Implemented | IST routine clock/status |
| 09:25 IST active revalidation | Implemented | IST routine clock/status |
| Opening-volatility caution | Implemented | IST routine guidance |
| Post-11:00 slowdown advisory | Implemented | IST routine guidance without relaxing thresholds |
| Temporary stock-specific wait instructions are not made permanent global rules | Implemented as rule design | Documented in `TRADING_RULES.md` |
| 1% profit can be acceptable | Implemented | Profit-discipline planner and rules contract |
| 3% base profit-booking reference | Implemented | Profit-discipline planner and rules contract |
| At 5% profit, consider trimming about 15% of quantity | Implemented as planning only | Profit-discipline planner and rules contract |
| Automatic sell order from profit rule | Deliberately disabled | Human planning only |
| Local GTT planning | Implemented | GTT Planner page |
| GTT price-structure validation | Implemented | Long/short entry-stop-target checks |
| GTT reward/risk validation | Implemented | Local GTT planner |
| GTT portfolio-risk validation | Implemented | Local GTT planner |
| Automatic broker GTT submission | Deliberately disabled | Requires separate tested broker workflow and fresh validation |
| Local portfolio entry/testing | Implemented | Portfolio page |
| Trade journal | Implemented | Trade Journal page |
| “Do not repeat Trent mistake” postmortem | Implemented | Journal guidance and canonical rule |
| A missed move must not weaken anti-chase rules | Implemented | Rules contract and journal guidance |
| Private free local LLM on Mac | Implemented, physical performance validation pending | Ollama integration |
| Local AI model selected by Mac memory | Implemented | `gpt-oss:20b`, `qwen3:8b`, or `qwen3:4b` policy |
| Local AI is advisory only | Implemented | Prompt and architecture boundary |
| LLM cannot override deterministic BUY / WAIT | Implemented | LLM outside execution path |
| LLM cannot remove a risk veto | Implemented | LLM outside execution path |
| LLM cannot place an order | Implemented | No order authority in local AI integration |
| TradingView registry | Registered, provider integration pending | Rules contract |
| Economic Times registry | Registered, provider integration pending | Rules contract |
| Reuters registry | Registered, provider integration pending | Rules contract |
| Investing.com registry | Registered, provider integration pending | Rules contract |
| Moneycontrol registry | Registered, provider integration pending | Rules contract |
| Screener.in registry | Registered, provider integration pending | Rules contract |
| MarketsMojo registry | Registered, provider integration pending | Rules contract |
| Tickertape registry | Registered, provider integration pending | Rules contract |
| TipRanks registry | Registered, provider integration pending | Rules contract |
| ChartInk registry | Registered, provider integration pending | Rules contract |
| Yahoo Finance registry | Registered, provider integration pending | Rules contract |
| CNBC registry | Registered, provider integration pending | Rules contract |
| CNBC-TV18 registry | Registered, provider integration pending | Rules contract |
| Never fabricate unconnected news/provider data | Implemented | Neutral-news policy and source registry rule |
| Manual NSE evaluation | Implemented | Trade Evaluator |
| Manual BSE evaluation | Implemented | Trade Evaluator |
| Manual NASDAQ evaluation | Implemented | Trade Evaluator |
| Manual NYSE evaluation | Implemented | Trade Evaluator |
| Automatic live NSE scanning | Implemented, broker validation pending | Groww backend |
| Automatic live U.S. scanning | Deliberately disabled | Requires approved live U.S. market-data and broker integration |
| Linked automatic target and stop exit orders | Deliberately disabled | Current BUY response explicitly states protective levels are not linked exit orders |
| Linux CI | Implemented and passing on validated commits | GitHub Actions |
| macOS 14 CI | Implemented and passing on validated commits | GitHub-hosted macOS runner |
| Secret scan in CI | Implemented | `scripts/check_no_secrets.py` |
| Rules-contract drift detection | Implemented | `scripts/check_rules_contract.py` |
| Python tests | Implemented | Backend test suite |
| Current and legacy Groww batch adapter tests | Implemented | `backend/test_groww_adapter.py` |
| Brand-new-Mac no-credentials safety tests | Implemented | `backend/test_backend_safety.py` |
| Dependency audit | Implemented | CI JSON audit artifact |
| Physical MacBook Pro bootstrap | Implemented, physical validation pending | Must be run on the actual laptop |
| Real Groww authentication and read-only sync | Implemented, physical/broker validation pending | Requires local official API credentials |
| Real-money live execution | Deliberately remains off | Must stay disabled until `MAC_VALIDATION_CHECKLIST.md` is complete |

## Intentional boundaries

The following are not missing features; they are safety gates:

1. **No unapproved scraping or fabricated provider data.** The requested research/news sources are registered, but each live integration must use an official, licensed, or explicitly permitted feed.
2. **No automatic broker GTT submission yet.** Local GTT planning is present; broker submission requires a separately tested official workflow and fresh validation.
3. **No linked automatic target/stop exit orders yet.** The current guarded live path can submit an explicitly enabled BUY, but protective levels are advisory until linked exit handling is implemented and tested.
4. **No automatic U.S. live scanner yet.** Manual U.S. evaluation is available, but automatic live scanning requires approved U.S. market data and broker connectivity.
5. **No claim of physical-Mac validation until it is actually run on the user's MacBook Pro.** Repository macOS CI is a strong compatibility check, but it does not replace testing the real hardware, Safari instance, Ollama performance, or local Groww credentials.
