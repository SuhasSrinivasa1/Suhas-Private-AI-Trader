#!/bin/zsh
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p logs data/secure
exec ./.venv/bin/python -m uvicorn psscanner_quant.main:app --host 127.0.0.1 --port 8765 --log-level info
