# YouTube 多格式上傳 + GUI 單獨上傳 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓 `upload_mp4_to_youtube.py` 接受 YouTube 官方支援（含 `.mkv`）的所有影片格式，並在 GUI 新增不需合併即可上傳的獨立視窗。

**Architecture:** 在 `upload_mp4_to_youtube.py` 建立 `SUPPORTED_VIDEO_EXTENSIONS` 白名單與 `list_video_files()` helper；抽出 `app/auth_flow.py` 共用授權迴圈；新增 `app/upload_worker.py`（QThread）與 `app/ui/upload_window.py`（QDialog）由主視窗按鈕開啟。CLI 批次上傳（`--video-dir`）沿用既有參數。

**Tech Stack:** Python 3.11、PySide6 6.5+、pytest、vendored `youtube-upload`（不修改）

## Global Constraints

- 測試環境：pyenv env `e3v`（Python 3.11.1），baseline `pytest -q` = 41 passed
- 檔名 `upload_mp4_to_youtube.py`、`DEFAULT_LOG_FILE` 不變；`main.py`、`app/pipeline.py`、`app/worker.py` 既有 import 相容
- 不修改 vendored `youtube-upload/`；不改 `PipelineConfig` / 合併管線行為
- `SUPPORTED_VIDEO_EXTENSIONS` 內容（全部小寫、含前導點、frozenset）：
  `.mp4 .mov .m4v .mkv .avi .wmv .flv .webm .mpg .mpeg .mpeg4 .mpegps .3gp .3gpp .3g2 .mts .m2ts`
- GUI 文字用中文，與主視窗 `upload_group` 風格一致
- 測試檔 `tests/test_worker.py` 開頭有 `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")`；新 GUI 相關測試檔必須沿用

---

### Task 1: 多格式白名單

**Files:**
- Modify: `upload_mp4_to_youtube.py`
- Test: `tests/test_upload_api.py`
- Modify: `README.md:90-96`

**Interfaces:**
- Produces: `up.SUPPORTED_VIDEO_EXTENSIONS: frozenset[str]`（模組層級常數，Task 3 使用）

- [ ] **Step 1: 更新測試（先寫失敗測試）**

在 `tests/test_upload_api.py` 把 `test_upload_video_rejects_non_mp4`（第 117-119 行）整段替換為：

```python
@pytest.mark.parametrize("suffix", [".mp4", ".mov", ".mkv", ".avi", ".webm", ".3gp"])
def test_upload_video_accepts_supported_formats(monkeypatch, tmp_path, fake_vendored, suffix):
    video = tmp_path / f"clip{suffix}"
    video.write_bytes(b"x")
    seen = {}

    def fake_upload_one(ns, video_path, youtube_upload_main):
        seen["file"] = video_path.as_posix()
        return {"file": video_path.as_posix(), "name": video_path.name, "exit_code": 0, "video_id": "abc"}

    monkeypatch.setattr(up, "_upload_one_video", fake_upload_one)
    result = up.upload_video(str(video))
    assert result["exit_code"] == 0
    assert seen["file"] == video.as_posix()


@pytest.mark.parametrize("suffix", [".txt", ".pdf"])
def test_upload_video_rejects_unsupported_format(tmp_path, suffix):
    video = tmp_path / f"clip{suffix}"
    video.write_bytes(b"x")
    with pytest.raises(ValueError):
        up.upload_video(str(video))


def test_upload_video_rejects_directory(tmp_path):
    with pytest.raises(ValueError):
        up.upload_video(str(tmp_path))
```

- [ ] **Step 2: 執行確認失敗**

Run: `pytest tests/test_upload_api.py -q`
Expected: `test_upload_video_accepts_supported_formats` 的 `.mov/.mkv/.avi/.webm/.3gp` 參數 FAIL（ValueError），`.txt` 參數 PASS、`test_upload_video_rejects_directory` PASS（舊行為仍拒絕非 mp4）

- [ ] **Step 3: 實作白名單常數**

在 `upload_mp4_to_youtube.py` 第 24 行 `DEFAULT_LOG_FILE` 之後新增：

