#!/usr/bin/env bash
set -euo pipefail
cd nse-intraday-v190
base64 -d ../v191-overlay-b64.part.00 > /tmp/v191-overlay.tar.xz
tar -xJf /tmp/v191-overlay.tar.xz
cd ..
mv nse-intraday-v190 nse-intraday-v191
