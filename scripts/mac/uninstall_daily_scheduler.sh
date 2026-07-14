#!/usr/bin/env bash
set -euo pipefail
PLIST="$HOME/Library/LaunchAgents/com.suhas.private-ai-trader.daily.plist"
UID_VALUE="$(id -u)"
launchctl bootout "gui/$UID_VALUE" "$PLIST" >/dev/null 2>&1 || true
rm -f "$PLIST"
printf 'Daily scheduler removed.\n'
