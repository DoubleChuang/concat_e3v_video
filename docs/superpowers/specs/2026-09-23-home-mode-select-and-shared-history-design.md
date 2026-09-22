# 設計：首頁模式選擇 + 共用紀錄檔設定

日期：2026-09-23
狀態：已由使用者核准（方案 A；移除 E3V 視窗內「單獨上傳影片」按鈕；一併加處理中關閉保護）

## 動機

程式目前啟動直接進入 E3V 處理視窗，「單獨上傳」只是視窗內一顆按鈕開出的 modal 對話框。
需求：
1. 程式入口改為「首頁」：兩顆大按鈕（「處理E3V影片」「單獨上傳影片」）分別進入不同模式；閒置狀態可回上頁（首頁）重新選擇模式。
2. 紀錄檔設定欄位移到首頁（兩模式共用一份設定）；E3V 模式上傳時也要開始寫上傳紀錄。

## 現況摘要

- 入口：`app/main.py` → `MainWindow`（E3V 模式）直接顯示。
- 單獨上傳：`MainWindow._open_upload_window` → `UploadWindow(self).exec()`（modal）。
- 紀錄檔欄位：目前只在 `UploadWindow`（`history_edit` + 瀏覽 + settings key `upload_history_file`）。
- E3V 模式（`run_pipeline`）上傳後**不寫**紀錄。
- `MainWindow` 沒有處理中關閉保護（處理中關閉視窗 = 連 worker 一起終止）。
- 共用函式：`upload_mp4_to_youtube.py` 的 `build_history_record`、`append_upload_history`、`UPLOAD_HISTORY_DEFAULT`（`~/concat-e3v-upload-history.json`）。`upload_video` 回傳 dict 含 `file`/`exit_code`/`video_id`/`error`，與 `build_history_record` 相容。

## 需求

### 1. 首頁 `HomeWindow`（新檔 `app/ui/home_window.py`）

- `HomeWindow(QWidget)`：標題 + 兩顆大按鈕「處理E3V影片」「單獨上傳影片」。
- 紀錄檔列：`QLineEdit`（placeholder `預設: {UPLOAD_HISTORY_DEFAULT}`）+ 瀏覽按鈕（`QFileDialog.getSaveFileName`，filter `JSON (*.json)`，初始目錄為現值或 `Path.home()`）。
- 設定鍵 `upload_history_file`，欄位變更即存（auto-save，同 MainWindow 既有模式）。
- signals：`e3v_requested`、`upload_requested`。
- `closeEvent` → `QApplication.instance().quit()`。

### 2. `app/main.py` 控制器

- `app.setQuitOnLastWindowClosed(False)`（退出時機改由首頁控制）。
- 建立 `HomeWindow` + `MainWindow`（一次建立，E3V 視窗起初隱藏）。
- 接線：
  - `home.e3v_requested` → `home.hide()`、`main_window.show()`
  - `home.upload_requested` → `UploadWindow(home).exec()`（modal；關閉後首頁維持顯示）
  - `main_window.back_requested` → `main_window.hide()`、`home.show()`
- 首頁關閉 → quit（由 HomeWindow.closeEvent 處理）。

### 3. `MainWindow` 修改（E3V 模式）

- 移除「單獨上傳影片...」按鈕與 `_open_upload_window`。
- 新增「回首頁」按鈕：signal `back_requested`；處理中（worker 執行中）disabled。
- `closeEvent`：
  - 處理中 → `event.ignore()` + 提示「請先取消或等待完成」。
  - 閒置 → 發 `back_requested` + `event.accept()`。
- `_build_cfg`：讀取設定 `upload_history_file`（helper）→ `PipelineConfig.history_file`。

### 4. `UploadWindow` 修改

- 移除紀錄檔欄位（`history_edit`、`_pick_history_file`、settings 讀寫）——欄位只留首頁一份。
- `_on_upload`：改為即時讀取設定（helper），空值用 `UPLOAD_HISTORY_DEFAULT.as_posix()` → `UploadConfig.history_file`。

### 5. `app/settings.py` 新 helper

```python
def get_upload_history_file(s: AppSettings) -> str:
    return str(s.value("upload_history_file", "") or UPLOAD_HISTORY_DEFAULT.as_posix())
```

兩模式共用，避免重複邏輯。

### 6. `app/pipeline.py`（E3V 模式寫紀錄）

- `PipelineConfig` 加 `history_file: str | None = None`。
- `run_pipeline`：每個上傳結果**即時**寫入一筆：
  `append_upload_history(history_file, [build_history_record(result)])`，
  `try/except OSError` → `cfg.log(f"無法寫入上傳紀錄: {exc}")`（與 UploadWorker 相同容錯模式）。
- 寫入時機在 cancel 檢查之前（取消也保留已完成上傳的紀錄，與 UploadWorker 行為一致）。
- 完全重用既有 `build_history_record`/`append_upload_history`/`UPLOAD_HISTORY_DEFAULT`，JSON schema 不變。

### 7. 資料流

```
首頁紀錄檔欄位 ──auto-save──▶ QSettings("upload_history_file")
                                  │
          ┌───────────────────────┴───────────────────────┐
  單獨上傳模式（開始時讀）                          E3V 模式（開始時讀）
  UploadConfig.history_file                      PipelineConfig.history_file
          └──────────┬────────────────────────────────────┘
             build_history_record / append_upload_history（同一 JSON）
```

兩模式皆於開始時「即時讀設定」（首頁改完立即生效，不需重啟）。

## 測試

- 新 `tests/test_home_window.py`：按鈕存在與文字、點擊發 signal、紀錄檔 settings 存讀（IniFormat + tmp dir，沿用 `tests/test_settings.py` 模式）、closeEvent 觸發 quit。
- 新 `tests/test_mode_flow.py`（offscreen）：首頁→E3V（首頁隱藏/E3V 顯示）、首頁→上傳 modal、E3V 回首頁（E3V 隱藏/首頁顯示）、回首頁按鈕處理中 disabled、E3V 閒置關閉回首頁、處理中關閉被 ignore、首頁關閉觸發 quit。
- `tests/test_gui_smoke.py`：補 `_build_cfg` 的 `history_file` 斷言。
- `tests/test_pipeline.py`：E3V 模式寫紀錄（成功/失敗各一筆）、寫入失敗不中斷（log 有訊息）、未設 `history_file` 不寫。
- 基準 75 passed；驗證後重建 `dist/concat-e3v.app`（`PYTHON="$(pwd)/.venv-build/bin/python" ./build/build_mac.sh`）。

## 不變更

- `upload_mp4_to_youtube.py`、`app/upload_worker.py`（共用函式與 worker 不變）。
- 上傳紀錄 JSON schema。
- 單獨上傳模式的其他欄位與行為。