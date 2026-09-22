# 首頁模式選擇 + 共用紀錄檔設定 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 程式入口改為首頁（兩顆按鈕選模式、閒置可回首頁），紀錄檔設定欄位移到首頁且兩模式共用，E3V 模式上傳時也開始寫上傳紀錄。

**Architecture:** 新增 `HomeWindow` 作為入口；`app/main.py` 改為控制器（hide/show 切換 HomeWindow 與 MainWindow，單獨上傳維持 `UploadWindow(home).exec()` modal）。紀錄檔設定只存在首頁（QSettings key `upload_history_file`），兩模式開始時經 `app/settings.get_upload_history_file` 即時讀取；`run_pipeline` 每檔上傳後以既有 `build_history_record`/`append_upload_history` 寫入（OSError 容錯，與 UploadWorker 相同模式）。

**Tech Stack:** Python 3.11、PySide6、QSettings、QThread worker、PyInstaller。

## Global Constraints

- 工作目錄：`/Users/double/Code/concat-e3v-video`（branch `main`）；pyenv env `e3v`（Python 3.11.1）；plain `pytest`；基準 **75 passed**；測試用 `QT_QPA_PLATFORM=offscreen`
- **不得修改**：`upload_mp4_to_youtube.py`（共用函式）、`app/upload_worker.py`、上傳紀錄 JSON schema（`build_history_record`/`append_upload_history`/`UPLOAD_HISTORY_DEFAULT` 原樣重用）、`app/ui/auth_dialog.py`、`app/worker.py`
- 紀錄檔設定欄位**只放首頁**；兩模式於開始時即時讀設定（不需重啟）
- 單獨上傳模式維持現狀（關閉視窗即回首頁）；E3V 模式：回首頁按鈕 + 關閉視窗都回首頁（閒置時）；處理中回首頁按鈕 disabled、關閉被阻止
- 程式只在首頁關閉時退出（`setQuitOnLastWindowClosed(False)` + `HomeWindow.closeEvent → QApplication.instance().quit()`）
- E3V 模式歷史寫入時機：每檔上傳後、cancel 檢查**之前**（取消也保留已完成紀錄，與 UploadWorker 行為一致）；寫入失敗 `try/except OSError` → `cfg.log`，不中斷批次
- commit 訊息格式：`feat: ...` / `test: ...`；每 task 結束 `pytest -q` 全綠才 commit

---

### Task 1: 設定 helper + HomeWindow

**Files:**
- Modify: `app/settings.py`（加 helper）
- Create: `app/ui/home_window.py`
- Test: `tests/test_home_window.py`

**Interfaces:**
- Consumes: `upload_mp4_to_youtube.UPLOAD_HISTORY_DEFAULT`、`app.settings.AppSettings`
- Produces:
  - `app.settings.get_upload_history_file(s: AppSettings) -> str`（讀 `upload_history_file`，空值回 `UPLOAD_HISTORY_DEFAULT.as_posix()`）
  - `app.ui.home_window.HomeWindow(QWidget)`：`e3v_requested`/`upload_requested` 兩個 `Signal()`；屬性 `e3v_btn`、`upload_btn`、`history_edit`；變更 `history_edit` 即存 `upload_history_file`；`closeEvent → QApplication.instance().quit()`

- [ ] **Step 1: 在 `app/settings.py` 加 helper**

```python
def get_upload_history_file(s: AppSettings) -> str:
    from upload_mp4_to_youtube import UPLOAD_HISTORY_DEFAULT

    return str(s.value("upload_history_file", "") or UPLOAD_HISTORY_DEFAULT.as_posix())
```

（lazy import 避免 settings 模組牽動 google 套件堆疊。）

- [ ] **Step 2: 寫失敗測試** `tests/test_home_window.py`

