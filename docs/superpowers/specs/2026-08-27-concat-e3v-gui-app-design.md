# concat-e3v GUI 應用程式設計文件

日期：2026-08-27
分支：`feat/gui-app`

## 目標

將現有 CLI 工具（`main.py`）包裝成跨平台（mac / linux / windows）的 PySide6 桌面應用程式，透過 UI 完成：

1. 選擇來源目錄、輸出目錄、開始/結束時間（日期時間）
2. 選擇是否將時間範圍內全部檔案合併成單一 mp4
3. 選擇是否將最終輸出檔前 N 秒靜音（N 可 0 到全部時間）
4. 選擇是否上傳到 YouTube；勾選時必須**優先**檢查 YouTube 上傳權限與憑證是否過期，失敗時在 UI 內重新授權

現有 CLI 介面保持不變（不破壞現有用法）。

## 技術選型

- **GUI**：PySide6（Qt），Python 3.11（pyenv `e3v` venv 或新建 venv）
- **打包**：PyInstaller，**連 ffmpeg 一起打包**（各平台使用該平台 static ffmpeg build）
- **時區**：固定 Asia/Taipei（與現有程式一致）
- 沿用現有模組：`e3vvid/video_processor.py`、`upload_mp4_to_youtube.py`、vendored `youtube-upload/`

## 專案結構

新增 `app/` 套件：

```
app/
├── __init__.py
├── main.py              # QApplication 入口
├── ffmpeg.py            # ffmpeg 二進位解析：打包內建 → 系統 PATH → 錯誤提示
├── settings.py          # QSettings 記住上次目錄/欄位
├── worker.py            # QThread 背景執行管線（合併 → 靜音 → 上傳），log 訊號輸出
└── ui/
    ├── __init__.py
    ├── main_window.py   # 主視窗
    └── auth_dialog.py   # YouTube 重新授權對話框
```

打包相關：

```
build/
├── app.spec             # PyInstaller spec（--add-binary ffmpeg）
├── build_mac.sh
├── build_linux.sh
└── build_windows.bat
```

## 主視窗欄位

- 來源目錄：行編輯 + 瀏覽按鈕（QFileDialog），記住上次路徑
- 輸出目錄：同上
- 開始時間 / 結束時間：`QDateTimeEdit`（含月曆彈出），台北時區，顯示格式 `yyyy-MM-dd HH:mm:ss`
- ☐ 合併成一個檔：勾選 = 範圍內全部片段（排序後）串成單一 mp4，忽略 1 分鐘間隔斷檔；未勾選 = 現狀（每連續區段一檔）
- ☐ 靜音前 N 秒：`QSpinBox`（0 = 不靜音；上限可達影片全長，等同全靜音）
- ☐ 上傳到 YouTube：勾選後展開面板——標題、描述（多行）、隱私（public/unlisted/private 下拉）、標籤、播放清單
- 執行日誌區（唯讀 `QPlainTextEdit`）
- 開始按鈕：執行中禁用；支援中途停止（中斷 ffmpeg subprocess）

## 執行前驗證順序（勾選上傳時 YouTube 優先）

1. 來源/輸出目錄存在、開始時間 < 結束時間
2. ffmpeg 可用（解析順序：執行檔目錄 → PyInstaller `_MEIPASS` → 系統 PATH → 錯誤對話框）
3. 若勾選上傳 → **優先**呼叫 `check_youtube_upload_available`（`channels().list(mine=True)`）：
   - 成功 → 繼續
   - 失敗（憑證過期/無權限）→ 跳出重新授權對話框 → 重查通過後才開始處理
   - 授權仍失敗 → 中止並提示

## 處理管線（worker 執行）

1. **合併**：`VideoProcessor` 新增 `merge_all: bool` 參數
   - `merge_all=True`：範圍內所有檔案（依檔名時間排序）全部列入單一 concat 清單，輸出一個 mp4
   - `merge_all=False`：現有 `find_continous_video` 行為（1 分鐘 interval 分組），每組一個 mp4
2. **靜音（單一 pass，整合進 concat 指令）**：不做第二遍 ffmpeg、不產生 intermediate 檔
   - N = 0：維持現行 `-c copy`（純 stream copy，不重編）
   - N > 0：concat 指令直接加音訊濾鏡，影片仍 `-c:v copy` 只重編音軌：

     ```
     ffmpeg -y -f concat -safe 0 -i videolist.txt -c:v copy -af "volume=0.0:enable='lt(t,N)'" -c:a aac out.mp4
     ```

     - `enable='lt(t,N)'` 的 `t` 是合併後輸出時間軸，即最終影片前 N 秒靜音
     - N ≥ 影片長度：`enable` 恆真 → 全靜音（同一表達式即可涵蓋，不需特判）
   - 輸出檔名：N > 0 時直接輸出 `<時間戳>_muted.mp4`（沿用現有 hokaido 命名慣例）；N = 0 維持原檔名
   - 已知限制：若來源 TS 完全無音軌，`-af` 會失敗（行車記錄器 TS 皆含音軌，可接受）
3. **上傳**：上傳前在 worker 內再次執行 YouTube 檢查；**上傳對象為最終輸出檔**（N > 0 則為 `_muted` 檔），收集結果（成功/失敗、video_id）

## 上傳模組重構

現況：`upload_mp4_to_youtube.py` 以 `subprocess python3 upload_mp4_to_youtube.py ...` 呼叫。
PyInstaller 打包後無 python3 可叫，需改為 **in-process 可呼叫 API**：

- 將 `main()` 邏輯抽出可重複使用的函式（如 `run_upload(ns) -> dict`），`main()` 保留作為 CLI 入口（argparse 行為不變）
- GUI worker 直接 import 呼叫，避免 subprocess python3 相依
- YouTube 重新授權：自訂 `get_code` callback（`auth.get_resource` 的 `get_code_callback` 參數）：
  - 對話框顯示 OAuth URL + 「在瀏覽器開啟」按鈕（`QDesktopServices.openUrl`）
  - 輸入框貼入 verification code → 回傳給 auth 流程
  - 憑證儲存位置不變：`~/.youtube-upload-credentials.json`，client secrets 沿用 repo root `client_secret*.json` 自動偵測

## 打包（PyInstaller + 內建 ffmpeg）

- `app.spec`：`--add-binary "build/bin/<platform>/ffmpeg:."` 包入
- 各平台 build 腳本負責下載對應 static ffmpeg：
  - mac：osx 靜態版
  - linux：johnvansickle static build
  - windows：gyan.dev build（ffmpeg.exe）
- `ffmpeg.py` 解析順序：執行檔所在目錄 → PyInstaller `_MEIPASS` → PATH → 錯誤對話框
- 輸出至 `dist/`

## 測試

- pytest：
  - `find_continous_video` 的 `merge_all` 邏輯（以偽檔名驗證分組/合併行為）
  - 靜音指令產生（N=0 純 `-c copy`；N>0 加 `-af` + `-c:a aac`；N≥長度邊界）
  - 上傳結果解析邏輯（沿用既有行為，重構後回歸測試）
- 手動驗證：GUI 啟動、目錄選擇、時間選擇、靜音輸出（前 N 秒 volumedetect 確認無聲）、授權流程
- 已實測確認：`-af "volume=0.0:enable='lt(t,N)'" -c:v copy -c:a aac` 單一 pass 可正確產生前 N 秒靜音

## 非目標（YAGNI）

- 不做 multi-camera（Front/Rear 並排）功能
- 不做安裝程式（NSIS/dmg），僅提供 build 腳本與 dist 產物
- 不處理 TS 檔案的 timestamp 校正或轉碼修復