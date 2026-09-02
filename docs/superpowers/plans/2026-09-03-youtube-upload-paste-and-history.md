# 貼上檔案路徑 + 上傳紀錄 JSON Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 上傳視窗可貼入多個檔案路徑（換行/逗號/引號），並把每次上傳的成功 mapping（本機路徑 ↔ YouTube URL）與失敗原因寫入 JSON 紀錄檔（GUI 與 CLI 皆然）。

**Architecture:** 共用邏輯放 `upload_mp4_to_youtube.py`（`is_supported_video_file`、`build_history_record`、`append_upload_history`、`UPLOAD_HISTORY_DEFAULT`）；CLI `main()` 加 `--history-file`；`UploadWorker` 每檔完成即寫一筆（`UploadConfig.history_file`，None 不寫）；`UploadWindow` 加貼上區塊與紀錄檔欄位。

**Tech Stack:** Python 3.11、PySide6、pytest、vendored `youtube-upload`（不修改）

## Global Constraints

- 測試環境：pyenv env `e3v`（Python 3.11.1），baseline `pytest -q` = 57 passed
- 檔名 `upload_mp4_to_youtube.py`、`DEFAULT_LOG_FILE` 不變；既有 CLI 參數與 API 相容
- 不修改 vendored `youtube-upload/`；不改 `PipelineConfig` / 合併管線行為
- JSON schema（`ensure_ascii=False, indent=2`）：`{"uploads": [{"file", "status", "video_id", "youtube_url", "timestamp" | "error", "timestamp"}]}`
- `UPLOAD_HISTORY_DEFAULT = Path.home() / "concat-e3v-upload-history.json"`
- `timestamp` = `datetime.now().astimezone().isoformat()`；`youtube_url` = `https://youtu.be/{video_id}`
- 同檔重複上傳 = 每次追加一筆；舊檔損毀/格式不符視為空清單；原子寫回（同目錄 tmp + `os.replace`）
- GUI 文字用中文，與主視窗風格一致；GUI 設定 key：`upload_history_file`
- 測試檔需要 `import os; os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")` 的只有 QThread 測試（`tests/test_upload_worker.py` 已具備）

---

### Task 1: 檔案/紀錄共用函式

**Files:**
- Modify: `upload_mp4_to_youtube.py`
- Test: `tests/test_upload_history.py`（Create）、`tests/test_upload_api.py`（Modify）

**Interfaces:**
- Produces（Task 2/3/4/5 依賴）：
  - `up.is_supported_video_file(path: Path) -> bool`
  - `up.UPLOAD_HISTORY_DEFAULT: Path`
  - `up.build_history_record(result: dict) -> dict`
  - `up.append_upload_history(history_file: str | Path, records: list[dict]) -> None`

- [ ] **Step 1: 新增 import**

`upload_mp4_to_youtube.py` 第 12-16 行的 import 區塊改為：

```python
import argparse
import io
import json
import logging
import os
import sys
from contextlib import redirect_stdout
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path
from typing import Callable
```

- [ ] **Step 2: 寫失敗測試（history）**

新增 `tests/test_upload_history.py`：

