#!/usr/bin/env bash
set -euo pipefail

# ──────────────────────────────────────────────────────────────────────────────
# Raven — Model Download Script (Linux/macOS)
# Downloads whisper.cpp STT model and Piper TTS voice model.
# ──────────────────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

# ── Configuration ─────────────────────────────────────────────────────────────

WHISPER_MODEL_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin"
WHISPER_MODEL_DIR="${REPO_DIR}/workspace/models/whisper"
WHISPER_MODEL_FILE="${WHISPER_MODEL_DIR}/ggml-tiny.bin"

PIPER_MODEL_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx"
PIPER_CONFIG_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json"
PIPER_MODEL_DIR="${REPO_DIR}/app/voice"
PIPER_MODEL_FILE="${PIPER_MODEL_DIR}/en_US-lessac-medium.onnx"
PIPER_CONFIG_FILE="${PIPER_MODEL_DIR}/en_US-lessac-medium.onnx.json"

# ── Helpers ───────────────────────────────────────────────────────────────────

info()  { printf "\033[1;34m➜\033[0m %s\n" "$1"; }
ok()    { printf "\033[1;32m✓\033[0m %s\n" "$1"; }
skip()  { printf "\033[1;33m⊘\033[0m %s\n" "$1"; }
err()   { printf "\033[1;31m✗\033[0m %s\n" "$1"; }

download() {
  local url="$1"
  local dest="$2"
  local label="$3"

  mkdir -p "$(dirname "$dest")"

  if [ -f "$dest" ]; then
    skip "$label already exists at $dest"
    return 0
  fi

  info "Downloading $label..."
  if command -v curl &>/dev/null; then
    curl -#fSL "$url" -o "$dest"
  elif command -v wget &>/dev/null; then
    wget --show-progress -q "$url" -O "$dest"
  else
    err "Neither curl nor wget found. Please install one of them."
    return 1
  fi

  if [ -f "$dest" ]; then
    ok "$label downloaded to $dest"
  else
    err "Failed to download $label"
    return 1
  fi
}

# ── Main ──────────────────────────────────────────────────────────────────────

echo ""
echo "  Raven — Model Downloader"
echo "  ─────────────────────────"
echo ""

download "$WHISPER_MODEL_URL" "$WHISPER_MODEL_FILE" "whisper.cpp ggml-tiny model"
echo ""

download "$PIPER_MODEL_URL" "$PIPER_MODEL_FILE" "Piper TTS ONNX model"
download "$PIPER_CONFIG_URL" "$PIPER_CONFIG_FILE" "Piper TTS config"
echo ""

if [ -f "$WHISPER_MODEL_FILE" ] && [ -f "$PIPER_MODEL_FILE" ] && [ -f "$PIPER_CONFIG_FILE" ]; then
  ok "All models downloaded successfully!"
  echo ""
  echo "  Whisper STT:  $WHISPER_MODEL_FILE"
  echo "  Piper TTS:    $PIPER_MODEL_FILE"
  echo "  Piper config: $PIPER_CONFIG_FILE"
else
  err "Some models failed to download. Check the errors above."
  exit 1
fi
