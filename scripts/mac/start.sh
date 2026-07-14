#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
RUNTIME_DIR="$ROOT_DIR/.runtime"
LOG_DIR="$RUNTIME_DIR/logs"
OPEN_BROWSER=true
[[ "${1:-}" == "--no-open" ]] && OPEN_BROWSER=false
mkdir -p "$LOG_DIR"
info(){ printf '\033[1;34m[mac-start]\033[0m %s\n' "$*"; }
fail(){ printf '\033[1;31m[mac-start]\033[0m %s\n' "$*" >&2; exit 1; }
[[ "$(uname -s)" == "Darwin" ]] || fail "This launcher is for macOS only."
[[ -x "$BACKEND_DIR/.venv/bin/python" ]] || fail "Python environment missing. Run INSTALL_MAC.command."
[[ -f "$BACKEND_DIR/.env" ]] || fail "backend/.env missing. Run INSTALL_MAC.command."
command -v brew >/dev/null 2>&1 && brew services start ollama >/dev/null 2>&1 || true
wait_for_url(){ local url="$1" name="$2"; for _ in {1..50}; do curl -fsS "$url" >/dev/null 2>&1 && { info "$name is ready."; return 0; }; sleep .5; done; return 1; }
start_service(){ local name="$1" pid_file="$2" command="$3" log="$4"; if [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then info "$name already running."; return; fi; rm -f "$pid_file"; (cd "$ROOT_DIR"; nohup bash -lc "$command" >"$log" 2>&1 & echo $! >"$pid_file"); }
start_service "Backend" "$RUNTIME_DIR/backend.pid" "cd '$BACKEND_DIR' && .venv/bin/python -m uvicorn production24_main:app --host 127.0.0.1 --port 8000" "$LOG_DIR/backend.log"
start_service "Frontend" "$RUNTIME_DIR/frontend.pid" "'$BACKEND_DIR/.venv/bin/python' -m http.server 8080 --bind 127.0.0.1" "$LOG_DIR/frontend.log"
wait_for_url http://127.0.0.1:8000/health Backend || { tail -n 120 "$LOG_DIR/backend.log" || true; fail "Backend failed to start."; }
wait_for_url http://127.0.0.1:8080 Frontend || { tail -n 80 "$LOG_DIR/frontend.log" || true; fail "Frontend failed to start."; }
$OPEN_BROWSER && open http://127.0.0.1:8080
cat <<EOF
Private AI Trader Production 2.4.1 is running.
Frontend: http://127.0.0.1:8080
Backend: http://127.0.0.1:8000/health
Research: http://127.0.0.1:8000/api/production24/status
Duty: http://127.0.0.1:8000/api/duty/status
Calls: http://127.0.0.1:8000/api/calls-results
Logs: $LOG_DIR
EOF
