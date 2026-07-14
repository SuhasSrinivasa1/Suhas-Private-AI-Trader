#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
PYTHON_BIN="${PYTHON_BIN:-$BACKEND_DIR/.venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
  else
    echo "Python is required for verification." >&2
    exit 1
  fi
fi

printf '[verify] Python syntax...\n'
"$PYTHON_BIN" -m compileall -q "$BACKEND_DIR" "$ROOT_DIR/scripts"

printf '[verify] Trading rules contract...\n'
"$PYTHON_BIN" "$ROOT_DIR/scripts/check_rules_contract.py"

printf '[verify] Secret leakage scan...\n'
"$PYTHON_BIN" "$ROOT_DIR/scripts/check_no_secrets.py"

if command -v node >/dev/null 2>&1; then
  printf '[verify] JavaScript syntax...\n'
  node --check "$ROOT_DIR/app.js"
  node --check "$ROOT_DIR/features.js"
  node --check "$ROOT_DIR/production.js"
else
  printf '[verify] Node not found; JavaScript syntax checks skipped.\n'
fi

printf '[verify] Shell syntax...\n'
while IFS= read -r -d '' script; do
  bash -n "$script"
done < <(find "$ROOT_DIR/scripts" -type f -name '*.sh' -print0)
for command_file in "$ROOT_DIR"/*.command; do
  bash -n "$command_file"
done

if "$PYTHON_BIN" -c 'import pytest' >/dev/null 2>&1; then
  printf '[verify] Python tests...\n'
  (cd "$BACKEND_DIR" && "$PYTHON_BIN" -m pytest -q)
else
  printf '[verify] pytest not installed; tests skipped.\n'
fi

if command -v shellcheck >/dev/null 2>&1; then
  printf '[verify] Shell lint...\n'
  while IFS= read -r -d '' script; do
    shellcheck "$script"
  done < <(find "$ROOT_DIR/scripts" -type f -name '*.sh' -print0)
  for command_file in "$ROOT_DIR"/*.command; do
    shellcheck "$command_file"
  done
else
  printf '[verify] shellcheck not found; shell lint skipped.\n'
fi

printf '[verify] All available checks passed.\n'
