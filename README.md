# Suhas Private AI Trader

Private, local-first trading decision-support application for Indian and U.S. markets.

## Current status

- Private GitHub repository
- Dashboard, Trade Evaluator, Portfolio, Broker Connections, and Privacy & Settings
- BUY / SELL / WAIT evaluator
- Paper mode by default
- Live execution disabled
- No broker connected yet
- No passwords, OTPs, PINs, recovery codes, or broker secrets stored in the frontend

## Run locally

```bash
python -m http.server 8080
```

Open `http://localhost:8080`.

## Backend starter

A FastAPI starter is included under `backend/`. It mirrors the safety-first trading-policy logic but does not fetch live market data, connect to brokers, or place orders.

## Security boundary

Never commit or paste broker passwords, OTPs, PINs, TOTP seeds, recovery codes, bank credentials, or withdrawal-enabled secrets. Future broker integrations should use official API/OAuth flows, least-privilege scopes, and backend-only secret storage.

## Default guardrails

- Max risk per trade: 1% of portfolio value
- Minimum reward/risk: 2.0
- Maximum chase distance: 1.5%
- Maximum quote age: 120 seconds
- Minimum independent confirmation sources: 2
- Mandatory checks: news, technical setup, portfolio exposure
- Live execution: disabled
