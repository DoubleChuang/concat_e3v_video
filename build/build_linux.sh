#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLAT="linux"
BIN_DIR="$ROOT/build/bin/$PLAT"
FFMPEG="$BIN_DIR/ffmpeg"
mkdir -p "$BIN_DIR"

# Prebuilt ffmpeg-static binaries (hosted on GitHub Releases: immutable and
# verifiable). We used johnvansickle.com before; when it answered with an error
# page, tar only said "xz: (stdin): File format not recognized", which looked like
# an archive problem instead of a failed download.
# Bump the tag and the sha256 values below together.
FFMPEG_STATIC_TAG="b6.1.1"

ffmpeg_asset() {
  case "$(uname -m)" in
    x86_64)
      echo "ffmpeg-linux-x64.gz bfe8a8fc511530457b528c48d77b5737527b504a3797a9bc4866aeca69c2dffa"
      ;;
    aarch64 | arm64)
      echo "ffmpeg-linux-arm64.gz 754a678672298bc68156adff58aa7385a592c2b30b1d0ae8750c45c915c4bac0"
      ;;
    *)
      echo "ERROR: unsupported Linux arch: $(uname -m)" >&2
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
  echo "Downloading ffmpeg (linux, $(uname -m))... $url"
  # -f makes 4xx/5xx fail immediately instead of saving an error page as an archive
  curl -fL --retry 5 --retry-delay 3 --retry-all-errors --connect-timeout 30 \
    -o "$gz" "$url"
  echo "${sha}  ${gz}" | sha256sum -c -
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

PYTHON="${PYTHON:-python3}"
cd "$ROOT"
"$PYTHON" -m PyInstaller --noconfirm build/app.spec
echo "Artifact: $ROOT/dist/concat-e3v"
