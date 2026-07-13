#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This setup helper is intended for macOS."
  exit 1
fi

MACOS_MAJOR="$(sw_vers -productVersion | cut -d. -f1)"
if (( MACOS_MAJOR < 14 )); then
  echo "Ollama currently requires macOS 14 Sonoma or later."
  exit 1
fi

if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama is not installed. Install the official macOS app, then rerun this script."
  echo "Official download: https://ollama.com/download/mac"
  exit 1
fi

MEM_BYTES="$(sysctl -n hw.memsize)"
MEM_GB=$(( MEM_BYTES / 1024 / 1024 / 1024 ))

if (( MEM_GB >= 16 )); then
  MODEL="gpt-oss:20b"
elif (( MEM_GB >= 12 )); then
  MODEL="qwen3:8b"
else
  MODEL="qwen3:4b"
fi

echo "Detected approximately ${MEM_GB} GB memory."
echo "Selected local model: ${MODEL}"
echo "Pulling model with Ollama..."
ollama pull "${MODEL}"

echo
echo "Local AI model is installed."
echo "In the app, use:"
echo "  Ollama URL: http://127.0.0.1:11434"
echo "  Model:      ${MODEL}"
echo
echo "For strict local-only mode, run:"
echo "  launchctl setenv OLLAMA_NO_CLOUD 1"
echo "Then fully quit and reopen Ollama."
