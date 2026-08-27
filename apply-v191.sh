#!/usr/bin/env bash
set -euo pipefail
cd nse-intraday-v190
cat ../v191.part.00 ../v191.part.01 ../v191.part.02 ../v191.part.03 ../v191.part.04 ../v191.part.05 ../v191.part.06 | base64 -d > /tmp/v191-overlay.tar.xz
tar -xJf /tmp/v191-overlay.tar.xz
cd ..
mv nse-intraday-v190 nse-intraday-v191
