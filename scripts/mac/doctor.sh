#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FAILURES=0
WARNINGS=0

pass() { printf '\033[1;32mPASS\033[0m  %s\n' "$*"; }
warn() { printf '\033[1;33mWARN\033[0m  %s\n' "$*"; WARNINGS=$((WARNINGS + 1)); }
fail() { printf '\033[1;31mFAIL\033[0m  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }

printf '\nPrivate AI Trader — Mac Doctor\n'
printf '================================\n'

if [[ "$(uname -s)" == "Darwin" ]]; then
  pass "Running on macOS $(sw_vers -productVersion) ($(uname -m))."
else
  fail "This installation is not running on macOS."
fi

MACOS_MAJOR="$(sw_vers -productVersion 2>/dev/null | cut -d. -f1)"
if [[ "$MACOS_MAJOR" =~ ^[0-9]+$ ]] && (( MACOS_MAJOR >= 14 )); then
  pass "macOS version meets the Sonoma-or-newer requirement."
else
  fail "macOS 14 Sonoma or newer is required."
fi

if xcode-select -p >/dev/null 2>&1; then pass "Apple Command Line Tools are installed."; else fail "Apple Command Line Tools are missing."; fi
for cmd in brew git gh jq node ollama curl; do
  if command -v "$cmd" >/dev/null 2>&1; then
    pass "$cmd is available: $(command -v "$cmd")"
  else
    fail "$cmd is missing."
  fi
done

if [[ -x "$BACKEND_DIR/.venv/bin/python" ]]; then
  pass "Python virtual environment exists: $("$BACKEND_DIR/.venv/bin/python" --version 2>&1)"
  RUNTIME_PYTHON="$BACKEND_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  fail "backend/.venv is missing."
  RUNTIME_PYTHON="$(command -v python3)"
else
  fail "Python is unavailable."
  RUNTIME_PYTHON=""
fi

if [[ -f "$BACKEND_DIR/.env" ]]; then
  pass "backend/.env exists locally."
  if grep -Eq '^GROWW_LIVE_EXECUTION_ENABLED=(true|1|yes|on)$' "$BACKEND_DIR/.env"; then
    warn "LIVE EXECUTION IS ENABLED in backend/.env. Use only after explicit paper-mode validation."
  else
    pass "Live execution is disabled in backend/.env."
  fi
  if security find-generic-password -s "SuhasPrivateAITrader" -a "groww-api-key" -w >/dev/null 2>&1 && security find-generic-password -s "SuhasPrivateAITrader" -a "groww-api-secret" -w >/dev/null 2>&1; then
    pass "Groww API credentials are present in macOS Keychain."
  else
    warn "Groww API credentials are not in macOS Keychain yet; market feed and broker data will remain unavailable."
  fi
else
  fail "backend/.env is missing."
fi

if [[ -f "$ROOT_DIR/local.runtime.json" ]]; then
  pass "local.runtime.json exists."
  if [[ -n "$RUNTIME_PYTHON" ]]; then
    MODEL="$("$RUNTIME_PYTHON" - "$ROOT_DIR/local.runtime.json" <<'PY' 2>/dev/null || true
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    print(json.load(handle).get("ollamaModel", ""))
PY
)"
    [[ -n "$MODEL" ]] && printf '      Selected local model: %s\n' "$MODEL"
  fi
else
  warn "local.runtime.json is missing; browser defaults will be used."
fi

if curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  pass "Ollama local API is reachable."
else
  warn "Ollama local API is not reachable on 127.0.0.1:11434."
fi
if ollama list 2>/dev/null | grep -q '^embeddinggemma'; then
  pass "Local semantic-memory model embeddinggemma is installed."
else
  warn "embeddinggemma is not installed; semantic news memory will remain degraded."
fi
if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then pass "FastAPI backend is reachable."; else warn "FastAPI backend is not currently running."; fi
if curl -fsS http://127.0.0.1:8000/api/production24/status >/dev/null 2>&1; then pass "Production 2.4 status endpoint is reachable."; else warn "Production 2.4 status endpoint is not currently reachable."; fi
if curl -fsS http://127.0.0.1:8080 >/dev/null 2>&1; then pass "Frontend is reachable."; else warn "Frontend is not currently running."; fi

if [[ -x "$BACKEND_DIR/.venv/bin/python" ]]; then
  printf '\nRunning repository verification...\n'
  if bash "$ROOT_DIR/scripts/verify.sh"; then
    pass "Repository verification passed."
  else
    fail "Repository verification failed."
  fi
fi

printf '\nDoctor result: %s failure(s), %s warning(s).\n' "$FAILURES" "$WARNINGS"
(( FAILURES == 0 ))