```python
SUPPORTED_VIDEO_EXTENSIONS = frozenset({
    ".mp4", ".mov", ".m4v", ".mkv", ".avi", ".wmv", ".flv", ".webm",
    ".mpg", ".mpeg", ".mpeg4", ".mpegps", ".3gp", ".3gpp", ".3g2",
    ".mts", ".m2ts",
})
```

- [ ] **Step 4: 改三處檢查**

4a. `_resolve_video_targets` 的 `--video-dir` 分支（第 139-144 行）：

```python
        candidates = sorted(
            path
            for path in video_dir.iterdir()
            if path.is_file()
            and path.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS
        )
```

4b. `_resolve_video_targets` 的單檔分支（第 146-154 行）整段替換：

```python
    else:
        video_path = Path(ns.video).expanduser().resolve()
        if not video_path.exists():
            parser.error(f"Video not found: {video_path}")
        if video_path.suffix.lower() not in SUPPORTED_VIDEO_EXTENSIONS:
            parser.error(
                "Unsupported format (got: %s). Supported: %s"
                % (
                    video_path.suffix or "(none)",
                    ", ".join(sorted(SUPPORTED_VIDEO_EXTENSIONS)),
                )
            )
        candidates = [video_path]
```

4c. `upload_video` 函式（第 422-426 行）：

```python
    video_path = Path(video_path).expanduser().resolve()
    if not video_path.exists():
        raise FileNotFoundError(video_path.as_posix())
    if video_path.suffix.lower() not in SUPPORTED_VIDEO_EXTENSIONS:
        raise ValueError(
            "Unsupported format (got: %s). Supported: %s"
            % (
                video_path.suffix or "(none)",
                ", ".join(sorted(SUPPORTED_VIDEO_EXTENSIONS)),
            )
        )
```

- [ ] **Step 5: 更新 help 文字、docstring、log 訊息**

- 第 2 行模組 docstring：`"Upload a local MP4 to YouTube using the vendored \`youtube-upload\` project."` → `"Upload a local video file to YouTube using the vendored \`youtube-upload\` project."`
- 第 269 行 parser description：`"Upload an MP4 to YouTube (wrapper for vendored youtube-upload)."` → `"Upload a video to YouTube (wrapper for vendored youtube-upload)."`
- 第 274 行 `video` positional help：`"Path to the .mp4 file"` → `"Path to a supported video file"`
- 第 279 行 `--video-dir` help：`"Upload all .mp4 files directly under this folder"` → `"Upload all supported video files directly under this folder"`
- 第 421 行 `upload_video` docstring：`"Upload a single mp4 in-process (no subprocess). Returns result dict."` → `"Upload a single video file in-process (no subprocess). Returns result dict."`
- 第 568 行：`logging.warning("no mp4 files selected for upload")` → `logging.warning("no supported video files selected for upload")`

- [ ] **Step 6: 更新 README**

`README.md` 第 92 行 `執行以下指令 上傳 mp4：` 改為：

```markdown
執行以下指令上傳影片（支援 mp4、mov、mkv、avi、webm、3gp 等格式，單檔或 `--video-dir` 批次）：

```

- [ ] **Step 7: 執行確認全部通過**

Run: `pytest tests/test_upload_api.py -q && pytest -q`
Expected: 全數 PASS（41 + 新增參數化案例）

- [ ] **Step 8: Commit**

```bash
git add upload_mp4_to_youtube.py tests/test_upload_api.py README.md
git commit -m "feat: support all YouTube video formats in upload wrapper"
```

---

### Task 2: 抽出 AuthFlow 共用授權迴圈

**Files:**
- Create: `app/auth_flow.py`
- Modify: `app/worker.py:36-57`（`_get_code_callback` / `_auth_check` 改用它）
- Test: `tests/test_worker.py`

**Interfaces:**
- Produces: `app.auth_flow.AuthFlow`：
  - `AuthFlow(code_event: threading.Event, retry_event: threading.Event, cancel_event: threading.Event, emit_code_required: Callable[[str], None], emit_auth_required: Callable[[str], None])`
  - `set_code(code: str) -> None`
  - `auth_check(client_secrets: str | None, credentials_file: str | None) -> bool`（內部呼叫 `app.auth_flow.check_youtube_upload_available`，Task 4 的 `UploadWorker` 依賴此 API）
