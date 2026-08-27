#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLAT="linux"
BIN_DIR="$ROOT/build/bin/$PLAT"
FFMPEG="$BIN_DIR/ffmpeg"
mkdir -p "$BIN_DIR"

if [ ! -x "$FFMPEG" ]; then
  echo "下載 ffmpeg (linux)..."
  ARCH="$(uname -m)"
  if [ "$ARCH" = "aarch64" ]; then
    URL="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz"
  else
    URL="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
  fi
  curl -L -o /tmp/ffmpeg-linux.tar.xz "$URL" || { echo "ERROR: ffmpeg download failed ($URL)" >&2; exit 1; }
  tar -xJf /tmp/ffmpeg-linux.tar.xz -C /tmp
  find /tmp -maxdepth 2 -name ffmpeg -type f -exec cp {} "$FFMPEG" \;
  chmod +x "$FFMPEG"
fi
if [ ! -x "$FFMPEG" ]; then
  echo "ERROR: ffmpeg binary not found at $FFMPEG" >&2
  exit 1
fi

PYTHON="${PYTHON:-python3}"
cd "$ROOT"
"$PYTHON" -m PyInstaller --noconfirm build/app.spec
echo "產物: $ROOT/dist/concat-e3v"