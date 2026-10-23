#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLAT="mac"
BIN_DIR="$ROOT/build/bin/$PLAT"
FFMPEG="$BIN_DIR/ffmpeg"
mkdir -p "$BIN_DIR"

# ffmpeg-static 的預編譯檔案（GitHub Releases 托管，內容固定、可驗證）。
# 只連結 macOS 系統 framework（/usr/lib、/System/Library），可直接打包進 app。
# 換版本時記得同步更新下面的 sha256。
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
      echo "ERROR: 不支援的 macOS 架構: $(uname -m)" >&2
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
  echo "下載 ffmpeg (macOS, $(uname -m))... $url"
  # -f 讓 4xx/5xx 直接失敗，避免把錯誤頁面當成壓縮檔解開（過去 evermeet 410 的坑）
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

# 這個 binary 等等要打包進 app；先確認它真的能在目前機器上執行
if ! "$FFMPEG" -version >/dev/null 2>&1; then
  echo "ERROR: $FFMPEG 無法執行（架構不符或檔案損毀）" >&2
  exit 1
fi

PYTHON="${PYTHON:-$HOME/.pyenv/versions/e3v/bin/python}"
cd "$ROOT"
"$PYTHON" -m PyInstaller --noconfirm build/app.spec
echo "產物: $ROOT/dist/concat-e3v"