```python
import json
import sys

import pytest
import upload_mp4_to_youtube as up


def test_build_history_record_success():
    rec = up.build_history_record(
        {"file": "/tmp/a.mp4", "exit_code": 0, "video_id": "abc123"}
    )
    assert rec["status"] == "success"
    assert rec["youtube_url"] == "https://youtu.be/abc123"
    assert rec["file"] == "/tmp/a.mp4"
    assert rec["timestamp"]


def test_build_history_record_failed_with_error():
    rec = up.build_history_record(
        {"file": "/tmp/a.mp4", "exit_code": 1, "error": "boom"}
    )
    assert rec["status"] == "failed"
    assert rec["error"] == "boom"
    assert "youtube_url" not in rec


def test_build_history_record_failed_fallback_error():
    rec = up.build_history_record({"file": "/tmp/a.mp4", "exit_code": 2})
    assert rec["status"] == "failed"
    assert rec["error"] == "exit code 2"


def test_append_upload_history_creates_file(tmp_path):
    out = tmp_path / "h.json"
    up.append_upload_history(
        out, [{"file": "/a.mp4", "status": "success", "timestamp": "t1"}]
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data == {
        "uploads": [{"file": "/a.mp4", "status": "success", "timestamp": "t1"}]
    }


def test_append_upload_history_appends_and_keeps_old(tmp_path):
    out = tmp_path / "h.json"
    up.append_upload_history(
        out, [{"file": "/a.mp4", "status": "success", "timestamp": "t1"}]
    )
    up.append_upload_history(
        out,
        [{"file": "/b.mp4", "status": "failed", "error": "x", "timestamp": "t2"}],
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    assert [u["file"] for u in data["uploads"]] == ["/a.mp4", "/b.mp4"]


def test_append_upload_history_corrupt_file_treated_as_empty(tmp_path):
    out = tmp_path / "h.json"
    out.write_text("not json", encoding="utf-8")
    up.append_upload_history(
        out, [{"file": "/a.mp4", "status": "success", "timestamp": "t1"}]
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data["uploads"]) == 1


def test_append_upload_history_empty_records_noop(tmp_path):
    out = tmp_path / "h.json"
    up.append_upload_history(out, [])
    assert not out.exists()
```

- [ ] **Step 3: 寫失敗測試（is_supported_video_file）**

`tests/test_upload_api.py` 結尾（`test_list_video_files_recursive` 之後）新增：

```python
def test_is_supported_video_file(tmp_path):
    video = tmp_path / "clip.mov"
    video.write_bytes(b"x")
    assert up.is_supported_video_file(video)
    assert not up.is_supported_video_file(tmp_path / "note.txt")
    assert not up.is_supported_video_file(tmp_path / "missing.mp4")
    assert not up.is_supported_video_file(tmp_path)
```

- [ ] **Step 4: 執行確認失敗**

Run: `pytest tests/test_upload_history.py tests/test_upload_api.py::test_is_supported_video_file -q`
Expected: FAIL（AttributeError: module ... has no attribute 'is_supported_video_file' / 'build_history_record'）

- [ ] **Step 5: 實作**

5a. `list_video_files` 之前新增（`upload_mp4_to_youtube.py`，放在第 121 行 `def list_video_files` 前面）：

```python
def is_supported_video_file(path: Path) -> bool:
    return (
        path.is_file()
        and path.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS
    )


UPLOAD_HISTORY_DEFAULT = Path.home() / "concat-e3v-upload-history.json"


def build_history_record(result: dict) -> dict:
    timestamp = datetime.now().astimezone().isoformat()
    if result.get("exit_code") == 0:
        video_id = result.get("video_id")
        return {
            "file": result["file"],
            "status": "success",
            "video_id": video_id,
            "youtube_url": f"https://youtu.be/{video_id}",
            "timestamp": timestamp,
        }
    error = result.get("error") or f"exit code {result.get('exit_code')}"
    return {
        "file": result["file"],
        "status": "failed",
        "error": error,
        "timestamp": timestamp,
    }


def append_upload_history(
    history_file: str | Path,
    records: list[dict],
) -> None:
    if not records:
        return
    path = Path(history_file).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    uploads: list[dict] = []
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(
                data.get("uploads"), list
            ):
                uploads = data["uploads"]
        except (OSError, ValueError):
            uploads = []
    uploads.extend(records)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(
        json.dumps(
            {"uploads": uploads}, ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )
    os.replace(tmp_path, path)
```

5b. `list_video_files` 的回傳 filter 改用 helper（第 131-136 行）：

```python
    return sorted(
        path
        for path in paths
        if is_supported_video_file(path)
    )
```

- [ ] **Step 6: 執行確認通過**

Run: `pytest tests/test_upload_history.py tests/test_upload_api.py -q`
Expected: 全數 PASS（57 + 7 + 1 = 65）

- [ ] **Step 7: Commit**

```bash
git add upload_mp4_to_youtube.py tests/test_upload_history.py tests/test_upload_api.py
git commit -m "feat: add upload history record functions and video file helper"
```

---

### Task 2: CLI `--history-file` 接線

