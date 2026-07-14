# Security Policy — Production 2.0

This repository is private and local-first. The trading engine binds to `127.0.0.1` and live execution is disabled by default.

## Never commit, paste, or send to an LLM

- broker passwords, OTPs, trading PINs, TOTP seeds, or recovery codes;
- bank/card credentials;
- withdrawal-enabled credentials;
- Groww API key or secret;
- PAN/Aadhaar/tax documents unless a separate workflow explicitly requires them.

## Credential storage

On macOS, Groww API credentials are stored in **macOS Keychain** under the service `SuhasPrivateAITrader`. They must not be stored in browser JavaScript, localStorage, GitHub, issue text, prompts, or the release ZIP. Environment-variable fallback exists only for tests and non-macOS automation.

## Execution boundaries

1. Local LLM output is advisory and can never place an order.
2. BUY requires human confirmation and fresh server-side revalidation.
3. SELL/trim requires human confirmation and fresh quote, position, pattern, and news revalidation.
4. The 3% profit-booking reference is advisory only; no automatic partial quantity is inferred.
5. The 5% rule may propose a maximum approximately 15% quantity trim, still requiring human confirmation.
6. Risk limits and vetoes never adapt automatically. Only bounded agent-confidence multipliers may learn from resolved historical outcomes.
7. Internet/news provider failure is visible through provider health and must fail closed rather than fabricate news.
8. Never expose the local API beyond loopback without adding authentication, TLS, and a separate security review.

## Local data

Production 2.0 stores market intelligence in a local SQLite database under the user profile. The database uses WAL mode, bounded retention, daily backup, and contains market/news/analysis history—not broker secrets.

## Vulnerability and release gate

The Production 2.0 release ZIP is created only after Linux validation, macOS validation, tests, rule-contract validation, secret scanning, shell/JavaScript checks, dependency consistency, and a clean runtime dependency audit pass.
