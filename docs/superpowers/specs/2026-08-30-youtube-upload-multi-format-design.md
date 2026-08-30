# 設計：upload_mp4_to_youtube.py 支援多種影片格式

日期：2026-08-30

## 背景與目標

`upload_mp4_to_youtube.py` 目前只接受 `.mp4`：`--video-dir` 過濾、單檔副檔名檢查、`upload_video()` API 三處都有 `.mp4` 限制。底層 vendored `youtube-upload` 本身不限制格式，限制完全來自 wrapper。

目標：讓 wrapper 接受 YouTube 官方支援的影片格式，白名單方式驗證，錯誤訊息列出支援格式。

## 格式白名單

模組層級常數 `SUPPORTED_VIDEO_EXTENSIONS`（frozenset[str]，全部小寫，含前導點）：

```
.mp4 .mov .m4v .mkv .avi .wmv .flv .webm
.mpg .mpeg .mpeg4 .mpegps .3gp .3gpp .3g2 .mts .m2ts
```

- 對齊 YouTube 官方支援清單（MOV、MPEG-1/2、MPEG4、MP4、MPG、AVI、WMV、MPEGPS、FLV、3GPP、WebM、DNxHR、ProRes、CineForm、HEVC/H.265 容器）
- 額外加入 `.mkv`（使用者要求；MKV 可內含 HEVC）
- `.mkv` 以外的非官方格式（如 `.ts` 之外的罕見容器）一律拒絕

## 變更點

### 1. `upload_mp4_to_youtube.py`

- 新增模組層級 `SUPPORTED_VIDEO_EXTENSIONS: frozenset[str]`
- `_resolve_video_targets`（`--video-dir` 分支）：候選過濾 `path.suffix.lower() == ".mp4"` → `path.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS`
- `_resolve_video_targets`（單檔分支）：`!= ".mp4"` 檢查 → 不在白名單則 `parser.error`，訊息列出支援格式（沿用現有 "Only .mp4 is supported by this wrapper (got: %s)" 的風格改寫）
- `upload_video()`：`!= ".mp4"` 檢查 → 不在白名單則 `ValueError`，訊息列出支援格式
- Help 文字與 docstring：
  - positional `video`：`"Path to the .mp4 file"` → `"Path to a supported video file"`
  - `--video-dir`：`"Upload all .mp4 files directly under this folder"` → `"Upload all supported video files directly under this folder"`
  - 檔案頂部 docstring：`"Upload a local MP4 to YouTube"` → 泛指影片檔案
  - `upload_video()` docstring：`"Upload a single mp4 in-process"` → 泛指影片檔案
- log 訊息：`"no mp4 files selected for upload"` → `"no supported video files selected for upload"`
- 檔名 `upload_mp4_to_youtube.py` 保留（`main.py`、`app/pipeline.py`、`app/worker.py` 的 import 不動）；`DEFAULT_LOG_FILE` 不變

### 2. `tests/test_upload_api.py`

- `test_upload_video_rejects_non_mp4` → 改為 `test_upload_video_rejects_unsupported_format`：
  - 建立 `.txt` 檔案 → 期望 `ValueError`
  - 傳目錄（無副檔名）→ 期望 `ValueError`（`Path.exists()` 對目錄為 True，靠白名單檢查攔下）
- 新增參數化測試 `test_upload_video_accepts_supported_formats`，參數固定為 `.mp4`、`.mov`、`.mkv`、`.avi`、`.webm`、`.3gp` 六種：均可通過檢查並上傳（沿用 fake `_upload_one_video` 模式）
- 新增 `_resolve_video_targets` 的 `--video-dir` 混合格式測試：目錄內同時有 `.mp4`、`.mov`、`.mkv`、`.txt`、`.DS_Store`，僅支援格式被選中（直接建 `argparse.Namespace` 呼叫函式，不跑 `main()`）

### 3. `README.md`

- 上傳指令範例文字從「上傳 mp4」改為泛指「上傳影片」，可列支援格式摘要

## 不做的事（YAGNI）

- 不支援 `--ext` 自訂格式參數
- 不改檔名、不改 log 檔名、不影響 `app/` 套件 import
- 不檢查檔案內容（容器/codec），只做副檔名白名單驗證；非影片內容的錯誤由 YouTube API 回報
- 不修改 vendored `youtube-upload/`

## 錯誤處理

- 單檔路徑非白名單格式 → `parser.error`（CLI）/ `ValueError`（API），訊息含完整支援清單
- 目錄無任何支援格式 → 現有行為不變（warning + 空結果，exit 0）
- 上傳失敗處理不變（沿用 `_upload_one_video` 既有 exit code / error 回報機制）

## 驗證

- `pytest tests/test_upload_api.py` 通過
- 全測試套件 `pytest` 通過
- 手動 smoke：`python3 upload_mp4_to_youtube.py foo.txt` 應印出支援格式清單錯誤；`--video-dir` 指向含混合格式目錄時僅選中支援格式