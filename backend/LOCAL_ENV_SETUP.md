# Local backend environment setup

The Mac bootstrap creates `backend/.env` automatically from `backend/.env.example` when the file does not already exist:

```bash
bash scripts/mac/bootstrap.sh
```

For a manual setup from inside the `backend` folder:

```bash
cp .env.example .env
```

Add only the official Groww API values to the local file:

```text
GROWW_API_KEY=
GROWW_API_SECRET=
```

Keep live execution disabled during setup and paper validation:

```text
GROWW_LIVE_EXECUTION_ENABLED=false
```

Do not place passwords, OTPs, PINs, TOTP seeds, recovery codes, bank credentials, or withdrawal-enabled secrets in the file.

Before any live-execution setting is considered, verify locally:

- Groww authentication;
- holdings retrieval;
- positions retrieval;
- live quote retrieval;
- scanner behavior;
- risk sizing;
- stale-signal rejection;
- anti-chase rejection;
- market-session checks;
- server-side revalidation immediately before an order request.

`backend/.env` is intentionally excluded from Git and must never be committed.