- Consumes: `upload_mp4_to_youtube.check_youtube_upload_available`

- [ ] **Step 1: 更新 test_worker.py 的 monkeypatch 目標（先讓舊測試指向新位置）**

`tests/test_worker.py` 中 5 處 `monkeypatch.setattr("app.worker.check_youtube_upload_available", fake_check)`（第 53、93、152、182、200 行）全部改為：

```python
    monkeypatch.setattr("app.auth_flow.check_youtube_upload_available", fake_check)
```

- [ ] **Step 2: 新增 `app/auth_flow.py`**

```python
import threading
from typing import Callable

from upload_mp4_to_youtube import check_youtube_upload_available


class AuthFlow:
    """Reusable YouTube auth retry loop shared by Qt workers."""

    def __init__(
        self,
        code_event: threading.Event,
        retry_event: threading.Event,
        cancel_event: threading.Event,
        emit_code_required: Callable[[str], None],
        emit_auth_required: Callable[[str], None],
    ):
        self._code_event = code_event
        self._retry_event = retry_event
        self._cancel_event = cancel_event
        self._emit_code_required = emit_code_required
        self._emit_auth_required = emit_auth_required
        self._code: str | None = None

    def set_code(self, code: str) -> None:
        self._code = code
        self._code_event.set()

    def _get_code_callback(self, url: str) -> str:
        self._emit_code_required(url)
        self._code_event.wait()
        self._code_event.clear()
        if self._cancel_event.is_set():
            raise RuntimeError("auth cancelled")
        return self._code or ""

    def auth_check(
        self,
        client_secrets: str | None,
        credentials_file: str | None,
    ) -> bool:
        while not self._cancel_event.is_set():
            try:
                check_youtube_upload_available(
                    client_secrets=client_secrets,
                    credentials_file=credentials_file,
                    get_code_callback=self._get_code_callback,
                )
                return True
            except BaseException as exc:
                self._emit_auth_required(str(exc))
                self._retry_event.wait()
                self._retry_event.clear()
        return False
```

- [ ] **Step 3: 重構 `app/worker.py`**

3a. 移除第 6 行 `from upload_mp4_to_youtube import check_youtube_upload_available`，改為：

```python
from app.auth_flow import AuthFlow
```

3b. `__init__`（第 15-22 行）結尾新增：

```python
        self._auth = AuthFlow(
            self._code_event,
            self._retry_event,
            self._cancel,
            emit_code_required=self.auth_code_required.emit,
            emit_auth_required=self.auth_required.emit,
        )
```

3c. `submit_auth_code`（第 29-31 行）改為：

```python
    def submit_auth_code(self, code: str) -> None:
        self._auth.set_code(code)
```

3d. 刪除 `_get_code_callback`（第 36-42 行）與 `_auth_check`（第 44-57 行）整段，改為：

```python
    def _auth_check(self) -> bool:
        return self._auth.auth_check(
            client_secrets=self._cfg.client_secrets,
            credentials_file=self._cfg.credentials_file,
        )
```

- [ ] **Step 4: 執行確認舊測試全過**

Run: `pytest tests/test_worker.py -q && pytest -q`
Expected: 41 passed（worker 授權相關 6 個測試行為不變）

- [ ] **Step 5: Commit**

```bash
git add app/auth_flow.py app/worker.py tests/test_worker.py
git commit -m "refactor: extract shared AuthFlow retry loop from PipelineWorker"
```

---

### Task 3: `list_video_files` helper

**Files:**
- Modify: `upload_mp4_to_youtube.py`
- Test: `tests/test_upload_api.py`

