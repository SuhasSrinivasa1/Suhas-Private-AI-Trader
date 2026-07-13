# Security Policy

This project is private and paper-mode by default.

## Never commit or paste

- Broker passwords
- OTPs or trading PINs
- TOTP/authenticator seeds
- Recovery codes
- Bank or card credentials
- PAN/Aadhaar/tax documents
- Withdrawal-enabled API credentials

## Safe integration rules

1. Use official broker APIs or OAuth only.
2. Prefer paper/sandbox access first.
3. Use least-privilege, trading-only scopes.
4. Disable withdrawals wherever possible.
5. Keep secrets in a backend secret store or local `.env`, never frontend JavaScript or GitHub.
6. Add authentication before exposing any private API remotely.
7. Keep live execution disabled until end-to-end testing is complete.

## Current prototype

The browser frontend stores only non-secret demo portfolio data and local settings in browser localStorage. The backend starter contains validation logic only and does not place orders.