**Files:**
- Modify: `upload_mp4_to_youtube.py`
- Test: `tests/test_upload_history.py`

**Interfaces:**
- Consumes: Task 1 的 `build_history_record` / `append_upload_history` / `UPLOAD_HISTORY_DEFAULT`
- Produces: CLI 參數 `--history-file`（預設 `UPLOAD_HISTORY_DEFAULT`，字串化）

- [ ] **Step 1: 寫失敗測試**

`tests/test_upload_history.py` 結尾新增：

```python
def test_cli_main_writes_history(monkeypatch, tmp_path):
    cs = tmp_path / "cs.json"
    cs.write_text("{}", encoding="utf-8")
    video = tmp_path / "a.mp4"
    video.write_bytes(b"x")
    history = tmp_path / "h.json"
    log_file = tmp_path / "up.log"

    def fake_check(*a, **kw):
        return None

    def fake_upload_one(ns, video_path, youtube_upload_main):
        return {
            "file": video_path.as_posix(),
            "name": video_path.name,
            "exit_code": 0,
            "video_id": "v1",
        }

    monkeypatch.setattr(up, "check_youtube_upload_available", fake_check)
    monkeypatch.setattr(up, "_upload_one_video", fake_upload_one)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "upload_mp4_to_youtube.py",
            str(video),
            "--client-secrets",
            str(cs),
            "--history-file",
            str(history),
            "--log-file",
            str(log_file),
        ],
    )

    rc = up.main()
    assert rc == 0
    data = json.loads(history.read_text(encoding="utf-8"))
    assert len(data["uploads"]) == 1
    assert data["uploads"][0]["status"] == "success"
    assert data["uploads"][0]["youtube_url"] == "https://youtu.be/v1"
```

- [ ] **Step 2: 執行確認失敗**

Run: `pytest tests/test_upload_history.py::test_cli_main_writes_history -q`
Expected: FAIL（`_build_parser` 之後的 `main()` 沒有 `--history-file` → SystemExit 2 / "unrecognized arguments"）

- [ ] **Step 3: 實作**

3a. `main()` 的 argparse 區塊（`--open-link` 之後，第 562 行附近）新增：

```python
    parser.add_argument(
        "--history-file",
        default=UPLOAD_HISTORY_DEFAULT.as_posix(),
        help="Upload history JSON file (default: ~/concat-e3v-upload-history.json)",
    )
```

3b. 上傳迴圈結束後、`_print_result_summary(result)` 之前（第 637 行附近）新增：

```python
    records = [
        build_history_record(r)
        for r in result["uploaded"] + result["failed"]
    ]
    append_upload_history(ns.history_file, records)
```

- [ ] **Step 4: 執行確認通過**

Run: `pytest tests/test_upload_history.py -q && pytest -q`
Expected: 全數 PASS（66）

- [ ] **Step 5: Commit**

```bash
git add upload_mp4_to_youtube.py tests/test_upload_history.py
git commit -m "feat: write upload history JSON from CLI"
```

---

### Task 3: UploadWorker 每檔寫紀錄

**Files:**
- Modify: `app/upload_worker.py`
- Test: `tests/test_upload_worker.py`

**Interfaces:**
- Consumes: Task 1 的 `build_history_record` / `append_upload_history`
- Produces: `UploadConfig.history_file: str | None = None`（Task 5 使用）；`UploadWorker.run()` 每檔完成後寫一筆

- [ ] **Step 1: 寫失敗測試**

`tests/test_upload_worker.py` 結尾新增：