```python
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from app.settings import AppSettings
from app.ui.home_window import HomeWindow


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


def _make_home(tmp_path, monkeypatch) -> HomeWindow:
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    monkeypatch.setattr(
        "app.ui.home_window.AppSettings",
        lambda: AppSettings(QSettings.IniFormat),
    )
    return HomeWindow()


def test_home_window_constructs(qapp, monkeypatch, tmp_path):
    home = _make_home(tmp_path, monkeypatch)
    assert home.windowTitle() == "concat-e3v"
    assert home.e3v_btn.text() == "處理E3V影片"
    assert home.upload_btn.text() == "單獨上傳影片"
    assert home.history_edit is not None


def test_e3v_button_emits_signal(qapp, monkeypatch, tmp_path):
    home = _make_home(tmp_path, monkeypatch)
    seen = []
    home.e3v_requested.connect(lambda: seen.append(1))
    home.e3v_btn.click()
    assert seen == [1]


def test_upload_button_emits_signal(qapp, monkeypatch, tmp_path):
    home = _make_home(tmp_path, monkeypatch)
    seen = []
    home.upload_requested.connect(lambda: seen.append(1))
    home.upload_btn.click()
    assert seen == [1]


def test_history_field_roundtrip(qapp, monkeypatch, tmp_path):
    home = _make_home(tmp_path, monkeypatch)
    home.history_edit.setText(str(tmp_path / "h.json"))
    s = AppSettings(QSettings.IniFormat)
    assert s.value("upload_history_file") == str(tmp_path / "h.json")
    home2 = _make_home(tmp_path, monkeypatch)
    assert home2.history_edit.text() == str(tmp_path / "h.json")


def test_close_quits_app(qapp, monkeypatch, tmp_path):
    home = _make_home(tmp_path, monkeypatch)
    quit_called = []
    monkeypatch.setattr(qapp, "quit", lambda: quit_called.append(1))
    home.close()
    assert quit_called == [1]
```

- [ ] **Step 3: 跑測試確認失敗**

Run: `pytest tests/test_home_window.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ui.home_window'`

- [ ] **Step 4: 實作 `app/ui/home_window.py`**

```python
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from app.settings import AppSettings
from upload_mp4_to_youtube import UPLOAD_HISTORY_DEFAULT


class HomeWindow(QWidget):
    e3v_requested = Signal()
    upload_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("concat-e3v")
        self.resize(480, 320)
        self._settings = AppSettings()

        layout = QVBoxLayout(self)

        title = QLabel("concat-e3v")
        title.setAlignment(Qt.AlignCenter)
        font = title.font()
        font.setPointSize(24)
        title.setFont(font)
        layout.addWidget(title)

        self.e3v_btn = QPushButton("處理E3V影片")
        self.e3v_btn.setMinimumHeight(56)
        self.e3v_btn.clicked.connect(lambda: self.e3v_requested.emit())
        layout.addWidget(self.e3v_btn)

        self.upload_btn = QPushButton("單獨上傳影片")
        self.upload_btn.setMinimumHeight(56)
        self.upload_btn.clicked.connect(lambda: self.upload_requested.emit())
        layout.addWidget(self.upload_btn)

        form = QFormLayout()
        self.history_edit = QLineEdit()
        self.history_edit.setPlaceholderText(f"預設: {UPLOAD_HISTORY_DEFAULT}")
        self.history_edit.textChanged.connect(self._save_history_file)
        history_btn = QPushButton("瀏覽...")
        history_btn.clicked.connect(self._pick_history_file)
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.history_edit, 1)
        lay.addWidget(history_btn)
        form.addRow("紀錄檔:", row)
        layout.addLayout(form)

        layout.addStretch()

        self._load_settings()

    def _pick_history_file(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "選擇上傳紀錄檔",
            self.history_edit.text() or str(Path.home()),
            "JSON (*.json)",
        )
        if path:
            self.history_edit.setText(path)

    def _save_history_file(self, _text):
        self._settings.set_value(
            "upload_history_file", self.history_edit.text()
        )

    def _load_settings(self):
        self.history_edit.setText(
            self._settings.value("upload_history_file", "")
        )

    def closeEvent(self, event):
        QApplication.instance().quit()
        super().closeEvent(event)
```

- [ ] **Step 5: 跑測試確認通過**

