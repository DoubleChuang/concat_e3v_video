# concat e3v video

將`e3v`行車記錄器的連續ts片段，合併成一個mp4檔案

## How to use

```
usage: main.py [-h] src_video_dir dst_video_dir Times [Times ...]

Automatically combine multiple continuous time videos into one

positional arguments:
  src_video_dir  source video directory
  dst_video_dir  destination video directory
  Times          input start time and end time scope that you want to combine, only 2 input

options:
  -h, --help     show this help message and exit
```

example
```
python3 main.py /Volumes/Untitled/DCIM/Front Front 2023-07-20T00:00:00 2023-07-22T00:00:00
```

## GUI 應用程式（跨平台）

安裝依賴並啟動：

```
~/.pyenv/versions/e3v/bin/pip install -r requirements-dev.txt
~/.pyenv/versions/e3v/bin/python app/main.py
```

功能：選擇來源/輸出目錄與時間範圍；勾選「合併成一個檔」可將範圍內全部片段串成單一 mp4；
勾選「靜音前 N 秒」可在合併時直接將前 N 秒音軌靜音（畫面保留）；勾選「上傳到 YouTube」
會在開始處理前優先檢查上傳權限與憑證，過期/失效時於視窗內重新授權
（憑證儲存於 `~/.youtube-upload-credentials.json`）。

Client Secrets：打包後的程式沒有 repo root，請在「上傳到 YouTube」面板中手動選擇
`client_secret*.json`，或放到 `~/.client_secrets.json`。

## 打包（PyInstaller + 內建 ffmpeg）

各平台需在該平台執行對應腳本（下載該平台 static ffmpeg 並打包成單一執行檔）：

- macOS: `./build/build_mac.sh`（產物 `dist/concat-e3v`）
- Linux: `./build/build_linux.sh`（產物 `dist/concat-e3v`）
- Windows: `build\build_windows.bat`（產物 `dist\concat-e3v.exe`）

若 venv 的 Python 沒有 shared library（例如 pyenv 未以 `--enable-shared` 建置），PyInstaller 會失敗，
請用 `PYTHON` 環境變數指定 framework/共享版 Python（例如 `PYTHON="$(pwd)/.venv-build/bin/python" ./build/build_mac.sh`）。

## Remove System Immutable Flag
用來刪除緊急鎖檔的檔案
```
sudo chflags nouchg /Volumes/Untitled/DCIM/EMR/*.TS && rm /Volumes/Untitled/DCIM/EMR/*.TS
```


## Upload video to youtube

ref: https://ithelp.ithome.com.tw/m/articles/10387011

### 重新取得Token
執行以下指令 上傳mp4
```
python3 upload_mp4_to_youtube.py Front/XXX.mp4
```

會出現如下面的資訊
```
Using client secrets: /path/to/client_secret_*.json
Using credentials file: ~/.youtube-upload-credentials.json
Check this link in your browser: https://accounts.google.com/o/oauth2/auth?client_id=YOUR_CLIENT_ID.apps.googleusercontent.com&redirect_uri=urn%3Aietf%3Awg%3Aoauth%3A2.0%3Aoob&scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fyoutube.upload+https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fyoutube&access_type=offline&response_type=code
Enter verification code: YOUR_VERIFICATION_CODE
```

透過提供的url進去使用your-account@gmail.com登入並給予權限最後取得token填入到console