```python
def test_upload_worker_writes_history(qapp, monkeypatch, tmp_path):
    import json

    def fake_upload_video(path, **kw):
        if path.endswith("bad.mp4"):
            return {"file": path, "name": path, "exit_code": 1, "error": "boom"}
        return {"file": path, "name": path, "exit_code": 0, "video_id": "ok1"}

    monkeypatch.setattr("app.upload_worker.upload_video", fake_upload_video)
    monkeypatch.setattr(
        "app.auth_flow.check_youtube_upload_available", lambda **kw: None
    )
    history = tmp_path / "h.json"
    worker = UploadWorker(
        UploadConfig(
            files=[str(tmp_path / "ok.mp4"), str(tmp_path / "bad.mp4")],
            history_file=str(history),
        )
    )
    results = {}
    worker.finished.connect(lambda r: results.update(r))
    assert _run_and_pump(qapp, worker)
    assert results["status"] == "done"
    data = json.loads(history.read_text(encoding="utf-8"))
    assert len(data["uploads"]) == 2
    by_status = {u["status"]: u for u in data["uploads"]}
    assert by_status["success"]["youtube_url"] == "https://youtu.be/ok1"
    assert by_status["failed"]["error"] == "boom"


def test_upload_worker_skips_history_when_unset(qapp, monkeypatch, tmp_path):
    calls = []

    def fake_upload_video(path, **kw):
        return {"file": path, "name": path, "exit_code": 0, "video_id": "x"}

    monkeypatch.setattr("app.upload_worker.upload_video", fake_upload_video)
    monkeypatch.setattr(
        "app.auth_flow.check_youtube_upload_available", lambda **kw: None
    )
    monkeypatch.setattr(
        "app.upload_worker.append_upload_history",
        lambda *a, **kw: calls.append((a, kw)),
    )
    worker = UploadWorker(UploadConfig(files=[str(tmp_path / "a.mp4")]))
    results = {}
    worker.finished.connect(lambda r: results.update(r))
    assert _run_and_pump(qapp, worker)
    assert calls == []
```

- [ ] **Step 2: 執行確認失敗**

Run: `pytest tests/test_upload_worker.py -q`
Expected: `test_upload_worker_writes_history` FAIL（TypeError: UploadConfig.__init__() got an unexpected keyword argument 'history_file'）；`test_upload_worker_skips_history_when_unset` FAIL（`append_upload_history` 被呼叫）

- [ ] **Step 3: 實作**

3a. import 改為：

```python
from upload_mp4_to_youtube import (
    append_upload_history,
    build_history_record,
    upload_video,
)
```

3b. `UploadConfig` 新增欄位：

```python
    credentials_file: str | None = None
    history_file: str | None = None
```

3c. `run()` 中收集結果之後（第 90-95 行的 if/else 之後）新增：

```python
                if cfg.history_file is not None:
                    append_upload_history(
                        cfg.history_file,
                        [build_history_record(result)],
                    )
```

- [ ] **Step 4: 執行確認通過**

Run: `pytest tests/test_upload_worker.py -q && pytest -q`
Expected: 全數 PASS（68）

- [ ] **Step 5: Commit**

```bash
git add app/upload_worker.py tests/test_upload_worker.py
git commit -m "feat: write per-file upload history from UploadWorker"
```

---

### Task 4: 貼上檔案路徑

**Files:**
- Modify: `app/ui/upload_window.py`
- Test: `tests/test_upload_window.py`（Create）

**Interfaces:**
- Consumes: Task 1 的 `is_supported_video_file`
- Produces（模組層級純函式，測試直接使用）：
  - `parse_pasted_paths(text: str) -> list[str]`
  - `resolve_pasted_paths(text: str) -> tuple[list[Path], list[tuple[str, str]]]`
  - `UploadWindow._add_pasted_paths()`（按鈕處理：有效進清單、無效 QMessageBox.warning）

- [ ] **Step 1: 寫失敗測試**

新增 `tests/test_upload_window.py`：

```python
from pathlib import Path

from app.ui.upload_window import parse_pasted_paths, resolve_pasted_paths


def test_parse_pasted_paths_newline(tmp_path):
    a, b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    assert parse_pasted_paths(f"{a}\n{b}") == [str(a), str(b)]


def test_parse_pasted_paths_comma_and_quotes(tmp_path):
    a, b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    raw = f'"{a}", \'{b}\''
    assert parse_pasted_paths(raw) == [str(a), str(b)]


def test_parse_pasted_paths_expanduser_and_blanks():
    assert parse_pasted_paths("  \n ~ \n\n /tmp/x.mp4 ") == [
        str(Path.home()),
        "/tmp/x.mp4",
    ]


def test_resolve_pasted_paths(tmp_path):
    ok = tmp_path / "a.mp4"
    ok.write_bytes(b"x")
    txt = tmp_path / "b.txt"
    txt.write_bytes(b"x")
    missing = tmp_path / "nope.mp4"
    valid, invalid = resolve_pasted_paths(f"{ok}\n{txt}\n{missing}")
    assert valid == [ok]
    reasons = {p: r for p, r in invalid}
    assert reasons[str(txt)] == "不支援的格式"
    assert reasons[str(missing)] == "檔案不存在"
```

