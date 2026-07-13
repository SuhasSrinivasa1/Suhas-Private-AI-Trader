# Brand-new MacBook Pro: first run

Use this guide when the Mac has no Git, Homebrew, Python environment, Node, or Ollama configured yet.

## What this setup installs

The project bootstrap installs and configures:

- Apple Command Line Tools requirement check
- Homebrew
- Git
- GitHub CLI (`gh`)
- Python 3.12
- an isolated Python virtual environment under `backend/.venv`
- Node.js for frontend syntax validation
- jq
- shellcheck
- Ollama for a private local LLM
- the best configured local model for the available Mac memory

The setup does **not** put broker credentials into Git or GitHub and does **not** enable live trading.

## Phase 1 — install Apple Command Line Tools

Open Terminal and run:

```bash
xcode-select --install
```

Complete the macOS installer dialog. Then close and reopen Terminal.

## Phase 2 — install Homebrew

Run the official Homebrew installer:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

At the end, Homebrew prints a shell setup command. Run it if requested.

For Apple Silicon Macs, this is normally:

```bash
eval "$(/opt/homebrew/bin/brew shellenv)"
```

## Phase 3 — install Git and GitHub CLI

```bash
brew install git gh
```

Authenticate GitHub:

```bash
gh auth login
```

Recommended choices:

1. GitHub.com
2. HTTPS
3. Authenticate Git with your GitHub credentials: Yes
4. Login with a web browser

No GitHub password or token should be pasted into this repository.

## Phase 4 — clone the private repository

```bash
cd ~
gh repo clone SuhasSrinivasa1/Suhas-Private-AI-Trader
cd Suhas-Private-AI-Trader
```

Until Pull Request #1 is merged, use the Mac build branch:

```bash
git switch feature/mac-local-llm
```

After that pull request is merged, future fresh installations can use `main`.

## Phase 5 — run the one-command Mac bootstrap

```bash
bash scripts/mac/bootstrap.sh
```

The bootstrap is idempotent: it may be run again after an interrupted setup. It will not overwrite an existing `backend/.env` file.

The first run may take longer because the local AI model must be downloaded.

## Phase 6 — start the application

```bash
bash scripts/mac/start.sh
```

The app opens at:

```text
http://127.0.0.1:8080
```

Backend health:

```text
http://127.0.0.1:8000/health
```

You can also double-click `run-mac.command` in Finder after the bootstrap has made it executable.

## Phase 7 — run the Mac doctor

```bash
bash scripts/mac/doctor.sh
```

This checks:

- macOS compatibility
- required tools
- Python environment
- local `.env`
- whether live execution is still disabled
- whether Groww credentials are configured locally
- Ollama availability
- backend/frontend availability
- repository tests, rules contract, secret scan, JavaScript syntax, and shell validation

## Phase 8 — configure Groww only when ready

Open:

```text
backend/.env
```

Add only the official Groww API values to the blank local fields:

```text
GROWW_API_KEY=
GROWW_API_SECRET=
```

Do not put passwords, OTPs, PINs, TOTP seeds, recovery codes, bank credentials, or withdrawal-enabled secrets in this file.

Keep this setting unchanged during paper validation:

```text
GROWW_LIVE_EXECUTION_ENABLED=false
```

Live execution should only be considered after broker authentication, holdings, positions, quote sync, scanner behavior, order sizing, and server-side revalidation have been verified on the physical Mac.

## Everyday commands

Start:

```bash
make start
```

Stop:

```bash
make stop
```

Health check:

```bash
make doctor
```

Run all tests and safety checks:

```bash
make verify
```

## Update from GitHub later

Before updating, stop the app:

```bash
make stop
```

Then:

```bash
git status
git pull --ff-only
make bootstrap
make verify
make start
```

Never commit `backend/.env`, `local.runtime.json`, `local.runtime.js`, `.runtime/`, logs, or local databases.
