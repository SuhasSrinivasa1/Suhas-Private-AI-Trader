#!/usr/bin/env bash
set -euo pipefail
SERVICE="SuhasPrivateAITrader"
for account in groww-api-key groww-api-secret; do
  security delete-generic-password -a "$account" -s "$SERVICE" >/dev/null 2>&1 || true
done
printf 'Groww API credentials removed from macOS Keychain.\n'
