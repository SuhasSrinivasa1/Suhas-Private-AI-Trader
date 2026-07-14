#!/usr/bin/env bash
set -euo pipefail

SERVICE="SuhasPrivateAITrader"
API_KEY_ACCOUNT="groww-api-key"
API_SECRET_ACCOUNT="groww-api-secret"

fail() { printf '\n[groww-setup] %s\n' "$*" >&2; exit 1; }
info() { printf '\n[groww-setup] %s\n' "$*"; }

[[ "$(uname -s)" == "Darwin" ]] || fail "This credential setup is for macOS only."
command -v security >/dev/null 2>&1 || fail "macOS Keychain command 'security' is unavailable."

cat <<'EOF'
Groww Trading API production connection
--------------------------------------
1. Buy/activate the Groww Trading API subscription in Groww.
2. Generate an API Key + Secret in Groww Cloud API Keys.
3. Approve that API key for the current day when Groww requires daily approval.
4. Paste the API key and secret below. They will be stored in macOS Keychain, not in this project.

Do NOT paste your Groww password, OTP, PIN, recovery code, bank password, or card details here.
EOF

read -r -p "Groww API key: " GROWW_KEY
[[ -n "$GROWW_KEY" ]] || fail "API key cannot be blank."
read -r -s -p "Groww API secret: " GROWW_SECRET
printf '\n'
[[ -n "$GROWW_SECRET" ]] || fail "API secret cannot be blank."

security add-generic-password -U -a "$API_KEY_ACCOUNT" -s "$SERVICE" -w "$GROWW_KEY" >/dev/null
security add-generic-password -U -a "$API_SECRET_ACCOUNT" -s "$SERVICE" -w "$GROWW_SECRET" >/dev/null
unset GROWW_KEY GROWW_SECRET

info "Groww API credentials were stored in macOS Keychain."
info "Restarting the local trader so it can read the new Keychain credentials."
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
bash "$ROOT_DIR/scripts/mac/stop.sh" >/dev/null 2>&1 || true
bash "$ROOT_DIR/scripts/mac/start.sh" --no-open

printf '\nNow open http://127.0.0.1:8080 and use Broker Connections -> TEST READ-ONLY CONNECTION.\n'
