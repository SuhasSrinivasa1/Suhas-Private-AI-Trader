# MacBook Pro local AI setup

This project uses Ollama for a free local LLM reviewer. The model runs on the Mac and receives only a selected machine-generated trade snapshot. It is outside the order-execution path.

## Automatic setup

The recommended path is the full Mac bootstrap:

```bash
bash scripts/mac/bootstrap.sh
```

The bootstrap:

1. verifies macOS compatibility;
2. installs the reproducible Homebrew dependencies;
3. installs and starts the local Ollama service;
4. disables Ollama cloud features through the local server configuration;
5. detects the Mac architecture and available memory;
6. selects and downloads a suitable local model;
7. writes local runtime hints that are ignored by Git;
8. runs the repository verification suite.

## Model selection policy

Unless `AI_MODEL` is explicitly supplied, the bootstrap chooses:

### Apple Silicon with 24 GB or more

```text
gpt-oss:20b
```

This is the quality-first default for a Mac with enough headroom.

### Apple Silicon with 16–23 GB

```text
qwen3:8b
```

This reduces memory pressure while retaining a stronger local reviewer than the smallest fallback.

### Smaller-memory or Intel fallback

```text
qwen3:4b
```

Intel Macs can run Ollama, but local inference is CPU-only and may be substantially slower. The application itself remains usable without AI REVIEW.

## Override the automatic model choice

Run the bootstrap with an explicit model:

```bash
AI_MODEL=qwen3:8b bash scripts/mac/bootstrap.sh
```

or:

```bash
AI_MODEL=gpt-oss:20b bash scripts/mac/bootstrap.sh
```

The selected model is saved only in local runtime files ignored by Git.

## Local-only Ollama configuration

The bootstrap creates or updates:

```text
~/.ollama/server.json
```

with:

```json
{
  "disable_ollama_cloud": true
}
```

The application uses:

```text
http://127.0.0.1:11434
```

as the local Ollama API address.

## Start and test

Start the project:

```bash
make start
```

Then open **Privacy & Settings**. The selected local model should be shown automatically. Use **Test connection** to verify the local model.

The Mac doctor can also check Ollama:

```bash
make doctor
```

## How AI REVIEW works

When **AI REVIEW** is selected, the browser sends only the selected opportunity snapshot to the local Ollama API. The snapshot can include:

- symbol and exchange;
- deterministic state;
- confidence;
- entry, target, stop, and quantity;
- reward/risk;
- market-regime summary;
- agent scores;
- risk vetoes;
- machine-generated reasons;
- signal timestamp and validity.

It does not need or receive:

- broker passwords;
- OTPs;
- PINs;
- recovery codes;
- TOTP seeds;
- bank credentials;
- Groww API secrets.

The local prompt instructs the model to:

- preserve the deterministic BUY / WAIT state;
- never invent live prices or news;
- state when data is missing or stale;
- never suggest bypassing a veto;
- explain the strongest evidence, main risks, and invalidation conditions.

## Execution boundary

The LLM cannot:

- convert WAIT into BUY;
- remove a risk veto;
- change position sizing;
- enable live execution;
- submit an order;
- approve a broker request.

The deterministic scanner and backend safety checks remain authoritative.
