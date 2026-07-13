# Suhas Private AI Trader

Private, local-first trading decision-support application for Indian and U.S. markets.

## Current status

- Private GitHub repository
- Dashboard, Trade Evaluator, Portfolio, Broker Connections, and Privacy & Settings
- BUY / SELL / WAIT evaluator
- Agentic intraday opportunity scanner
- Optional private local LLM review on macOS through Ollama
- Paper mode by default
- Live execution disabled unless explicitly enabled in the backend environment
- No broker passwords, OTPs, PINs, recovery codes, API secrets, or broker credentials stored in the frontend

## Local AI on a MacBook Pro

The default local model is `gpt-oss:20b` through Ollama. It is used only as an advisory reviewer for a selected trade snapshot.

The local LLM:

- explains the deterministic scanner output;
- highlights evidence, risks, missing data, and invalidation conditions;
- cannot change BUY / WAIT logic;
- cannot bypass a risk veto;
- cannot place an order;
- never needs broker credentials.

For lower-memory Macs, use the lighter model selected in `MAC_LOCAL_AI_SETUP.md`.

## Run the frontend locally

```bash
python -m http.server 8080 --bind 127.0.0.1
```

Open `http://127.0.0.1:8080`.

## Run the backend locally

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Keep all broker secrets only in `backend/.env`. Do not commit that file.

## Set up the free local LLM

See `MAC_LOCAL_AI_SETUP.md`.

The UI defaults to:

```text
Ollama URL: http://127.0.0.1:11434
Model:      gpt-oss:20b
```

After Ollama is running and the model is installed, use **AI REVIEW** on any ranked opportunity.

## Backend starter

The FastAPI backend under `backend/` contains the scanner, risk controls, optional Groww integration, and execution revalidation.

## Security boundary

Never commit or paste broker passwords, OTPs, PINs, TOTP seeds, recovery codes, bank credentials, or withdrawal-enabled secrets. Future broker integrations should use official API/OAuth flows, least-privilege scopes, and backend-only secret storage.

The local LLM receives only the selected trade snapshot from the browser. It is advisory only and is deliberately kept outside the execution path.

## Default guardrails

- Max risk per trade: 1% of portfolio value
- Minimum reward/risk: 2.0
- Maximum chase distance: 1.5%
- Maximum quote age: 120 seconds
- Minimum independent confirmation sources: 2
- Mandatory checks: news, technical setup, portfolio exposure
- Live execution: disabled by default
