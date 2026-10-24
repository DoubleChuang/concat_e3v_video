#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLAT="mac"
BIN_DIR="$ROOT/build/bin/$PLAT"
FFMPEG="$BIN_DIR/ffmpeg"
mkdir -p "$BIN_DIR"

# Prebuilt ffmpeg-static binaries (hosted on GitHub Releases: immutable and
# verifiable). They only link macOS system frameworks (/usr/lib, /System/Library),
# so they can be bundled into the app as-is.
# Bump the tag and the sha256 values below together.
FFMPEG_STATIC_TAG="b6.1.1"

ffmpeg_asset() {
  case "$(uname -m)" in
    arm64)
      echo "ffmpeg-darwin-arm64.gz 8923876afa8db5585022d7860ec7e589af192f441c56793971276d450ed3bbfa"
      ;;
    x86_64)
      echo "ffmpeg-darwin-x64.gz 929b375c1182d956c51f7ac25e0b2b0411fb01f6f407aa15c9758efeb4242106"
      ;;
    *)
      echo "ERROR: unsupported macOS arch: $(uname -m)" >&2
      exit 1
      ;;
  esac
}

download_ffmpeg() {
  local asset sha url tmpdir gz
  read -r asset sha <<<"$(ffmpeg_asset)"
  url="https://github.com/eugeneware/ffmpeg-static/releases/download/${FFMPEG_STATIC_TAG}/${asset}"
  tmpdir="$(mktemp -d)"
  gz="$tmpdir/$asset"
  echo "Downloading ffmpeg (macOS, $(uname -m))... $url"
  # -f makes 4xx/5xx fail immediately instead of saving an error page as an archive
  # (evermeet used to answer 410 here).
  curl -fL --retry 5 --retry-delay 3 --retry-all-errors --connect-timeout 30 \
    -o "$gz" "$url"
  echo "${sha}  ${gz}" | shasum -a 256 -c -
  gunzip -c "$gz" >"$FFMPEG"
  chmod +x "$FFMPEG"
  rm -rf "$tmpdir"
}

if [ ! -x "$FFMPEG" ]; then
  download_ffmpeg
fi

# This binary is about to be bundled into the app; prove it runs on this machine first.
if ! "$FFMPEG" -version >/dev/null 2>&1; then
  echo "ERROR: $FFMPEG is not executable (wrong arch or corrupted file)" >&2
  exit 1
fi

PYTHON="${PYTHON:-$HOME/.pyenv/versions/e3v/bin/python}"
cd "$ROOT"
"$PYTHON" -m PyInstaller --noconfirm build/app.spec
echo "Artifact: $ROOT/dist/concat-e3v"
