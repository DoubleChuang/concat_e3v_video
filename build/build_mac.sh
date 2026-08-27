#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLAT="mac"
BIN_DIR="$ROOT/build/bin/$PLAT"
FFMPEG="$BIN_DIR/ffmpeg"
mkdir -p "$BIN_DIR"

if [ ! -x "$FFMPEG" ]; then
  echo "下載 ffmpeg (macOS)..."
  ARCH="$(uname -m)"
  if [ "$ARCH" = "arm64" ]; then
    URL="https://evermeet.cx/ffmpeg/getrelease/arm64/zip"
  else
    URL="https://evermeet.cx/ffmpeg/getrelease/zip"
  fi
  curl -L -o /tmp/ffmpeg-mac.zip "$URL"
  unzip -o /tmp/ffmpeg-mac.zip -d "$BIN_DIR"
fi

PYTHON="${PYTHON:-$HOME/.pyenv/versions/e3v/bin/python}"
cd "$ROOT"
"$PYTHON" -m PyInstaller --noconfirm build/app.spec
echo "產物: $ROOT/dist/concat-e3v"