- [ ] **Step 2: 執行確認失敗**

Run: `pytest tests/test_upload_window.py -q`
Expected: FAIL（ImportError: cannot import name 'parse_pasted_paths'）

- [ ] **Step 3: 實作純函式**

3a. `app/ui/upload_window.py` 頂部 import 改為：

```python
import re
from pathlib import Path

from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from app.settings import AppSettings
from app.ui.auth_dialog import AuthDialog
from app.upload_worker import UploadConfig, UploadWorker
from upload_mp4_to_youtube import (
    SUPPORTED_VIDEO_EXTENSIONS,
    is_supported_video_file,
    list_video_files,
)
```

3b. `_file_dialog_filter` 之後新增：

```python
def _strip_quotes(text: str) -> str:
    text = text.strip()
    if (
        len(text) >= 2
        and text[0] == text[-1]
        and text[0] in ("'", '"')
    ):
        return text[1:-1]
    return text


def parse_pasted_paths(text: str) -> list[str]:
    parts = re.split(r"[\n,]+", text)
    paths: list[str] = []
    for part in parts:
        cleaned = _strip_quotes(part).strip()
        if not cleaned:
            continue
        paths.append(str(Path(cleaned).expanduser()))
    return paths


def resolve_pasted_paths(
    text: str,
) -> tuple[list[Path], list[tuple[str, str]]]:
    valid: list[Path] = []
    invalid: list[tuple[str, str]] = []
    for raw in parse_pasted_paths(text):
        path = Path(raw)
        if not path.is_file():
            invalid.append((raw, "檔案不存在"))
        elif not is_supported_video_file(path):
            invalid.append((raw, "不支援的格式"))
        else:
            valid.append(path)
    return valid, invalid
```

- [ ] **Step 4: 實作 UI 區塊**

4a. `__init__` 中「移除選取/清空」列（`remove_row`）之後新增：

```python
        paste_label = QLabel("貼上檔案路徑（一行一個，支援逗號分隔與引號）：")
        layout.addWidget(paste_label)
        paste_row = QHBoxLayout()
        self.paste_edit = QPlainTextEdit()
        self.paste_edit.setMaximumHeight(70)
        self.paste_btn = QPushButton("加入清單")
        self.paste_btn.clicked.connect(self._add_pasted_paths)
        paste_row.addWidget(self.paste_edit, 1)
        paste_row.addWidget(self.paste_btn)
        layout.addLayout(paste_row)
```

4b. 類別內（`_pick_client_secrets` 之後）新增：

```python
    def _add_pasted_paths(self):
        text = self.paste_edit.toPlainText()
        if not text.strip():
            return
        valid, invalid = resolve_pasted_paths(text)
        self._add_paths([p.as_posix() for p in valid])
        if invalid:
            lines = "\n".join(
                f"{path}（{reason}）" for path, reason in invalid
            )
            QMessageBox.warning(
                self, "部分路徑無法加入", f"以下路徑無法加入：\n\n{lines}"
            )
```

- [ ] **Step 5: 執行確認通過**

Run: `pytest tests/test_upload_window.py -q && pytest -q`
Expected: 全數 PASS（72）

Run: offscreen smoke：

```bash
QT_QPA_PLATFORM=offscreen python3 -c "
import sys, tempfile, pathlib
sys.path.insert(0, '.')
from PySide6.QtWidgets import QApplication
from app.ui.upload_window import UploadWindow, parse_pasted_paths
app = QApplication([])
w = UploadWindow()
d = pathlib.Path(tempfile.mkdtemp())
a = d / 'a.mp4'; a.write_bytes(b'x')
b = d / 'b.txt'; b.write_bytes(b'x')
c = d / 'nope.mp4'
w.paste_edit.setPlainText(f'{a}\n{b}\n{c}')
w._add_pasted_paths()
assert w._paths() == [str(a)], w._paths()
print('paste OK')
"
```