Run: `pytest tests/test_home_window.py -v`
Expected: 5 passed

- [ ] **Step 6: 全量測試 + commit**

Run: `pytest -q`（75 + 5 = 80 passed）

```bash
git add app/settings.py app/ui/home_window.py tests/test_home_window.py
git commit -m "feat: add home window with mode selection and shared history setting"
```

---

### Task 2: MainWindow 改造（回首頁 + 關閉保護 + history_file）

**Files:**
- Modify: `app/ui/main_window.py`
- Test: `tests/test_gui_smoke.py`

**Interfaces:**
- Consumes: `app.settings.get_upload_history_file`（Task 1）、`app.pipeline.PipelineConfig`（Task 4 會加 `history_file` 欄位——本 task 先傳，Task 4 才被使用，dataclass 多餘 kwarg 目前會 TypeError；因此 Task 4 必須先於本 task 的 `_build_cfg` 生效前合入。**執行順序：Task 4 先於 Task 2。**）
- Produces: `MainWindow.back_requested`（`Signal()`）；`MainWindow._busy() -> bool`；`MainWindow.closeEvent` 行為

- [ ] **Step 1: 寫失敗測試**（追加到 `tests/test_gui_smoke.py`，保留既有 4 個測試）

```python
from PySide6.QtGui import QCloseEvent
from upload_mp4_to_youtube import UPLOAD_HISTORY_DEFAULT


class _Signal:
    def connect(self, *a, **kw):
        pass


class FakeBusyWorker:
    def __init__(self, cfg, parent=None):
        self.log = _Signal()
        self.finished = _Signal()
        self.auth_required = _Signal()
        self.auth_code_required = _Signal()

    def start(self):
        pass

    def isRunning(self):
        return True


def test_back_button_disabled_while_busy(qapp, monkeypatch, tmp_path):
    window = _make_window(tmp_path, monkeypatch)
    window.src_edit.setText(str(tmp_path))
    window.dst_edit.setText(str(tmp_path / "out"))
    monkeypatch.setattr(
        "app.ui.main_window.PipelineWorker", FakeBusyWorker
    )
    monkeypatch.setattr(
        "app.ui.main_window.QMessageBox.information", lambda *a, **kw: None
    )
    window._on_start()
    assert not window.back_btn.isEnabled()
    window._on_finished({"status": "done", "upload_results": []})
    assert window.back_btn.isEnabled()


def test_close_blocked_while_busy(qapp, monkeypatch, tmp_path):
    window = _make_window(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "app.ui.main_window.QMessageBox.warning", lambda *a, **kw: None
    )
    window._worker = FakeBusyWorker(None)
    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted()


def test_close_idle_returns_home(qapp, monkeypatch, tmp_path):
    QApplication.setQuitOnLastWindowClosed(False)
    window = _make_window(tmp_path, monkeypatch)
    backs = []
    window.back_requested.connect(lambda: backs.append(1))
    window.close()
    assert backs == [1]


def test_build_cfg_history_file_from_settings(qapp, monkeypatch, tmp_path):
    window = _make_window(tmp_path, monkeypatch)
    window._settings.set_value("upload_history_file", str(tmp_path / "h.json"))
    cfg = window._build_cfg()
    assert cfg.history_file == str(tmp_path / "h.json")


def test_build_cfg_history_file_default(qapp, monkeypatch, tmp_path):
    window = _make_window(tmp_path, monkeypatch)
    cfg = window._build_cfg()
    assert cfg.history_file == UPLOAD_HISTORY_DEFAULT.as_posix()
```

