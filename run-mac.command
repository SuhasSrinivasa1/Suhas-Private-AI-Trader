#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
bash scripts/mac/start.sh
printf '\nYou can close this Terminal window after the browser opens.\n'