Expected: 輸出 `paste OK`

- [ ] **Step 6: Commit**

```bash
git add app/ui/upload_window.py tests/test_upload_window.py
git commit -m "feat: paste multiple file paths into upload window"
```

---

### Task 5: 紀錄檔欄位 + 最終驗證

**Files:**
- Modify: `app/ui/upload_window.py`

**Interfaces:**
- Consumes: Task 1 的 `UPLOAD_HISTORY_DEFAULT`、Task 3 的 `UploadConfig.history_file`
- Produces: 上傳視窗「紀錄檔」欄位（QLineEdit + 瀏覽），空值時以 `UPLOAD_HISTORY_DEFAULT` 傳給 worker

- [ ] **Step 1: 實作欄位**

1a. import 加 `UPLOAD_HISTORY_DEFAULT`：

```python
from upload_mp4_to_youtube import (
    SUPPORTED_VIDEO_EXTENSIONS,
    UPLOAD_HISTORY_DEFAULT,
    is_supported_video_file,
    list_video_files,
)
```

1b. `__init__` 中「Client Secrets」row（第 78 行附近）之後新增：

```python
        self.history_edit = QLineEdit()
        self.history_edit.setPlaceholderText(
            f"預設: {UPLOAD_HISTORY_DEFAULT}"
        )
        history_btn = QPushButton("瀏覽...")
        history_btn.clicked.connect(self._pick_history_file)
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.history_edit, 1)
        lay.addWidget(history_btn)
        form.addRow("紀錄檔:", row)
```

1c. `_pick_client_secrets` 之後新增：

```python
    def _pick_history_file(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "選擇上傳紀錄檔",
            self.history_edit.text() or str(Path.home()),
            "JSON (*.json)",
        )
        if path:
            self.history_edit.setText(path)
```

1d. `_load_settings` 加（`client_secrets` 之後）：

```python
        self.history_edit.setText(s.value("upload_history_file", ""))
```

1e. `_save_settings` 加（`client_secrets` 之後）：

```python
        s.set_value("upload_history_file", self.history_edit.text())
```

1f. `_on_upload` 的 `UploadConfig(...)` 加參數：

```python
            history_file=(
                self.history_edit.text().strip()
                or UPLOAD_HISTORY_DEFAULT.as_posix()
            ),
```

- [ ] **Step 2: 驗證**

Run: `pytest -q`
Expected: 全數 PASS（72）

Run: offscreen smoke：

```bash
QT_QPA_PLATFORM=offscreen python3 -c "
import sys
sys.path.insert(0, '.')
from PySide6.QtWidgets import QApplication
from app.ui.upload_window import UploadWindow
app = QApplication([])
w = UploadWindow()
assert w.history_edit.placeholderText().startswith('預設: '), w.history_edit.placeholderText()
w.history_edit.setText('/tmp/my-history.json')
w._save_settings()
w2 = UploadWindow()
assert w2.history_edit.text() == '/tmp/my-history.json', w2.history_edit.text()
print('history field OK')
"
```

Expected: 輸出 `history field OK`

Run: CLI 手動驗證（使用 Task 2 的測試已涵蓋；此處確認 help）：

```bash
python3 upload_mp4_to_youtube.py --help | grep history-file
```

Expected: 印出 `--history-file` 說明行

- [ ] **Step 3: Commit**

```bash
git add app/ui/upload_window.py
git commit -m "feat: configurable upload history file path in upload window"
```

- [ ] **Step 4: 重建 app 供使用者測試**

```bash
PYTHON="$(pwd)/.venv-build/bin/python" ./build/build_mac.sh
```

Expected: Build complete，`dist/concat-e3v.app` 更新

---

## 驗證總結

完成後執行：

```bash
pytest -q   # 72 passed
git log --oneline -5
```