（`test_close_blocked_while_busy`／`test_back_button_disabled_while_busy` 需 `QMessageBox` monkeypatch，否則 offscreen 下阻塞；`test_back_button_disabled_while_busy` 走真實 `_on_start`/`_on_finished` 流程驗證按鈕狀態轉換。）

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_gui_smoke.py -v`
Expected: 新 5 個測試 FAIL（`AttributeError: 'MainWindow' object has no attribute 'back_btn'`；`_build_cfg` 因 Task 4 尚未加 `history_file` 而 TypeError——**若 Task 4 已先合入則為 cfg 沒有 history_file 屬性的斷言失敗**）

- [ ] **Step 3: 實作 `app/ui/main_window.py` 修改**

3a. import 修改（第 4 行與第 14 行）：

```python
from PySide6.QtCore import Qt, QDateTime, QTimeZone, Signal
```

```python
from app.settings import AppSettings, get_upload_history_file
```

3b. 類別屬性（class 定義第一行，`__init__` 前）：

```python
    back_requested = Signal()
```

3c. 刪除「單獨上傳影片」按鈕（目前第 112-114 行）：

```python
        self.upload_btn = QPushButton("單獨上傳影片...")
        self.upload_btn.clicked.connect(self._open_upload_window)
        layout.addWidget(self.upload_btn)
```

3d. 在「開始處理」按鈕（`self.start_btn` 建立處）之前加：

```python
        self.back_btn = QPushButton("回首頁")
        self.back_btn.clicked.connect(lambda: self.back_requested.emit())
        layout.addWidget(self.back_btn)
```

3e. `_build_cfg` 的 `PipelineConfig(...)` 加一列（在 `client_secrets=` 之後）：

```python
            history_file=get_upload_history_file(self._settings),
