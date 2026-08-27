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
    URL="https://www.osxexperts.net/ffmpeg9arm.zip"
  else
    URL="https://evermeet.cx/ffmpeg/getrelease/zip"
  fi
  curl -L -o /tmp/ffmpeg-mac.zip "$URL"
  if [ "$ARCH" = "arm64" ]; then
    echo "d0c06c5c68ce48af3143b262f7a9118a7c9f67de1e237fcc24ffb14df9c67af9  /tmp/ffmpeg-mac.zip" | shasum -a 256 -c - || exit 1
  fi
  unzip -o /tmp/ffmpeg-mac.zip -d "$BIN_DIR"
fi
if [ ! -x "$FFMPEG" ]; then
  echo "ERROR: ffmpeg binary not found at $FFMPEG" >&2
  exit 1
fi

PYTHON="${PYTHON:-$HOME/.pyenv/versions/e3v/bin/python}"
cd "$ROOT"
"$PYTHON" -m PyInstaller --noconfirm build/app.spec
echo "產物: $ROOT/dist/concat-e3v"