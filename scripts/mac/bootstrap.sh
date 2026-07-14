#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"

info() { printf '\n\033[1;34m[mac-setup]\033[0m %s\n' "$*"; }
warn() { printf '\n\033[1;33m[mac-setup]\033[0m %s\n' "$*"; }
fail() { printf '\n\033[1;31m[mac-setup]\033[0m %s\n' "$*" >&2; exit 1; }

[[ "$(uname -s)" == "Darwin" ]] || fail "This bootstrap is for macOS only."
MACOS_MAJOR="$(sw_vers -productVersion | cut -d. -f1)"
(( MACOS_MAJOR >= 14 )) || fail "macOS 14 Sonoma or newer is required. Current version: $(sw_vers -productVersion)"
info "Detected $(sw_vers -productName) $(sw_vers -productVersion) on $(uname -m)."

if ! xcode-select -p >/dev/null 2>&1; then
  warn "Apple Command Line Tools are not installed. macOS will now open the installer."
  xcode-select --install >/dev/null 2>&1 || true
  cat <<'EOF'
Finish the Apple Command Line Tools installation, then run this command again:

  bash INSTALL_MAC.command
EOF
  exit 2
fi

if ! command -v brew >/dev/null 2>&1; then
  info "Installing Homebrew from the official installer."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi
if [[ -x /opt/homebrew/bin/brew ]]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
elif [[ -x /usr/local/bin/brew ]]; then
  eval "$(/usr/local/bin/brew shellenv)"
fi
command -v brew >/dev/null 2>&1 || fail "Homebrew is installed but is not available in PATH."

BREW_PREFIX="$(brew --prefix)"
SHELLENV_LINE="eval \"\$($BREW_PREFIX/bin/brew shellenv)\""
if ! grep -Fq "$SHELLENV_LINE" "$HOME/.zprofile" 2>/dev/null; then
  info "Adding Homebrew to ~/.zprofile."
  printf '\n# Homebrew\n%s\n' "$SHELLENV_LINE" >> "$HOME/.zprofile"
fi

info "Installing reproducible Mac dependencies from Brewfile."
brew bundle --file="$ROOT_DIR/Brewfile"
PYTHON_BIN="$(brew --prefix python@3.12)/bin/python3.12"
[[ -x "$PYTHON_BIN" ]] || fail "Homebrew Python 3.12 was not found."

info "Creating the isolated Python production environment."
"$PYTHON_BIN" -m venv "$BACKEND_DIR/.venv"
"$BACKEND_DIR/.venv/bin/python" -m pip install --upgrade pip wheel
"$BACKEND_DIR/.venv/bin/python" -m pip install -r "$BACKEND_DIR/requirements-dev.txt"

if [[ ! -f "$BACKEND_DIR/.env" ]]; then
  info "Creating backend/.env from the safe production template."
  cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
else
  warn "backend/.env already exists; it was preserved."
fi

info "Configuring Ollama for local-only operation."
mkdir -p "$HOME/.ollama"
"$BACKEND_DIR/.venv/bin/python" - "$HOME/.ollama/server.json" <<'PY'
import json
import pathlib
import sys
path = pathlib.Path(sys.argv[1])
try:
    data = json.loads(path.read_text()) if path.exists() else {}
except (json.JSONDecodeError, OSError):
    data = {}
data["disable_ollama_cloud"] = True
path.write_text(json.dumps(data, indent=2) + "\n")
PY

info "Starting the local Ollama service."
brew services start ollama >/dev/null
for _ in {1..40}; do
  if curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then break; fi
  sleep 1
done
curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1 || fail "Ollama did not become ready on 127.0.0.1:11434."

MEM_BYTES="$(sysctl -n hw.memsize)"
MEM_GB=$(( MEM_BYTES / 1024 / 1024 / 1024 ))
ARCH="$(uname -m)"
if [[ -n "${AI_MODEL:-}" ]]; then
  MODEL="$AI_MODEL"
elif [[ "$ARCH" == "arm64" && "$MEM_GB" -ge 24 ]]; then
  MODEL="gpt-oss:20b"
elif [[ "$ARCH" == "arm64" && "$MEM_GB" -ge 16 ]]; then
  MODEL="qwen3:8b"
else
  MODEL="qwen3:4b"
fi

info "Detected approximately ${MEM_GB} GB unified/system memory. Selected local model: ${MODEL}"
ollama pull "$MODEL"
info "Installing the local semantic-memory embedding model: embeddinggemma"
ollama pull embeddinggemma

cat > "$ROOT_DIR/local.runtime.json" <<EOF
{
  "ollamaBaseUrl": "http://127.0.0.1:11434",
  "ollamaModel": "$MODEL",
  "backendBaseUrl": "http://127.0.0.1:8000",
  "frontendBaseUrl": "http://127.0.0.1:8080",
  "timezone": "Asia/Kolkata",
  "release": "2.0.0"
}
EOF
cat > "$ROOT_DIR/local.runtime.js" <<EOF
window.PAI_RUNTIME = {
  ollamaBaseUrl: "http://127.0.0.1:11434",
  ollamaModel: "$MODEL",
  backendBaseUrl: "http://127.0.0.1:8000",
  frontendBaseUrl: "http://127.0.0.1:8080",
  timezone: "Asia/Kolkata",
  release: "2.0.0"
};
EOF

"$BACKEND_DIR/.venv/bin/python" - "$BACKEND_DIR/.env" "$MODEL" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
model = sys.argv[2]
updates = {
    "APP_ENV": "production",
    "GROWW_CREDENTIAL_SOURCE": "keychain",
    "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
    "OLLAMA_MODEL": model,
    "OLLAMA_EMBEDDING_MODEL": "embeddinggemma",
    "ENABLE_GROWW_FEED": "true",
    "ENABLE_AUTO_LLM": "true",
    "ENABLE_SEMANTIC_MEMORY": "true",
    "FREE_NEWS_ENABLED": "true",
    "NEWS_REQUIRED_FOR_BUY": "true",
}
lines = path.read_text(encoding="utf-8").splitlines()
seen = set()
out = []
for line in lines:
    if "=" in line and not line.lstrip().startswith("#"):
        key = line.split("=", 1)[0].strip()
        if key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
            continue
    out.append(line)
for key, value in updates.items():
    if key not in seen:
        out.append(f"{key}={value}")
path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
PY

chmod +x "$ROOT_DIR"/*.command "$ROOT_DIR"/scripts/mac/*.sh "$ROOT_DIR"/scripts/*.sh 2>/dev/null || true
info "Running the full local verification suite."
bash "$ROOT_DIR/scripts/verify.sh"

if [[ "${INSTALL_DAILY_SCHEDULER:-true}" == "true" ]]; then
  info "Installing the daily 07:45 local scheduler and login start hook."
  bash "$ROOT_DIR/scripts/mac/install_daily_scheduler.sh"
fi

cat <<EOF

Mac production setup completed successfully.

Release:              2.0.0
Selected local model: $MODEL
Repository folder:    $ROOT_DIR
Groww secrets:        macOS Keychain only
Live execution:       OFF by default

Next mandatory step:
  bash CONFIGURE_GROWW.command

After Groww read-only verification succeeds:
  bash START_TRADER.command

Open:
  http://127.0.0.1:8080

EOF