```

3f. `_on_start`：`self._worker.start()` 之前加 `self.back_btn.setEnabled(False)`；`_on_finished`：`self.start_btn.setText("開始處理")` 之後加 `self.back_btn.setEnabled(True)`。

3g. 新增 `_busy` 與 `closeEvent`（放在 `_on_finished` 之後）：

```python
    def _busy(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def closeEvent(self, event):
        if self._busy():
            QMessageBox.warning(self, "處理中", "請先取消或等待處理完成")
            event.ignore()
            return
        self.back_requested.emit()
        super().closeEvent(event)
```

3h. 刪除 `_open_upload_window`（檔案最後一個 method，目前第 278-281 行）。

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/test_gui_smoke.py -v`
Expected: 9 passed（4 舊 + 5 新）

- [ ] **Step 5: 全量測試 + commit**

Run: `pytest -q`（80 + 5 = 85 passed）

```bash
git add app/ui/main_window.py tests/test_gui_smoke.py
git commit -m "feat: return-to-home from E3V window with busy close guard and shared history setting"
```

---

### Task 3: UploadWindow 移除紀錄檔欄位

**Files:**
- Modify: `app/ui/upload_window.py`

**Interfaces:**
- Consumes: `app.settings.get_upload_history_file`（Task 1）、`app.upload_worker.UploadConfig`（不變）
- Produces: `UploadWindow` 不再有 `history_edit`；`_on_upload` 以 helper 即時讀設定

- [ ] **Step 1: 寫失敗測試**（新檔 `tests/test_upload_window_settings.py`，與既有純函式測試分開）

```python
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from app.settings import AppSettings
from upload_mp4_to_youtube import UPLOAD_HISTORY_DEFAULT


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


class _Signal:
    def connect(self, *a, **kw):
        pass


def _make_window(tmp_path, monkeypatch):
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    monkeypatch.setattr(
        "app.ui.upload_window.AppSettings",
        lambda: AppSettings(QSettings.IniFormat),
    )
    from app.ui.upload_window import UploadWindow

    return UploadWindow()


def _fake_worker(monkeypatch, captured):
    class FakeWorker:
        def __init__(self, cfg, parent=None):
            captured["cfg"] = cfg
            self.log = _Signal()
            self.finished = _Signal()
            self.auth_required = _Signal()
            self.auth_code_required = _Signal()

        def start(self):
            pass

    monkeypatch.setattr("app.ui.upload_window.UploadWorker", FakeWorker)


def test_on_upload_history_from_settings(qapp, monkeypatch, tmp_path):
    captured = {}
    _fake_worker(monkeypatch, captured)
    window = _make_window(tmp_path, monkeypatch)
    window._settings.set_value("upload_history_file", str(tmp_path / "h.json"))
    window.file_list.addItem("/tmp/a.mp4")
    window._on_upload()
    assert captured["cfg"].history_file == str(tmp_path / "h.json")


def test_on_upload_history_default_when_unset(qapp, monkeypatch, tmp_path):
    captured = {}
    _fake_worker(monkeypatch, captured)
    window = _make_window(tmp_path, monkeypatch)
    window.file_list.addItem("/tmp/a.mp4")
    window._on_upload()
    assert captured["cfg"].history_file == UPLOAD_HISTORY_DEFAULT.as_posix()
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_upload_window_settings.py -v`
Expected: FAIL — `AttributeError: 'UploadWindow' object has no attribute 'file_list'` 或 history 欄位仍在時斷言不符

- [ ] **Step 3: 實作 `app/ui/upload_window.py` 修改**

3a. import 修改（第 10、13-18 行）：

```python
from app.settings import AppSettings, get_upload_history_file
```

```python
from upload_mp4_to_youtube import (
    SUPPORTED_VIDEO_EXTENSIONS,
    is_supported_video_file,
    list_video_files,
)
```

（移除 `UPLOAD_HISTORY_DEFAULT`。）

3b. 刪除「紀錄檔」欄位區塊（目前第 138-149 行，`self.history_edit = QLineEdit()` 到 `form.addRow("紀錄檔:", row)` 含 `_pick_history_file` 用的 `history_btn`）。

3c. 刪除 `_pick_history_file` method（目前第 207-214 行）。

3d. `_load_settings` 刪除 `self.history_edit.setText(s.value("upload_history_file", ""))`（目前第 239 行）。

3e. `_save_settings` 刪除 `s.set_value("upload_history_file", self.history_edit.text())`（目前第 250 行）。

3f. `_on_upload` 的 `history_file=` 改為：

```python
            history_file=get_upload_history_file(self._settings),
```

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/test_upload_window_settings.py tests/test_upload_window.py -v`
Expected: 2 + 4 = 6 passed

- [ ] **Step 5: 全量測試 + commit**

Run: `pytest -q`（85 + 2 = 87 passed）

```bash
git add app/ui/upload_window.py tests/test_upload_window_settings.py
git commit -m "feat: read shared upload history setting from home window"
```

---

### Task 4: pipeline 寫上傳紀錄

**Files:**
- Modify: `app/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `upload_mp4_to_youtube.append_upload_history`、`upload_mp4_to_youtube.build_history_record`（原樣，不修改）
- Produces: `PipelineConfig.history_file: str | None = None`；`run_pipeline` 每檔上傳後（cancel 檢查前）寫入一筆，`OSError` 容錯 → `cfg.log`
- **注意：本 task 的 `history_file` 欄位是 Task 2 的 `_build_cfg` 傳參的前提，執行順序必須在 Task 2 之前。**

- [ ] **Step 1: 寫失敗測試**（追加到 `tests/test_pipeline.py`，需加 `import json`）

```python
def test_pipeline_writes_history_records(monkeypatch, tmp_path):
    class FakeProcessor:
        def __init__(self, *a, **kw):
            pass

        def concat(self, cancel_event=None):
            return ["out.mp4", "out2.mp4"]

    monkeypatch.setattr("app.pipeline.VideoProcessor", FakeProcessor)
    results = iter(
        [
            {"file": "/tmp/out.mp4", "exit_code": 0, "video_id": "v1"},
            {"file": "/tmp/out2.mp4", "exit_code": 1, "error": "boom"},
        ]
    )
    monkeypatch.setattr(
        "app.pipeline.upload_video", lambda *a, **kw: next(results)
    )
    history = tmp_path / "h.json"
    cfg = make_cfg(
        tmp_path,
        upload_enabled=True,
        auth_callback=lambda: True,
        history_file=str(history),
    )
    run_pipeline(cfg)
    data = json.loads(history.read_text(encoding="utf-8"))
    assert [u["status"] for u in data["uploads"]] == ["success", "failed"]
    assert data["uploads"][0]["youtube_url"] == "https://youtu.be/v1"
    assert data["uploads"][1]["error"] == "boom"


def test_pipeline_tolerates_history_write_error(monkeypatch, tmp_path):
    class FakeProcessor:
        def __init__(self, *a, **kw):
            pass

        def concat(self, cancel_event=None):
            return ["out.mp4"]

    monkeypatch.setattr("app.pipeline.VideoProcessor", FakeProcessor)
    monkeypatch.setattr(
        "app.pipeline.upload_video",
        lambda *a, **kw: {"file": "/tmp/out.mp4", "exit_code": 0, "video_id": "v1"},
    )

    def boom(*a, **kw):
        raise OSError("disk full")

    monkeypatch.setattr("app.pipeline.append_upload_history", boom)
    logs = []
    cfg = make_cfg(
        tmp_path,
        upload_enabled=True,
        auth_callback=lambda: True,
        history_file=str(tmp_path / "h.json"),
        log=logs.append,
    )
    result = run_pipeline(cfg)
    assert result["status"] == "done"
    assert any("無法寫入上傳紀錄" in line for line in logs)


def test_pipeline_skips_history_without_file(monkeypatch, tmp_path):
    calls = []

    class FakeProcessor:
        def __init__(self, *a, **kw):
            pass

        def concat(self, cancel_event=None):
            return ["out.mp4"]

    monkeypatch.setattr("app.pipeline.VideoProcessor", FakeProcessor)
    monkeypatch.setattr(
        "app.pipeline.upload_video",
        lambda *a, **kw: {"file": "/tmp/out.mp4", "exit_code": 0, "video_id": "v1"},
    )
    monkeypatch.setattr(
        "app.pipeline.append_upload_history", lambda *a, **kw: calls.append(1)
    )
    cfg = make_cfg(tmp_path, upload_enabled=True, auth_callback=lambda: True)
    run_pipeline(cfg)
    assert calls == []
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_pipeline.py -v`
Expected: 3 個新測試 FAIL（`TypeError: __init__() got an unexpected keyword argument 'history_file'`）

- [ ] **Step 3: 實作 `app/pipeline.py` 修改**

3a. import（第 8 行）：

```python
from upload_mp4_to_youtube import (
    append_upload_history,
    build_history_record,
    upload_video,
)
```

3b. `PipelineConfig` 加欄位（`credentials_file: str | None = None` 之後）：

```python
    history_file: str | None = None
```

3c. 上傳迴圈內、`upload_results.append(result)` 之後（cancel 檢查之前）：

```python
            if cfg.history_file:
                try:
                    append_upload_history(
                        cfg.history_file,
                        [build_history_record(result)],
                    )
                except OSError as exc:
                    cfg.log(f"無法寫入上傳紀錄: {exc}")
```

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/test_pipeline.py -v`
Expected: 既有 8 個 + 新 3 個 = 11 passed

- [ ] **Step 5: 全量測試 + commit**

Run: `pytest -q`（75 + 3 = 78 passed）

```bash
git add app/pipeline.py tests/test_pipeline.py
git commit -m "feat: write per-upload history records from E3V pipeline"
```

---

### Task 5: main.py 控制器 + 模式流程測試 + 重建

**Files:**
- Modify: `app/main.py`
- Create: `tests/test_mode_flow.py`

**Interfaces:**
- Consumes: `HomeWindow`（Task 1）、`MainWindow`（Task 2）、`UploadWindow`（不變）、`app.settings.AppSettings`
- Produces: `app.main._connect(home, main_window) -> None`（可測試的接線函式）；`main()` 改為首頁入口

- [ ] **Step 1: 寫失敗測試** `tests/test_mode_flow.py`

```python
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

import app.main as app_main
from app.settings import AppSettings
from app.ui.home_window import HomeWindow
from app.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


def _make_home(tmp_path, monkeypatch) -> HomeWindow:
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    monkeypatch.setattr(
        "app.ui.home_window.AppSettings",
        lambda: AppSettings(QSettings.IniFormat),
    )
    return HomeWindow()


def _make_main(tmp_path, monkeypatch) -> MainWindow:
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    monkeypatch.setattr(
        "app.ui.main_window.AppSettings",
        lambda: AppSettings(QSettings.IniFormat),
    )
    monkeypatch.setattr(
        "app.ui.main_window.resolve_ffmpeg", lambda: "/usr/bin/ffmpeg"
    )
    return MainWindow()


def test_e3v_button_switches_to_main_window(qapp, monkeypatch, tmp_path):
    home = _make_home(tmp_path, monkeypatch)
    main = _make_main(tmp_path, monkeypatch)
    app_main._connect(home, main)
    home.show()
    assert not main.isVisible()
    home.e3v_requested.emit()
    assert main.isVisible()
    assert not home.isVisible()


def test_upload_button_opens_upload_dialog(qapp, monkeypatch, tmp_path):
    opened = []

    class FakeDialog:
        def __init__(self, parent=None):
            opened.append(parent)

        def exec(self):
            return 0

    monkeypatch.setattr(app_main, "UploadWindow", FakeDialog)
    home = _make_home(tmp_path, monkeypatch)
    main = _make_main(tmp_path, monkeypatch)
    app_main._connect(home, main)
    home.show()
    home.upload_requested.emit()
    assert opened == [home]


def test_back_requested_returns_to_home(qapp, monkeypatch, tmp_path):
    home = _make_home(tmp_path, monkeypatch)
    main = _make_main(tmp_path, monkeypatch)
    app_main._connect(home, main)
    home.show()
    main.show()
    main.back_requested.emit()
    assert home.isVisible()
    assert not main.isVisible()
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_mode_flow.py -v`
Expected: FAIL — `AttributeError: module 'app.main' has no attribute '_connect'`

- [ ] **Step 3: 實作 `app/main.py`**

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

from app.ui.home_window import HomeWindow
from app.ui.main_window import MainWindow
from app.ui.upload_window import UploadWindow


def _connect(home: HomeWindow, main_window: MainWindow) -> None:
    home.e3v_requested.connect(lambda: (home.hide(), main_window.show()))
    home.upload_requested.connect(lambda: UploadWindow(home).exec())
    main_window.back_requested.connect(lambda: (main_window.hide(), home.show()))


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("concat-e3v")
    app.setOrganizationName("concat-e3v")
    app.setQuitOnLastWindowClosed(False)
    home = HomeWindow()
    main_window = MainWindow()
    _connect(home, main_window)
    home.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/test_mode_flow.py -v`
Expected: 3 passed

- [ ] **Step 5: 全量測試**

Run: `pytest -q`
Expected: 87 + 3 = **90 passed**

- [ ] **Step 6: 重建 app + commit**

Run: `PYTHON="$(pwd)/.venv-build/bin/python" ./build/build_mac.sh`
Expected: 結尾 `產物: /Users/double/Code/concat-e3v-video/dist/concat-e3v`

```bash
git add app/main.py tests/test_mode_flow.py
git commit -m "feat: home screen entry with mode switching controller"
```

---

## 執行順序

`Task 1 → Task 4 → Task 2 → Task 3 → Task 5`

（Task 4 的 `PipelineConfig.history_file` 是 Task 2 `_build_cfg` 傳參的前提；Task 2 與 Task 3 皆依賴 Task 1 的 helper。）

## Self-Review 紀錄

- **Spec 覆蓋**：1 首頁（Task 1）、2 控制器（Task 5）、3 MainWindow（Task 2）、4 UploadWindow（Task 3）、5 helper（Task 1）、6 pipeline（Task 4）、資料流與測試（分散各 task）、重建（Task 5）——全部覆蓋。
- **Placeholder**：無 TBD/TODO，所有程式碼皆內嵌。
- **型別一致**：`get_upload_history_file(s) -> str`、`PipelineConfig.history_file: str | None`、`back_requested`、`e3v_requested`/`upload_requested`、`_connect(home, main_window)` 各 task 引用一致。