**Interfaces:**
- Consumes: Task 1 的 `SUPPORTED_VIDEO_EXTENSIONS`
- Produces: `list_video_files(directory: str | Path) -> list[Path]`（依檔名排序、只含支援格式的檔案；目錄不存在/非目錄回傳 `[]`；Task 4 的 `UploadWindow` 與本檔 `_resolve_video_targets` 使用）

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_upload_api.py` 結尾新增：

```python
def test_list_video_files_filters_and_sorts(tmp_path):
    for name in ["b.mp4", "a.mov", "c.mkv", "note.txt", ".DS_Store"]:
        (tmp_path / name).write_bytes(b"x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "nested.mp4").write_bytes(b"x")
    names = [p.name for p in up.list_video_files(tmp_path)]
    assert names == ["a.mov", "b.mp4", "c.mkv"]


def test_list_video_files_missing_dir(tmp_path):
    assert up.list_video_files(tmp_path / "nope") == []
```

- [ ] **Step 2: 執行確認失敗**

Run: `pytest tests/test_upload_api.py::test_list_video_files_filters_and_sorts tests/test_upload_api.py::test_list_video_files_missing_dir -q`
Expected: FAIL（AttributeError: module ... has no attribute 'list_video_files'）

- [ ] **Step 3: 實作 helper 並改 `_resolve_video_targets`**

3a. 在 `_resolve_video_targets` 之前新增：

```python
def list_video_files(directory: str | Path) -> list[Path]:
    directory = Path(directory).expanduser().resolve()
    if not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file()
        and path.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS
    )
```

3b. `_resolve_video_targets` 的 `--video-dir` 分支（Task 1 Step 4a 的程式碼）整段替換為：

```python
    if ns.video_dir is not None:
        video_dir = Path(ns.video_dir).expanduser().resolve()
        if not video_dir.exists():
            parser.error(
                f"Video directory not found: {video_dir}"
            )
        if not video_dir.is_dir():
            parser.error(
                f"Not a directory: {video_dir}"
            )
        candidates = list_video_files(video_dir)
```

- [ ] **Step 4: 執行確認通過**

Run: `pytest tests/test_upload_api.py -q`
Expected: 全數 PASS（含 Task 1 參數化案例）

- [ ] **Step 5: Commit**

```bash
git add upload_mp4_to_youtube.py tests/test_upload_api.py
git commit -m "feat: extract list_video_files helper for shared dir scanning"
```

---

### Task 4: `UploadWorker`（QThread）

**Files:**
- Create: `app/upload_worker.py`
- Test: `tests/test_upload_worker.py`

**Interfaces:**
- Consumes: Task 2 的 `app.auth_flow.AuthFlow`、`upload_mp4_to_youtube.upload_video`
- Produces: `app.upload_worker.UploadConfig`（dataclass：`files: list[str]`、`title: str | None = None`、`description: str | None = None`、`privacy: str = "private"`、`tags: str | None = None`、`playlist: str | None = None`、`client_secrets: str | None = None`、`credentials_file: str | None = None`）；`app.upload_worker.UploadWorker(QThread)` 含 signals `log(str)` / `finished(dict)` / `auth_required(str)` / `auth_code_required(str)` 與方法 `cancel()` / `submit_auth_code(code)` / `retry_auth()`（Task 5 的 `UploadWindow` 使用）

- [ ] **Step 1: 寫失敗測試**

新增 `tests/test_upload_worker.py`（沿用 test_worker.py 的 offscreen 設定與 `_run_and_pump` 模式）：

```python
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication

from app.upload_worker import UploadConfig, UploadWorker


@pytest.fixture(scope="module")
def qapp():
    app = QCoreApplication.instance() or QCoreApplication([])
    return app


def _run_and_pump(qapp, worker, timeout=5.0):
    import time as _t

    worker.start()
    deadline = _t.time() + timeout
    while worker.isRunning() and _t.time() < deadline:
        qapp.processEvents()
        _t.sleep(0.01)
    qapp.processEvents()
    return not worker.isRunning()


def test_upload_worker_uploads_all_files(qapp, monkeypatch, tmp_path):
    calls = []

    def fake_upload_video(path, **kw):
        calls.append((path, kw))
        return {"file": path, "name": path, "exit_code": 0, "video_id": f"id{len(calls)}"}

    monkeypatch.setattr("app.upload_worker.upload_video", fake_upload_video)
    monkeypatch.setattr("app.auth_flow.check_youtube_upload_available", lambda **kw: None)

    files = [str(tmp_path / "a.mp4"), str(tmp_path / "b.mov")]
    worker = UploadWorker(UploadConfig(files=files, title="T"))
    results = {}
    worker.finished.connect(lambda r: results.update(r))
    assert _run_and_pump(qapp, worker)
    assert results["status"] == "done"
    assert [c[0] for c in calls] == files
    assert len(results["uploaded"]) == 2


