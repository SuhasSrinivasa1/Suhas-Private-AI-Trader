#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
RUNTIME_DIR="$ROOT_DIR/.runtime"
LOG_DIR="$RUNTIME_DIR/logs"
OPEN_BROWSER=true
[[ "${1:-}" == "--no-open" ]] && OPEN_BROWSER=false
mkdir -p "$LOG_DIR"

info() { printf '\033[1;34m[mac-start]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[mac-start]\033[0m %s\n' "$*" >&2; exit 1; }

[[ "$(uname -s)" == "Darwin" ]] || fail "This launcher is for macOS only."
[[ -x "$BACKEND_DIR/.venv/bin/python" ]] || fail "Python environment missing. Run: bash scripts/mac/bootstrap.sh"
[[ -f "$BACKEND_DIR/.env" ]] || fail "backend/.env missing. Run: bash scripts/mac/bootstrap.sh"

if command -v brew >/dev/null 2>&1; then
  brew services start ollama >/dev/null 2>&1 || true
fi

wait_for_url() {
  local url="$1"
  local name="$2"
  for _ in {1..50}; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      info "$name is ready."
      return 0
    fi
    sleep 0.5
  done
  return 1
}

start_backend() {
  local pid_file="$RUNTIME_DIR/backend.pid"
  if [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
    info "Backend already running with PID $(cat "$pid_file")."
    return
  fi
  rm -f "$pid_file"
  info "Starting production FastAPI backend on 127.0.0.1:8000."
  (
    cd "$BACKEND_DIR"
    nohup .venv/bin/python -m uvicorn production_main:app --host 127.0.0.1 --port 8000 \
      > "$LOG_DIR/backend.log" 2>&1 &
    echo $! > "$pid_file"
  )
}

start_frontend() {
  local pid_file="$RUNTIME_DIR/frontend.pid"
  if [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
    info "Frontend already running with PID $(cat "$pid_file")."
    return
  fi
  rm -f "$pid_file"
  info "Starting local frontend on 127.0.0.1:8080."
  (
    cd "$ROOT_DIR"
    nohup "$BACKEND_DIR/.venv/bin/python" -m http.server 8080 --bind 127.0.0.1 \
      > "$LOG_DIR/frontend.log" 2>&1 &
    echo $! > "$pid_file"
  )
}

start_backend
start_frontend

if ! wait_for_url "http://127.0.0.1:8000/health" "Backend"; then
  tail -n 120 "$LOG_DIR/backend.log" || true
  fail "Backend failed to start."
fi

if ! wait_for_url "http://127.0.0.1:8080" "Frontend"; then
  tail -n 80 "$LOG_DIR/frontend.log" || true
  fail "Frontend failed to start."
fi

if curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  info "Local Ollama API is ready."
else
  info "Ollama is not ready; deterministic trading features will still run, but local AI review will be unavailable."
fi

if $OPEN_BROWSER; then
  info "Opening Private AI Trader in the default browser."
  open "http://127.0.0.1:8080"
fi

cat <<EOF

Private AI Trader production release is running locally.

Frontend:          http://127.0.0.1:8080
Backend health:    http://127.0.0.1:8000/health
Production status: http://127.0.0.1:8000/api/production/status
Logs:              $LOG_DIR

Stop the app with:
  bash scripts/mac/stop.sh

EOF
