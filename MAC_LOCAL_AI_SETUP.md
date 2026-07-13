# MacBook Pro local AI setup

This project can use a free local LLM through Ollama. The LLM runs on the Mac and is used only to explain a selected trade snapshot. It does not control BUY / WAIT logic and cannot place orders.

## 1. Requirements

- macOS 14 Sonoma or later for the current Ollama macOS app.
- Enough free storage for the selected model.
- The frontend should be opened from `http://127.0.0.1:8080` so it can call the local Ollama service on `127.0.0.1:11434`.

## 2. Install Ollama

Install the official Ollama macOS application, then verify in Terminal:

```bash
ollama --version
```

## 3. Choose the model for the Mac

### Recommended default: 16 GB unified memory or more

```bash
ollama pull gpt-oss:20b
```

Use this in **Privacy & Settings**:

```text
Model: gpt-oss:20b
Ollama URL: http://127.0.0.1:11434
```

### Lighter fallback: 12–15 GB memory

```bash
ollama pull qwen3:8b
```

Set the model to `qwen3:8b`.

### Small-memory fallback: below 12 GB

```bash
ollama pull qwen3:4b
```

Set the model to `qwen3:4b`.

## 4. Optional strict local-only mode

To disable Ollama cloud features for the macOS application:

```bash
launchctl setenv OLLAMA_NO_CLOUD 1
```

Then fully quit and reopen Ollama.

## 5. Start the project

Terminal 1:

```bash
cd Suhas-Private-AI-Trader
python -m http.server 8080 --bind 127.0.0.1
```

Terminal 2:

```bash
cd Suhas-Private-AI-Trader/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Open:

```text
http://127.0.0.1:8080
```

Go to **Privacy & Settings**, confirm the model and Ollama URL, and click **Save & test**.

## 6. How AI REVIEW works

The browser sends only the currently selected machine-generated trade snapshot to the local Ollama API. The prompt explicitly instructs the model to:

- preserve the deterministic BUY / WAIT state;
- never invent live prices or news;
- never ask for credentials or secrets;
- never suggest bypassing a risk veto;
- explain the strongest evidence, main risks, missing data, and invalidation conditions.

The order path remains separate. The LLM is not given authority to submit or approve trades.
