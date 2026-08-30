# 設計：GUI 單獨上傳功能（不需合併即可上傳影片）

日期：2026-08-30

## 背景與目標

目前 GUI（`concat-e3v`）的上傳只能跟在合併管線之後（`PipelineConfig.upload_enabled`），要上傳既有影片檔必須走完整個合併流程。CLI 已有單獨上傳（`python3 upload_mp4_to_youtube.py file.mp4` / `--video-dir`），多格式變更後即支援全部格式，CLI 不需要新功能。

目標：GUI 新增獨立上傳視窗，可選單檔（多選）或整個資料夾批次上傳，不需經過合併。CLI 無新增需求。

## 相依

本功能依賴「多格式白名單」spec（`2026-08-30-youtube-upload-multi-format-design.md`）的 `SUPPORTED_VIDEO_EXTENSIONS` 常數。實作順序：多格式先、單獨上傳後。

## 變更點

### 1. `upload_mp4_to_youtube.py`：抽出 `list_video_files` helper

- 新增模組層級函式 `list_video_files(directory: str | Path) -> list[Path]`：
  - 展開目錄，僅回傳 `path.is_file()` 且 `path.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS` 的檔案，依檔名排序
  - 目錄不存在或不為目錄時回傳空清單（呼叫端自行驗證）
- `_resolve_video_targets` 的 `--video-dir` 分支改用此 helper（刪除內嵌迴圈）

### 2. 新增 `app/auth_flow.py`：共用授權迴圈

- 自 `PipelineWorker._auth_check` / `_get_code_callback` 抽出（約 20 行），供兩個 worker 共用：
  - `AuthFlow(cancel_event, code_event, retry_event)` 或等價的小型類別/函式，行為與現有完全一致：
    - `get_code_callback(url)`：emit 授權碼需求 → 等待 code event → cancel 時拋 `RuntimeError("auth cancelled")`
    - `auth_check(client_secrets, credentials_file)`：迴圈呼叫 `check_youtube_upload_available`，失敗時 emit auth_required 並等待 retry event，cancel 時回傳 False
- `PipelineWorker` 改用此 helper（行為不變，現有測試需繼續通過）

### 3. 新增 `app/upload_worker.py`：`UploadWorker(QThread)`

- Signals 與 `PipelineWorker` 相同：`log(str)`、`finished(dict)`、`auth_required(str)`、`auth_code_required(str)`
- 參數：`UploadConfig` dataclass：
  - `files: list[str]`（已展開的檔案清單）
  - `title: str | None`、`description: str | None`、`privacy: str = "private"`、`tags: str | None`、`playlist: str | None`
  - `client_secrets: str | None`、`credentials_file: str | None`
- `run()`：
  1. 先 `AuthFlow.auth_check(...)`；失敗（cancel）→ `finished` emit `{"status": "aborted", "reason": "youtube-auth-failed", ...}`
  2. 逐檔 `upload_video(...)`（title 傳 None 由 API 預設為檔名 stem），每檔 log 結果，收集 `uploaded` / `failed`
  3. 中途 cancel → `{"status": "aborted", "reason": "cancelled", ...}`（已完成的仍列出）
  4. 完成 → `{"status": "done", "uploaded": [...], "failed": [...], "reason": None}`
  5. 例外 → `{"status": "failed", "reason": str(exc), ...}`（比照 `PipelineWorker.run` 的包法）

### 4. 新增 `app/ui/upload_window.py`：`UploadWindow(QDialog)`

- 標題「上傳到 YouTube」
- 輸入區：
  - 「選擇檔案...」：`QFileDialog.getOpenFileNames`，filter 由 `SUPPORTED_VIDEO_EXTENSIONS` 動態組出（例如 `"影片 (*.mp4 *.mov *.mkv ...)"`）
  - 「選擇資料夾...」：`QFileDialog.getExistingDirectory`，選定後以 `list_video_files()` 展開
  - `QListWidget` 顯示已選檔案清單（可選移除選取項），支援去重複
- 欄位（沿用主視窗 upload_group 的欄位與 `AppSettings` key）：
  - 標題（placeholder「預設 = 檔名」）、描述（`QPlainTextEdit` 限高 70）、隱私（private/unlisted/public）、標籤、播放清單、Client Secrets（+瀏覽按鈕）
  - `_load_settings` / `_save_settings` 與主視窗共用同一組 key（`upload_title`、`upload_description`、`upload_privacy`、`upload_tags`、`upload_playlist`、`client_secrets`），切換視窗值互通
- Log 區（readonly `QPlainTextEdit`）+「上傳」/「停止」按鈕（按鈕文字切換，比照主視窗）
- 授權流程：`auth_required` → `QMessageBox.question`（重新授權？）；`auth_code_required` → 重用 `AuthDialog`；行為與 `MainWindow._on_auth_required` / `_on_auth_code_required` 一致
- 完成：`QMessageBox.information` 摘要（成功數、video_id 清單；失敗數與原因寫入 log），失敗存在時用 warning 呈現
- 關閉視窗時若 worker 仍在跑 → 先 `cancel()` 再接受關閉

### 5. `app/ui/main_window.py`：入口

- 在「開始處理」按鈕上方（或同列）新增「單獨上傳影片...」按鈕 → `UploadWindow(self).exec()`

### 6. 測試

- `tests/test_upload_worker.py`（新增）：
  - fake `upload_video`（monkeypatch `app.upload_worker.upload_video`）：驗證逐檔呼叫、參數傳遞、`uploaded`/`failed` 收集、`finished` 結果結構
  - auth 失敗（`AuthFlow.auth_check` 回傳 False）→ aborted
  - cancel（設定 cancel event）→ aborted/cancelled
  - 沿用 test_worker.py 的 fake 模式（`youtube_upload` 套件注入）
- `list_video_files` 測試（放 `tests/test_upload_api.py`）：混合格式目錄（`.mp4`、`.mov`、`.mkv`、`.txt`、`.DS_Store`）只回傳支援格式且排序；目錄不存在回傳空清單
- 既有 `tests/test_worker.py` 必須全部繼續通過（`PipelineWorker` 改用 `AuthFlow` 後行為不變）

## 不做的事（YAGNI）

- CLI 不新增功能（`--video-dir` 批次 + `--exclude` 已存在）
- 不做拖放、不做上傳進度條（`youtube-upload` 回傳結構無進度）、不做已上傳記錄/去重（每個檔案是否上傳由使用者決定）
- 不改 `PipelineConfig` / 合併管線行為
- `UploadWindow` 不支援排程（publish-at）、縮圖、錄製日期等進階欄位（主視窗 upload_group 也沒有）

## 錯誤處理

- 無選取檔案時按「上傳」→ warning「請先選擇檔案」
- 單檔上傳失敗不中斷批次（逐檔回報，比照 CLI）
- 授權失敗可重試（沿用現有 retry 流程）或取消
- Client Secrets 未填時沿用 `_default_client_secrets_path()` 行為（`upload_video` 內建 fallback），與主視窗一致

## 驗證

- `pytest` 全數通過（新增 test_upload_worker.py、test_upload_api.py 擴充）
- 手動 smoke：`python3 app/main.py` 開啟主視窗 →「單獨上傳影片...」→ 選 `.mkv` 檔 → 上傳成功取得 video_id