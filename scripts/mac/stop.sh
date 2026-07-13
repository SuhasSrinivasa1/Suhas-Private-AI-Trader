#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_DIR="$ROOT_DIR/.runtime"

stop_pid_file() {
  local name="$1"
  local pid_file="$2"
  if [[ ! -f "$pid_file" ]]; then
    printf '[mac-stop] %s is not recorded as running.\n' "$name"
    return
  fi
  local pid
  pid="$(cat "$pid_file")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    for _ in {1..20}; do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.2
    done
    kill -9 "$pid" 2>/dev/null || true
    printf '[mac-stop] Stopped %s (PID %s).\n' "$name" "$pid"
  else
    printf '[mac-stop] %s PID %s was already stopped.\n' "$name" "$pid"
  fi
  rm -f "$pid_file"
}

stop_pid_file "frontend" "$RUNTIME_DIR/frontend.pid"
stop_pid_file "backend" "$RUNTIME_DIR/backend.pid"

if [[ "${STOP_OLLAMA:-0}" == "1" ]] && command -v brew >/dev/null 2>&1; then
  brew services stop ollama >/dev/null 2>&1 || true
  printf '[mac-stop] Stopped Ollama service.\n'
else
  printf '[mac-stop] Ollama remains available for local AI. Set STOP_OLLAMA=1 to stop it too.\n'
fi