def test_upload_worker_auth_failure_aborts(qapp, monkeypatch, tmp_path):
    def fake_check(*a, **kw):
        raise SystemExit(2)

    monkeypatch.setattr("app.auth_flow.check_youtube_upload_available", fake_check)
    worker = UploadWorker(UploadConfig(files=[str(tmp_path / "a.mp4")]))
    results = {}
    auth_msgs = []

    def on_auth_required(msg):
        auth_msgs.append(msg)
        worker.cancel()

    worker.auth_required.connect(on_auth_required)
    worker.finished.connect(lambda r: results.update(r))
    assert _run_and_pump(qapp, worker)
    assert len(auth_msgs) == 1
    assert results["status"] == "aborted"


def test_upload_worker_reports_failed_files(qapp, monkeypatch, tmp_path):
    def fake_upload_video(path, **kw):
        if path.endswith("bad.mp4"):
            return {"file": path, "name": path, "exit_code": 1, "error": "boom"}
        return {"file": path, "name": path, "exit_code": 0, "video_id": "ok"}

    monkeypatch.setattr("app.upload_worker.upload_video", fake_upload_video)
    monkeypatch.setattr("app.auth_flow.check_youtube_upload_available", lambda **kw: None)
    worker = UploadWorker(
        UploadConfig(files=[str(tmp_path / "ok.mp4"), str(tmp_path / "bad.mp4")])
    )
    results = {}
    worker.finished.connect(lambda r: results.update(r))
    assert _run_and_pump(qapp, worker)
    assert results["status"] == "done"
    assert len(results["uploaded"]) == 1
    assert len(results["failed"]) == 1


def test_upload_worker_cancel_aborts(qapp, monkeypatch, tmp_path):
    def fake_upload_video(path, **kw):
        return {"file": path, "name": path, "exit_code": 0, "video_id": "x"}

    monkeypatch.setattr("app.upload_worker.upload_video", fake_upload_video)
    monkeypatch.setattr("app.auth_flow.check_youtube_upload_available", lambda **kw: None)
    worker = UploadWorker(UploadConfig(files=[str(tmp_path / "a.mp4")]))
    results = {}
    worker.finished.connect(lambda r: results.update(r))
    worker.start()
    worker.cancel()
    assert worker.wait(5000)
    qapp.processEvents()
    assert results["status"] == "aborted"
```

- [ ] **Step 2: 執行確認失敗**

Run: `pytest tests/test_upload_worker.py -q`
Expected: FAIL（ModuleNotFoundError: app.upload_worker）

- [ ] **Step 3: 實作 `app/upload_worker.py`**

```python
import threading
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from app.auth_flow import AuthFlow
from upload_mp4_to_youtube import upload_video


@dataclass
class UploadConfig:
    files: list[str]
    title: str | None = None
    description: str | None = None
    privacy: str = "private"
    tags: str | None = None
    playlist: str | None = None
    client_secrets: str | None = None
    credentials_file: str | None = None


