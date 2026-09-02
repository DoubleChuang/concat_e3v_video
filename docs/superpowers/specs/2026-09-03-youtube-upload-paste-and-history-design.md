# 設計：貼上檔案路徑 + 上傳紀錄 JSON mapping

日期：2026-09-03

## 背景與目標

單獨上傳視窗（`UploadWindow`）目前支援檔案多選、多資料夾 + 遞迴。新增兩項功能：

1. **貼上多個檔案路徑**：使用者可貼入多個檔案位置（換行 / 逗號 / 引號），上傳失敗時方便重新挑選多個檔案。
2. **上傳紀錄 JSON mapping**：上傳成功時記錄「本機檔案位置 ↔ YouTube 位置」；失敗記錄檔案位置 + 失敗原因。GUI 與 CLI 都要寫入。

## 決策（已與使用者確認）

- 貼入格式：換行 + 逗號 + 引號（`'...'` / `"..."`）+ `~` 展開
- 無效路徑（不存在 / 不支援副檔名）：跳過 + 警告列出原因，不阻擋其他有效路徑
- JSON 路徑：GUI 可設定欄位（預設 `~/concat-e3v-upload-history.json`，persisted）；CLI 用 `--history-file` 參數（同預設值）
- 同檔案重複上傳：每次追加一筆（保留歷史）
- 範圍：GUI + CLI 都要寫入

## JSON Schema

```json
{
  "uploads": [
    {
      "file": "/path/video.mp4",
      "status": "success",
      "video_id": "abc123",
      "youtube_url": "https://youtu.be/abc123",
      "timestamp": "2026-09-03T10:00:00+08:00"
    },
    {
      "file": "/path/bad.mp4",
      "status": "failed",
      "error": "youtube-upload exited with code 1",
      "timestamp": "2026-09-03T10:05:00+08:00"
    }
  ]
}
```

- `timestamp`：`datetime.now().astimezone().isoformat()`
- `youtube_url`：`https://youtu.be/{video_id}`

## 變更點

### 1. `upload_mp4_to_youtube.py`

**`is_supported_video_file(path: Path) -> bool`**
- `path.is_file() and path.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS`
- `list_video_files` 的過濾改用此 helper（消除重複判斷）

**上傳紀錄函式**
- `UPLOAD_HISTORY_DEFAULT = Path.home() / "concat-e3v-upload-history.json"`
- `build_history_record(result: dict) -> dict`：
  - `exit_code == 0` → `{"file", "status": "success", "video_id", "youtube_url", "timestamp"}`
  - 否則 → `{"file", "status": "failed", "error", "timestamp"}`；`error` = `result.get("error")`，缺省時用 `f"exit code {exit_code}"`
- `append_upload_history(history_file: str | Path, records: list[dict]) -> None`：
  - 讀既有檔案：有效 JSON 且含 `uploads` list → 追加；不存在 / 解析失敗 / 格式不符 → 視為空清單
  - `json.dump`（`ensure_ascii=False, indent=2`）
  - 原子寫回：`tempfile.NamedTemporaryFile`（同目錄）+ `os.replace`

**CLI `main()`**
- 新增 `--history-file` 參數，預設 `UPLOAD_HISTORY_DEFAULT`，`expanduser().resolve()`
- 上傳迴圈結束後：若 `uploaded` 或 `failed` 非空 → `append_upload_history(history_file, 所有 records)`（成功 + 失敗一起批次寫入）
- 既有 CLI 行為不變（參數相容）

### 2. `app/upload_worker.py`

- `UploadConfig` 新增欄位 `history_file: str | None = None`（None = 不寫）
- `run()` 中每完成一個檔案（拿到 result 後）即 `append_upload_history(cfg.history_file, [build_history_record(result)])`（中途取消/例外也保留已完成紀錄；cancel 後不再寫）

### 3. `app/ui/upload_window.py`

**貼上路徑區塊**（「移除選取/清空」列下方）：
- `QPlainTextEdit`（限高 ~70，placeholder「貼上檔案路徑，一行一個，支援逗號分隔與引號」）+「加入清單」按鈕

**純函式（模組層級，可單元測試）**
- `parse_pasted_paths(text: str) -> list[str]`：
  - 以換行與逗號切分 → 每段 strip 首尾空白 → 去包覆引號（`'` / `"`）→ `Path(...).expanduser()` 字串化；空段丟棄
- `resolve_pasted_paths(text: str) -> tuple[list[Path], list[tuple[str, str]]]`：
  - 回傳（有效檔, [(無效路徑, 原因)]）；原因：「檔案不存在」/「不支援的格式」

**「加入清單」處理**
- 有效路徑 → `_add_paths`（沿用去重複）
- 無效 → `QMessageBox.warning`（標題「部分路徑無法加入」），列出「路徑（原因）」逐行；輸入全無效時一樣警告
- 貼上文字框不自動清空

**紀錄檔欄位**
- form 新增「紀錄檔:」`QLineEdit` + 瀏覽按鈕（`QFileDialog.getSaveFileName`，filter `JSON (*.json)`）
- 空值 → `_on_upload` 時以 `UPLOAD_HISTORY_DEFAULT` 為預設傳給 `UploadConfig.history_file`
- `_load_settings` / `_save_settings` 新增 key `upload_history_file`

### 4. 測試

- `tests/test_upload_api.py`（或新 `tests/test_upload_history.py`）：
  - `is_supported_video_file`：存在+支援 / 不存在 / 不支援格式 / 目錄
  - `build_history_record`：成功（url 正確）/ 失敗（error 欄位）
  - `append_upload_history`：新檔建立、舊檔追加（保留舊紀錄）、損毀檔視為空、原子寫入後 JSON 可讀
- 新 `tests/test_upload_window.py`（純函式，不需 QApplication）：
  - `parse_pasted_paths`：換行、逗號、引號、`~`、首尾空白、空段
  - `resolve_pasted_paths`：有效通過、不存在、`.txt` 不支援、混合輸入
- `tests/test_upload_worker.py`：設 `history_file` → fake 上傳成功+失敗各一 → JSON 有 2 筆且欄位正確；不設 `history_file` → 不產生檔案（既有測試不受影響）

## 不做的事（YAGNI）

- CLI 不新增讀取/列出紀錄的功能
- 不做失敗自動重試、不做 JSON 的 UI 檢視器
- 貼入資料夾路徑不支援（僅檔案）

## 驗證

- `pytest -q` 全綠
- offscreen smoke：貼上混合輸入 → 有效進清單、無效警告；紀錄檔欄位預設值正確；fake worker 寫出 JSON 內容正確
- 重建 `dist/concat-e3v.app` 供使用者測試