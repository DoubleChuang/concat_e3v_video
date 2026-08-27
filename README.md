# concat e3v video

![build](https://github.com/DoubleChuang/concat_e3v_video/actions/workflows/build.yml/badge.svg)

將 `e3v` 行車記錄器的連續 TS 片段，依時間範圍合併成 MP4 檔案。

## 功能

- **GUI（跨平台）**：選擇目錄與時間範圍、合併成單一檔、靜音前 N 秒、上傳 YouTube（含憑證檢查與重新授權）
- **CLI**：保留原有指令列介面（含 `--upload-to-youtube`）
- **打包**：PyInstaller 單一執行檔、內建 ffmpeg，支援 macOS / Linux / Windows

## 安裝

建議使用 pyenv 建立虛擬環境：

```bash
pyenv virtualenv 3.11 e3v
~/.pyenv/versions/e3v/bin/pip install -r requirements-dev.txt
```

## GUI 使用

```bash
~/.pyenv/versions/e3v/bin/python app/main.py
```

| 欄位 | 說明 |
|---|---|
| 來源目錄 | 記憶卡影片資料夾（如 `/Volumes/Untitled/DCIM/Front`） |
| 輸出目錄 | 合併後的 MP4 存放位置 |
| 開始 / 結束時間 | 台北時區（Asia/Taipei），格式 `yyyy-MM-dd HH:mm:ss` |
| 合併成一個檔 | 勾選後，時間範圍內全部片段串成單一 MP4（忽略中間斷檔） |
| 靜音前 N 秒 | 合併時直接將前 N 秒音軌靜音（畫面保留），N=0 表示不靜音 |
| 上傳到 YouTube | 勾選後**優先**檢查上傳權限與憑證；過期/失效時會跳出授權視窗重新認證 |

### YouTube 上傳

- 勾選「上傳到 YouTube」後展開設定：標題、描述、隱私（私人/不公開/公開）、標籤、播放清單
- 憑證儲存於 `~/.youtube-upload-credentials.json`，重新授權不需重複登入
- **Client Secrets**：GUI 版沒有 repo root，請在上傳面板手動選擇 `client_secret*.json`，或放到 `~/.client_secrets.json`

## CLI 使用

```
usage: main.py [-h] [--upload-to-youtube] src_video_dir dst_video_dir Times [Times ...]

positional arguments:
  src_video_dir         source video directory
  dst_video_dir         destination video directory
  Times                 start and end time (only 2 input), e.g. 2023-07-20T00:00:00 2023-07-22T00:00:00

options:
  -h, --help            show this help message and exit
  --upload-to-youtube   upload the combined video to youtube
```

example

```bash
python3 main.py /Volumes/Untitled/DCIM/Front Front 2023-07-20T00:00:00 2023-07-22T00:00:00
python3 main.py /Volumes/Untitled/DCIM/Front Front 2023-07-20T00:00:00 2023-07-22T00:00:00 --upload-to-youtube
```

## 從 Release 下載

打上 `v*` tag（如 `v1.0.0`）後，GitHub Actions 會自動建置並發布四個產物：

| 產物 | 平台 |
|---|---|
| `concat-e3v-macos-x86_64` | macOS Intel |
| `concat-e3v-macos-arm64` | macOS Apple Silicon |
| `concat-e3v-linux-x86_64` | Linux x86_64 |
| `concat-e3v-windows.exe` | Windows x86_64 |

> **未簽章注意**：產物未經 Apple/微軟簽章，首次執行需按右鍵 →「打開」（macOS Gatekeeper）或接受 SmartScreen 警告。

## 自行打包

各平台需在該平台執行對應腳本（自動下載該平台 static ffmpeg 並打包成單一執行檔）：

- macOS: `./build/build_mac.sh`（產物 `dist/concat-e3v`）
- Linux: `./build/build_linux.sh`（產物 `dist/concat-e3v`）
- Windows: `build\build_windows.bat`（產物 `dist\concat-e3v.exe`）

若 venv 的 Python 沒有 shared library（例如 pyenv 未以 `--enable-shared` 建置），PyInstaller 會失敗，
請用 `PYTHON` 環境變數指定 framework/共享版 Python（例如 `PYTHON="$(pwd)/.venv-build/bin/python" ./build/build_mac.sh`）。

## YouTube 重新授權（手動）

執行以下指令 上傳 mp4：

```
python3 upload_mp4_to_youtube.py Front/XXX.mp4
```

會出現如下面的資訊：

```
Using client secrets: /path/to/client_secret_*.json
Using credentials file: ~/.youtube-upload-credentials.json
Check this link in your browser: https://accounts.google.com/o/oauth2/auth?client_id=YOUR_CLIENT_ID.apps.googleusercontent.com&redirect_uri=urn%3Aietf%3Awg%3Aoauth%3A2.0%3Aoob&scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fyoutube.upload+https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fyoutube&access_type=offline&response_type=code
Enter verification code: YOUR_VERIFICATION_CODE
```

透過提供的 URL 登入並授權，將驗證碼填入 console 即可。

## 疑難排解

| 症狀 | 原因 / 解法 |
|---|---|
| 「找不到 ffmpeg」 | 系統未安裝 ffmpeg，請改用 Release 產物（已內建） |
| 合併後沒聲音或前 N 秒沒靜音 | 確認「靜音前 N 秒」的秒數設定與勾選狀態 |
| 時間選錯範圍 | 時間為台北時區；檢查開始 < 結束 |
| 上傳失敗 / 跳出授權視窗 | 憑證過期或無權限，於視窗內重新授權即可 |
| `No videos in time range` | 範圍內沒有符合 `YYYYMMDDHHMMSS_*.TS` 命名的檔案 |

## 附錄：移除緊急鎖檔（EMR）

用來刪除行車記錄器緊急鎖檔的檔案：

```
sudo chflags nouchg /Volumes/Untitled/DCIM/EMR/*.TS && rm /Volumes/Untitled/DCIM/EMR/*.TS
```