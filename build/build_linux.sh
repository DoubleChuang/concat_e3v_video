#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLAT="linux"
BIN_DIR="$ROOT/build/bin/$PLAT"
FFMPEG="$BIN_DIR/ffmpeg"
mkdir -p "$BIN_DIR"

# ffmpeg-static 的預編譯檔案（GitHub Releases 托管，內容固定、可驗證）。
# 之前用 johnvansickle.com，對方回錯誤頁時 tar 只會噴
# "xz: (stdin): File format not recognized"，看不出是下載失敗。
# 換版本時記得同步更新下面的 sha256。
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
      echo "ERROR: 不支援的 Linux 架構: $(uname -m)" >&2
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
  echo "下載 ffmpeg (linux, $(uname -m))... $url"
  # -f 讓 4xx/5xx 直接失敗，避免把錯誤頁面當成壓縮檔解開
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

# 這個 binary 等等要打包進 app；先確認它真的能在目前機器上執行
if ! "$FFMPEG" -version >/dev/null 2>&1; then
  echo "ERROR: $FFMPEG 無法執行（架構不符或檔案損毀）" >&2
  exit 1
fi

PYTHON="${PYTHON:-python3}"
cd "$ROOT"
"$PYTHON" -m PyInstaller --noconfirm build/app.spec
echo "產物: $ROOT/dist/concat-e3v"