class UploadWorker(QThread):
    log = Signal(str)
    finished = Signal(dict)
    auth_required = Signal(str)
    auth_code_required = Signal(str)

    def __init__(self, cfg: UploadConfig, parent=None):
        super().__init__(parent)
        self._cfg = cfg
        self._cancel = threading.Event()
        self._code_event = threading.Event()
        self._retry_event = threading.Event()
        self._auth = AuthFlow(
            self._code_event,
            self._retry_event,
            self._cancel,
            emit_code_required=self.auth_code_required.emit,
            emit_auth_required=self.auth_required.emit,
        )

    def cancel(self) -> None:
        self._cancel.set()
        self._code_event.set()
        self._retry_event.set()

    def submit_auth_code(self, code: str) -> None:
        self._auth.set_code(code)

    def retry_auth(self) -> None:
        self._retry_event.set()

    def _auth_check(self) -> bool:
        return self._auth.auth_check(
            client_secrets=self._cfg.client_secrets,
            credentials_file=self._cfg.credentials_file,
        )

    def run(self) -> None:
        cfg = self._cfg
        try:
            if not self._auth_check():
                self.finished.emit(
                    {
                        "status": "aborted",
                        "reason": "youtube-auth-failed",
                        "uploaded": [],
                        "failed": [],
                    }
                )
                return
            uploaded: list[dict] = []
            failed: list[dict] = []
            for file in cfg.files:
                if self._cancel.is_set():
                    break
                path = Path(file)
                self.log.emit(f"上傳 {path} 到 YouTube...")
                result = upload_video(
                    str(path),
                    title=cfg.title,
                    description=cfg.description,
                    tags=cfg.tags,
                    privacy=cfg.privacy,
                    playlist=cfg.playlist,
                    client_secrets=cfg.client_secrets,
                    credentials_file=cfg.credentials_file,
                )
                if result.get("exit_code") == 0:
                    self.log.emit(f"上傳成功: {result.get('video_id')}")
                    uploaded.append(result)
                else:
                    self.log.emit(f"上傳失敗: {result.get('error')}")
                    failed.append(result)
                if self._cancel.is_set():
                    break
            if self._cancel.is_set():
                self.finished.emit(
                    {
                        "status": "aborted",
                        "reason": "cancelled",
                        "uploaded": uploaded,
                        "failed": failed,
                    }
                )
                return
            self.finished.emit(
                {
                    "status": "done",
                    "uploaded": uploaded,
                    "failed": failed,
                    "reason": None,
                }
            )
        except BaseException as exc:
            self.finished.emit(
                {
                    "status": "failed",
                    "reason": str(exc),
                    "uploaded": [],
                    "failed": [],
                }
            )
```

- [ ] **Step 4: 執行確認通過**

Run: `pytest tests/test_upload_worker.py -q && pytest -q`
Expected: 新增 4 個測試 PASS，全套件 45+ passed

- [ ] **Step 5: Commit**

```bash
git add app/upload_worker.py tests/test_upload_worker.py
git commit -m "feat: add UploadWorker QThread for standalone YouTube uploads"
```

---

### Task 5: `UploadWindow` 與主視窗入口

**Files:**
- Create: `app/ui/upload_window.py`
- Modify: `app/ui/main_window.py:108-114`（log 區與開始按鈕之間加「單獨上傳影片...」按鈕）

**Interfaces:**
- Consumes: Task 3 的 `upload_mp4_to_youtube.list_video_files` / `SUPPORTED_VIDEO_EXTENSIONS`、Task 4 的 `app.upload_worker.UploadConfig` / `UploadWorker`、既有 `app.ui.auth_dialog.AuthDialog`、`app.settings.AppSettings`
- Produces: `app.ui.upload_window.UploadWindow(QDialog)`（主視窗 import 並 `exec()` 開啟）

- [ ] **Step 1: 新增 `app/ui/upload_window.py`**

```python
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFileDialog, QFormLayout,
    QHBoxLayout, QLineEdit, QListWidget, QMessageBox, QPlainTextEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from app.settings import AppSettings
from app.ui.auth_dialog import AuthDialog
from app.upload_worker import UploadConfig, UploadWorker
from upload_mp4_to_youtube import SUPPORTED_VIDEO_EXTENSIONS, list_video_files


def _file_dialog_filter() -> str:
    exts = " ".join(sorted(SUPPORTED_VIDEO_EXTENSIONS))
    return f"影片 ({exts})"


class UploadWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("上傳到 YouTube")
        self.resize(560, 560)
        self._settings = AppSettings()
        self._worker: UploadWorker | None = None

        layout = QVBoxLayout(self)

        pick_row = QHBoxLayout()
        self.files_btn = QPushButton("選擇檔案...")
        self.files_btn.clicked.connect(self._pick_files)
        self.dir_btn = QPushButton("選擇資料夾...")
        self.dir_btn.clicked.connect(self._pick_dir)
        pick_row.addWidget(self.files_btn)
        pick_row.addWidget(self.dir_btn)
        pick_row.addStretch()
        layout.addLayout(pick_row)

        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        layout.addWidget(self.file_list)

        remove_row = QHBoxLayout()
        self.remove_btn = QPushButton("移除選取")
        self.remove_btn.clicked.connect(self._remove_selected)
        self.clear_btn = QPushButton("清空")
        self.clear_btn.clicked.connect(self.file_list.clear)
        remove_row.addWidget(self.remove_btn)
        remove_row.addWidget(self.clear_btn)
        remove_row.addStretch()
        layout.addLayout(remove_row)

        form = QFormLayout()
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("預設 = 檔名")
        form.addRow("標題:", self.title_edit)
        self.desc_edit = QPlainTextEdit()
        self.desc_edit.setMaximumHeight(70)
        form.addRow("描述:", self.desc_edit)
        self.privacy_combo = QComboBox()
        self.privacy_combo.addItem("私人 (private)", "private")
        self.privacy_combo.addItem("不公開 (unlisted)", "unlisted")
        self.privacy_combo.addItem("公開 (public)", "public")
        form.addRow("隱私:", self.privacy_combo)
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("逗號分隔，例如: dashcam, drive")
        form.addRow("標籤:", self.tags_edit)
        self.playlist_edit = QLineEdit()
        form.addRow("播放清單:", self.playlist_edit)
        self.cs_edit = QLineEdit()
        cs_btn = QPushButton("瀏覽...")
        cs_btn.clicked.connect(self._pick_client_secrets)
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.cs_edit, 1)
        lay.addWidget(cs_btn)
        form.addRow("Client Secrets:", row)
        layout.addLayout(form)

        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        layout.addWidget(self.log_edit, 1)

        self.upload_btn = QPushButton("上傳")
        self.upload_btn.clicked.connect(self._on_upload)
        layout.addWidget(self.upload_btn)

        self._load_settings()

    def _pick_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "選擇影片", "", _file_dialog_filter()
        )
        self._add_paths(paths)

    def _pick_dir(self):
        path = QFileDialog.getExistingDirectory(self, "選擇資料夾")
        if not path:
            return
        self._add_paths([p.as_posix() for p in list_video_files(path)])

    def _add_paths(self, paths):
        existing = set(self._paths())
        for p in paths:
            if p not in existing:
                self.file_list.addItem(p)
                existing.add(p)

    def _paths(self) -> list[str]:
        return [
            self.file_list.item(i).text()
            for i in range(self.file_list.count())
        ]

    def _remove_selected(self):
        for item in self.file_list.selectedItems():
            self.file_list.takeItem(self.file_list.row(item))

    def _pick_client_secrets(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "選擇 Client Secrets", self.cs_edit.text(),
            "Client Secrets JSON (*.json)",
        )
        if path:
            self.cs_edit.setText(path)

    def _load_settings(self):
        s = self._settings
        self.title_edit.setText(s.value("upload_title", ""))
        self.desc_edit.setPlainText(s.value("upload_description", ""))
        idx = self.privacy_combo.findData(s.value("upload_privacy", "private"))
        self.privacy_combo.setCurrentIndex(max(idx, 0))
        self.tags_edit.setText(s.value("upload_tags", ""))
        self.playlist_edit.setText(s.value("upload_playlist", ""))
        self.cs_edit.setText(s.value("client_secrets", ""))

    def _save_settings(self):
        s = self._settings
        s.set_value("upload_title", self.title_edit.text())
        s.set_value("upload_description", self.desc_edit.toPlainText())
        s.set_value("upload_privacy", self.privacy_combo.currentData())
        s.set_value("upload_tags", self.tags_edit.text())
        s.set_value("upload_playlist", self.playlist_edit.text())
        s.set_value("client_secrets", self.cs_edit.text())

    def _on_upload(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self.log_edit.appendPlainText("已送出停止要求...")
            return
        files = self._paths()
        if not files:
            QMessageBox.warning(self, "輸入錯誤", "請先選擇檔案")
            return
        self._save_settings()
        self.log_edit.clear()
        self.log_edit.appendPlainText("開始上傳...")
        cfg = UploadConfig(
            files=files,
            title=self.title_edit.text().strip() or None,
            description=self.desc_edit.toPlainText().strip() or None,
            privacy=self.privacy_combo.currentData(),
            tags=self.tags_edit.text().strip() or None,
            playlist=self.playlist_edit.text().strip() or None,
            client_secrets=self.cs_edit.text().strip() or None,
        )
        self._worker = UploadWorker(cfg, parent=self)
        self._worker.log.connect(self.log_edit.appendPlainText)
        self._worker.finished.connect(self._on_finished)
        self._worker.auth_required.connect(self._on_auth_required)
        self._worker.auth_code_required.connect(self._on_auth_code_required)
        self.upload_btn.setText("停止")
        self._worker.start()

    def _on_auth_required(self, message: str):
        answer = QMessageBox.question(
            self, "YouTube 授權失敗",
            f"無法驗證 YouTube 權限或憑證已過期：\n{message}\n\n要重新授權嗎？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer == QMessageBox.Yes and self._worker is not None:
            self._worker.retry_auth()
        elif self._worker is not None:
            self._worker.cancel()

    def _on_auth_code_required(self, url: str):
        dialog = AuthDialog(url, self)
        if dialog.exec() == AuthDialog.Accepted and self._worker is not None:
            self._worker.submit_auth_code(dialog.code())
        elif self._worker is not None:
            self._worker.cancel()

    def _on_finished(self, result: dict):
        self.upload_btn.setText("上傳")
        status = result.get("status")
        uploaded = result.get("uploaded", [])
        failed = result.get("failed", [])
        if status == "done":
            self.log_edit.appendPlainText("上傳完成")
            for r in uploaded:
                self.log_edit.appendPlainText(
                    f"已上傳: {r.get('file')} -> {r.get('video_id')}"
                )
            for r in failed:
                self.log_edit.appendPlainText(
                    f"上傳失敗: {r.get('file')} ({r.get('error')})"
                )
            if failed:
                QMessageBox.warning(
                    self, "部分失敗",
                    f"成功 {len(uploaded)} 個，失敗 {len(failed)} 個",
                )
            else:
                QMessageBox.information(
                    self, "完成", f"成功上傳 {len(uploaded)} 個影片"
                )
        elif status == "aborted":
            self.log_edit.appendPlainText(f"已中止: {result.get('reason')}")
        else:
            self.log_edit.appendPlainText(f"上傳失敗: {result.get('reason')}")
            QMessageBox.critical(self, "失敗", str(result.get("reason")))

    def closeEvent(self, event):
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(5000)
        super().closeEvent(event)
```

- [ ] **Step 2: 主視窗加入口按鈕**

`app/ui/main_window.py` 在 `self.start_btn`（第 112 行）之前新增：

```python
        self.upload_btn = QPushButton("單獨上傳影片...")
        self.upload_btn.clicked.connect(self._open_upload_window)
        layout.addWidget(self.upload_btn)
```

並在類別結尾（`_on_finished` 之後）新增：

```python
    def _open_upload_window(self):
        from app.ui.upload_window import UploadWindow

        UploadWindow(self).exec()
```

- [ ] **Step 3: 全測試 + smoke 驗證**

Run: `pytest -q`
Expected: 全數 PASS（45+ passed）

Run: `QT_QPA_PLATFORM=offscreen python3 -c "
import sys
sys.path.insert(0, '.')
from PySide6.QtWidgets import QApplication
from app.ui.upload_window import UploadWindow, _file_dialog_filter
app = QApplication([])
w = UploadWindow()
assert '.mp4' in _file_dialog_filter()
assert '.mkv' in _file_dialog_filter()
assert w.windowTitle() == '上傳到 YouTube'
print('UploadWindow OK')
"`

Expected: 輸出 `UploadWindow OK`（offscreen 建立視窗不 crash，驗證 import 與 widget 建置）

- [ ] **Step 4: Commit**

```bash
git add app/ui/upload_window.py app/ui/main_window.py
git commit -m "feat: add standalone upload window to GUI"
```

---

## 驗證總結

完成後執行：

```bash
pytest -q
python3 upload_mp4_to_youtube.py foo.txt   # 期望印出支援格式清單錯誤後 exit
python3 -m py_compile app/upload_worker.py app/ui/upload_window.py app/auth_flow.py
```