# concat-e3v GUI 應用程式 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將現有 CLI 工具包裝成跨平台（mac/linux/windows）PySide6 桌面應用：UI 選擇目錄與時間範圍、可合併成單一 mp4、可靜音前 N 秒、可上傳 YouTube（勾選時優先檢查權限/憑證並在 UI 內重新授權）。

**Architecture:** 保留現有 CLI（`main.py`、`upload_mp4_to_youtube.py`）不動行為；`VideoProcessor` 增加 `merge_all`/`mute_seconds`/`ffmpeg_bin` 參數與取消支援；`upload_mp4_to_youtube.py` 抽出 in-process 可呼叫 API（`upload_video` + 可注入 `get_code_callback`）；新增 `app/` 套件：`pipeline.py`（純 Python 管線、可測試）、`worker.py`（QThread 薄包裝）、`ui/`（主視窗 + 授權對話框）、`ffmpeg.py`（ffmpeg 解析）、`settings.py`（QSettings）。PyInstaller onefile 打包，ffmpeg 以 `--add-data`/`binaries` 內建。

**Tech Stack:** Python 3.11（pyenv `e3v` venv）、PySide6 6.11、pytest、PyInstaller、ffmpeg（系統或內建二進位）。

## Global Constraints

- 時區固定 `Asia/Taipei`（`pytz.timezone("Asia/Taipei")`），與現有程式一致
- 來源檔名格式 `%Y%m%d%H%M%S`（`stem.split("_")[0]`），輸出檔名 `%Y_%m_%dT%H:%M:%S`（靜音時加 `_muted` 後綴）
- 靜音指令（單一 pass）：N>0 時 `-af "volume=0.0:enable='lt(t,N)'" -c:v copy -c:a aac`；N=0 時維持 `-c copy`
- 勾選上傳時，YouTube 檢查必須在**任何合併處理之前**執行；失敗 → UI 重新授權 → 重查通過才繼續
- 上傳對象 = 最終輸出檔（靜音時為 `_muted` 檔）
- CLI 行為不得改變：`main.py`、`upload_mp4_to_youtube.py` 指令列介面保持相容
- venv：`~/.pyenv/versions/e3v/bin/python`（3.11.1，x86_64）
- 所有 ffmpeg 呼叫一律用 list 參數（無 shell），路徑含空白安全

---

### Task 1: 環境與專案骨架

**Files:**
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `tests/__init__.py`
- Create: `.python-version`（內容 `e3v`，確保 pyenv 指到 e3v venv）

**Interfaces:**
- Produces: venv 內安裝 PySide6、pytest、PyInstaller；後續任務的測試/執行環境

- [ ] **Step 1: 安裝依賴到 e3v venv**

```bash
~/.pyenv/versions/e3v/bin/pip install "PySide6>=6.5" pytest pyinstaller
```

- [ ] **Step 2: 建立需求檔**

`requirements.txt`:
```
PySide6>=6.5
pytz
python-dateutil
```

`requirements-dev.txt`:
```
-r requirements.txt
pytest
pyinstaller
```

- [ ] **Step 3: 建立 tests 套件與 .python-version**

```bash
mkdir -p tests && touch tests/__init__.py
echo "e3v" > .python-version
```

- [ ] **Step 4: 驗證環境**

```bash
~/.pyenv/versions/e3v/bin/python -c "import PySide6, pytz, dateutil; print('ok')"
~/.pyenv/versions/e3v/bin/python -m pytest --version
```

Expected: 兩行皆成功輸出。

- [ ] **Step 5: Commit**

```bash
git add requirements.txt requirements-dev.txt tests/__init__.py .python-version
git commit -m "chore: add venv deps and test scaffolding"
```

---

### Task 2: VideoProcessor 支援 merge_all / mute / ffmpeg_bin / 取消

**Files:**
- Modify: `e3vvid/video_processor.py`
- Create: `tests/test_video_processor.py`

**Interfaces:**
- Consumes: 現有 `VideoProcessor.__init__`、`find_continous_video`、`concat`
- Produces:
  - `VideoProcessor.__init__(self, src_video_dir: str, dst_video_dir: str, start_time: datetime, end_time: datetime, timezone: tzinfo = pytz.timezone("Asia/Taipei"), merge_all: bool = False, mute_seconds: int = 0, ffmpeg_bin: str = "ffmpeg")`
  - `VideoProcessor.find_continous_video(self, interval: timedelta = relativedelta(minutes=1)) -> list[list[str]]`（merge_all=True 時回傳單一清單，格式 `["file '/path.ts'\n", ...]`）
  - `VideoProcessor.concat(self, cancel_event: threading.Event | None = None) -> list[str]`（回傳輸出檔名清單；N>0 時檔名含 `_muted` 後綴）
  - `VideoProcessor._build_concat_cmd(self, videolist: str, video_name: str) -> list[str]`

- [ ] **Step 1: 寫失敗測試**（`tests/test_video_processor.py`）

```python
from datetime import datetime, timedelta
import threading
import pytz
import pytest
from e3vvid.video_processor import VideoProcessor

TAIPEI = pytz.timezone("Asia/Taipei")


def make_processor(tmp_path, names, merge_all=False, mute_seconds=0, ffmpeg_bin="ffmpeg"):
    src = tmp_path / "src"
    src.mkdir()
    for n in names:
        (src / n).touch()
    dst = tmp_path / "dst"
    return VideoProcessor(
        str(src), str(dst),
        datetime(2026, 8, 25, 0, 0, 0).astimezone(TAIPEI),
        datetime(2026, 8, 25, 2, 0, 0).astimezone(TAIPEI),
        merge_all=merge_all, mute_seconds=mute_seconds, ffmpeg_bin=ffmpeg_bin,
    )


def test_merge_all_returns_single_segment(tmp_path):
    names = [
        "20260825000000_1.ts", "20260825000100_2.ts", "20260825000500_3.ts",
    ]
    proc = make_processor(tmp_path, names, merge_all=True)
    segs = proc.find_continous_video()
    assert len(segs) == 1
    assert len(segs[0]) == 3


def test_merge_all_filters_out_of_range(tmp_path):
    names = [
        "20260824000000_old.ts",
        "20260825000000_1.ts", "20260825000100_2.ts",
        "20260825030000_late.ts",
    ]
    proc = make_processor(tmp_path, names, merge_all=True)
    segs = proc.find_continous_video()
    assert len(segs) == 1
    assert len(segs[0]) == 2


def test_non_merge_keeps_segmentation(tmp_path):
    names = [
        "20260825000000_1.ts", "20260825000100_2.ts", "20260825000500_3.ts",
    ]
    proc = make_processor(tmp_path, names, merge_all=False)
    segs = proc.find_continous_video()
    assert len(segs) == 2
    assert len(segs[0]) == 2
    assert len(segs[1]) == 1


def test_concat_cmd_no_mute_uses_stream_copy(tmp_path):
    proc = make_processor(tmp_path, ["20260825000000_1.ts"], mute_seconds=0)
    cmd = proc._build_concat_cmd("videolist0.txt", "2026_08_25T00:00:00.mp4")
    assert "-c" in cmd and "copy" in cmd
    assert not any("volume" in c for c in cmd)
    assert cmd[0] == "ffmpeg"


def test_concat_cmd_mute_adds_filter_and_aac(tmp_path):
    proc = make_processor(tmp_path, ["20260825000000_1.ts"], mute_seconds=10)
    cmd = proc._build_concat_cmd("videolist0.txt", "2026_08_25T00:00:00_muted.mp4")
    assert any("volume=0.0:enable='lt(t,10)'" in c for c in cmd)
    assert cmd[cmd.index("-c:a") + 1] == "aac"


def test_concat_cmd_uses_ffmpeg_bin(tmp_path):
    proc = make_processor(tmp_path, ["20260825000000_1.ts"], ffmpeg_bin="/opt/ff/ffmpeg")
    cmd = proc._build_concat_cmd("videolist0.txt", "out.mp4")
    assert cmd[0] == "/opt/ff/ffmpeg"


def test_concat_returns_muted_name(tmp_path, monkeypatch):
    proc = make_processor(tmp_path, ["20260825000000_1.ts"], mute_seconds=10)
    monkeypatch.setattr("e3vvid.video_processor.Popen", _FakePopen)
    names = proc.concat()
    assert names == ["2026_08_25T00:00:00_muted.mp4"]


def test_concat_respects_cancel_event(tmp_path, monkeypatch):
    proc = make_processor(tmp_path, ["20260825000000_1.ts", "20260825000100_2.ts"])
    cancel = threading.Event()
    cancel.set()
    monkeypatch.setattr("e3vvid.video_processor.Popen", _FakePopen)
    names = proc.concat(cancel_event=cancel)
    assert names == []
```

並在檔案頂部加假 Popen（模擬成功執行，支援 kill）：

```python
class _FakePopen:
    def __init__(self, cmd, stdout=None, stderr=None, text=False):
        self.cmd = cmd
        self.returncode = 0
        self.stdout = ""
        self.stderr = ""

    def poll(self):
        return 0

    def kill(self):
        self.returncode = -9

    def communicate(self):
        return "", ""
```

- [ ] **Step 2: 跑測試確認失敗**

```bash
~/.pyenv/versions/e3v/bin/python -m pytest tests/test_video_processor.py -v
```

Expected: FAIL（`__init__` 不接受 `merge_all`/`mute_seconds`/`ffmpeg_bin` 關鍵字參數）。

- [ ] **Step 3: 實作 `video_processor.py` 修改**

修改 `__init__` 加入三個參數：

```python
    def __init__(
        self,
        src_video_dir: str,
        dst_video_dir: str,
        start_time: datetime,
        end_time: datetime,
        timezone: tzinfo = pytz.timezone("Asia/Taipei"),
        merge_all: bool = False,
        mute_seconds: int = 0,
        ffmpeg_bin: str = "ffmpeg",
    ):
        self._src_video_dir = src_video_dir
        self._dst_video_dir = dst_video_dir
        self._start_time = start_time
        self._end_time = end_time
        self._timezone = timezone
        self._merge_all = merge_all
        self._mute_seconds = mute_seconds
        self._ffmpeg_bin = ffmpeg_bin
```

改寫 `find_continous_video`（先篩出範圍內檔案，merge_all 時全部一個區段）：

```python
    def find_continous_video(
        self, interval: timedelta = relativedelta(minutes=1)
    ):
        raw_videos = self.get_videos(self._src_video_dir)
        if len(raw_videos) == 0:
            raise ValueError("No videos")

        in_range = [
            vid
            for vid in raw_videos
            if self._start_time
            <= self.convert_filename_to_datetime(vid)
            < self._end_time
        ]
        if len(in_range) == 0:
            raise ValueError("No videos in time range")

        if self._merge_all:
            return [[f"file '{vid}'\n" for vid in in_range]]

        last_time = self.convert_filename_to_datetime(
            in_range[0], format="%Y%m%d%H%M%S"
        )
        tmp_list = []
        video_list = []
        for vid in in_range:
            file_date = self.convert_filename_to_datetime(
                vid, format="%Y%m%d%H%M%S"
            )
            this_time = last_time + interval
            if this_time != file_date:
                if len(tmp_list) != 0:
                    video_list.append(tmp_list.copy())
                    tmp_list.clear()
            tmp_list.append(f"file '{vid}'\n")
            last_time = file_date
        if len(tmp_list):
            video_list.append(tmp_list.copy())
        return video_list
```

加入 `_build_concat_cmd` 並改寫 `concat`（Popen + 取消支援 + `_muted` 命名）：

```python
    def _build_concat_cmd(self, videolist: str, video_name: str) -> list:
        cmd = [
            self._ffmpeg_bin, "-y", "-f", "concat", "-safe", "0",
            "-i", videolist,
        ]
        if self._mute_seconds > 0:
            cmd += [
                "-c:v", "copy",
                "-af", f"volume=0.0:enable='lt(t,{self._mute_seconds})'",
                "-c:a", "aac",
            ]
        else:
            cmd += ["-c", "copy"]
        cmd.append(str(Path(self._dst_video_dir) / video_name))
        return cmd

    def concat(self, cancel_event: Event | None = None) -> list:
        import time as _time
        video_list = self.find_continous_video()
        try:
            dst = Path(self._dst_video_dir)
            dst.mkdir(parents=True, exist_ok=True)

            procs = []
            video_names = []
            for i, v in enumerate(video_list):
                if cancel_event is not None and cancel_event.is_set():
                    break
                videolist = Path(f"videolist{i}.txt")
                with open(videolist, "w") as f:
                    f.writelines(v)

                dat = self.convert_filename_to_datetime(v[0])
                base_name = dat.strftime("%Y_%m_%dT%H:%M:%S")
                suffix = "_muted" if self._mute_seconds > 0 else ""
                video_name = f"{base_name}{suffix}.mp4"

                cmd = self._build_concat_cmd(
                    videolist.as_posix(), video_name
                )
                logging.info(cmd)
                proc = Popen(cmd, stdout=PIPE, stderr=PIPE, text=True)
                procs.append(proc)
                video_names.append(video_name)

                if cancel_event is not None:
                    while proc.poll() is None:
                        if cancel_event.is_set():
                            proc.kill()
                            break
                        _time.sleep(0.1)
                else:
                    proc.communicate()

            for p in procs:
                if p.returncode != 0:
                    print("處理失敗:", p.stderr)
                    return []
                else:
                    print("成功:", p.stdout)

            return video_names
        finally:
            for i, v in enumerate(video_list):
                Path(f"videolist{i}.txt").unlink()
```

注意：檔案頂部需 `from threading import Event`（`Event` 型別註解用）。

- [ ] **Step 4: 跑測試確認通過**

```bash
~/.pyenv/versions/e3v/bin/python -m pytest tests/test_video_processor.py -v
```

Expected: 全部 PASS（9 個測試）。

- [ ] **Step 5: 回歸確認 CLI 仍可 import**

```bash
~/.pyenv/versions/e3v/bin/python -c "from e3vvid.video_processor import VideoProcessor; from main import parse_args; print('ok')"
```

Expected: `ok`

- [ ] **Step 6: Commit**

```bash
git add e3vvid/video_processor.py tests/test_video_processor.py
git commit -m "feat: support merge_all, mute_seconds, ffmpeg_bin and cancel in VideoProcessor"
```

---

### Task 3: upload_mp4_to_youtube 抽出 in-process API

**Files:**
- Modify: `upload_mp4_to_youtube.py`
- Create: `tests/test_upload_api.py`

**Interfaces:**
- Consumes: 現有 `check_youtube_upload_available`、`_upload_one_video`、`_ensure_vendored_youtube_upload`
- Produces:
  - `check_youtube_upload_available(client_secrets: str | None = None, credentials_file: str | None = None, auth_browser: bool = False, get_code_callback: Callable[[str], str] | None = None) -> None`
  - `upload_video(video_path: str | Path, *, title: str | None = None, description: str | None = None, category: str | None = None, tags: str | None = None, privacy: str = "private", playlist: str | None = None, client_secrets: str | None = None, credentials_file: str | None = None) -> dict[str, str | int | None]`

- [ ] **Step 1: 寫失敗測試**（`tests/test_upload_api.py`）

```python
import sys
import types
from pathlib import Path
import pytest
import upload_mp4_to_youtube as up


@pytest.fixture
def fake_vendored(monkeypatch):
    """預先注入 fake youtube_upload 套件到 sys.modules，避免打到真的 vendored 套件。"""
    youtube_upload = types.ModuleType("youtube_upload")
    auth = types.ModuleType("youtube_upload.auth")
    browser = types.ModuleType("youtube_upload.auth.browser")
    console = types.ModuleType("youtube_upload.auth.console")
    main_mod = types.ModuleType("youtube_upload.main")

    youtube_upload.auth = auth
    youtube_upload.main = main_mod
    auth.browser = browser
    auth.console = console
    main_mod.main = lambda args: None

    for name, mod in {
        "youtube_upload": youtube_upload,
        "youtube_upload.auth": auth,
        "youtube_upload.auth.browser": browser,
        "youtube_upload.auth.console": console,
        "youtube_upload.main": main_mod,
    }.items():
        monkeypatch.setitem(sys.modules, name, mod)

    return auth, browser, console, main_mod


class FakeYouTube:
    def __init__(self, calls):
        self._calls = calls

    def channels(self):
        return self

    def list(self, mine=True, part="id", maxResults=1):
        self._calls["listed"] = True
        return self

    def execute(self):
        return {"items": [{"id": "x"}]}


def test_check_available_uses_custom_get_code_callback(monkeypatch, fake_vendored):
    auth, _browser, _console, _main = fake_vendored
    calls = {}

    def fake_get_resource(client_secrets, credentials_file, get_code_callback=None):
        calls["callback"] = get_code_callback
        return FakeYouTube(calls)

    auth.get_resource = fake_get_resource
    monkeypatch.setattr(up, "_default_client_secrets_path", lambda: "/tmp/cs.json")

    def my_callback(url):
        return "CODE"

    up.check_youtube_upload_available(
        client_secrets="/tmp/cs.json",
        credentials_file="/tmp/cred.json",
        get_code_callback=my_callback,
    )
    assert calls["callback"] is my_callback
    assert calls.get("listed")


def test_upload_video_returns_result_dict(monkeypatch, tmp_path, fake_vendored):
    video = tmp_path / "test.mp4"
    video.write_bytes(b"x")

    def fake_upload_one(ns, video_path, youtube_upload_main):
        return {
            "file": video_path.as_posix(),
            "name": video_path.name,
            "exit_code": 0,
            "video_id": "abc123",
        }

    monkeypatch.setattr(up, "_upload_one_video", fake_upload_one)

    result = up.upload_video(
        str(video), title="My Title", privacy="unlisted"
    )
    assert result["exit_code"] == 0
    assert result["video_id"] == "abc123"
    assert result["name"] == "test.mp4"


def test_upload_video_default_title_is_stem(monkeypatch, tmp_path, fake_vendored):
    video = tmp_path / "2026_08_25T00:00:00.mp4"
    video.write_bytes(b"x")
    seen = {}

    def fake_upload_one(ns, video_path, youtube_upload_main):
        seen["title"] = ns.title
        seen["privacy"] = ns.privacy
        return {"file": str(video_path), "name": video_path.name, "exit_code": 0}

    monkeypatch.setattr(up, "_upload_one_video", fake_upload_one)

    up.upload_video(str(video))
    assert seen["title"] == "2026_08_25T00:00:00"
    assert seen["privacy"] == "private"


def test_upload_video_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        up.upload_video(str(tmp_path / "nope.mp4"))
```

- [ ] **Step 2: 跑測試確認失敗**

```bash
~/.pyenv/versions/e3v/bin/python -m pytest tests/test_upload_api.py -v
```

Expected: FAIL（`upload_video` 不存在、`check_youtube_upload_available` 不接受 `get_code_callback`）。

- [ ] **Step 3: 實作修改**

在 `check_youtube_upload_available` 簽名加 `get_code_callback` 參數，並優先使用它：

```python
def check_youtube_upload_available(
    client_secrets: str | None = None,
    credentials_file: str | None = None,
    auth_browser: bool = False,
    get_code_callback: Callable[[str], str] | None = None,
) -> None:
    parser = argparse.ArgumentParser(add_help=False)
    _ensure_vendored_youtube_upload(parser)

    from youtube_upload import auth  # type: ignore
    from youtube_upload.auth import browser  # type: ignore
    from youtube_upload.auth import console  # type: ignore

    resolved_client_secrets = (
        client_secrets or _default_client_secrets_path()
    )
    if resolved_client_secrets is None:
        parser.error(
            "No client secrets JSON found. Provide --client-secrets, "
            "or place a client_secret*.json at repo root (or ~/.client_secrets.json)."
        )

    resolved_credentials = credentials_file
    if resolved_credentials is None:
        resolved_credentials = str(
            Path.home() / ".youtube-upload-credentials.json"
        )

    if get_code_callback is None:
        get_code_callback = (
            browser.get_code
            if auth_browser
            else console.get_code
        )
    youtube = auth.get_resource(
        resolved_client_secrets,
        resolved_credentials,
        get_code_callback=get_code_callback,
    )
    if youtube is None:
        raise RuntimeError(
            "Cannot authenticate with YouTube"
        )

    youtube.channels().list(
        mine=True,
        part="id",
        maxResults=1,
    ).execute()
```

在 `_build_youtube_upload_args` 之後、`main()` 之前新增 `upload_video`：

```python
def upload_video(
    video_path: str | Path,
    *,
    title: str | None = None,
    description: str | None = None,
    category: str | None = None,
    tags: str | None = None,
    privacy: str = "private",
    playlist: str | None = None,
    client_secrets: str | None = None,
    credentials_file: str | None = None,
) -> dict[str, str | int | None]:
    """Upload a single mp4 in-process (no subprocess). Returns result dict."""
    video_path = Path(video_path).expanduser().resolve()
    if not video_path.exists():
        raise FileNotFoundError(video_path.as_posix())

    parser = argparse.ArgumentParser(add_help=False)
    _ensure_vendored_youtube_upload(parser)
    from youtube_upload import main as youtube_upload_main  # type: ignore

    ns = argparse.Namespace(
        video=video_path.as_posix(),
        title=title if title is not None else video_path.stem,
        description=description,
        description_file=None,
        category=category,
        tags=tags,
        privacy=privacy,
        publish_at=None,
        recording_date=None,
        default_language=None,
        default_audio_language=None,
        thumbnail=None,
        playlist=playlist,
        client_secrets=client_secrets,
        credentials_file=credentials_file,
        auth_browser=False,
        open_link=False,
    )
    return _upload_one_video(ns, video_path, youtube_upload_main)
```

檔案頂部 import 補上 `Callable`（`from typing import Callable`，或改 `collections.abc`）。

- [ ] **Step 4: 跑測試確認通過**

```bash
~/.pyenv/versions/e3v/bin/python -m pytest tests/test_upload_api.py -v
```

Expected: 全部 PASS。

- [ ] **Step 5: 回歸確認 CLI 可用**

```bash
~/.pyenv/versions/e3v/bin/python upload_mp4_to_youtube.py --help | head -5
```

Expected: 顯示 usage（與原本一致）。

- [ ] **Step 6: Commit**

```bash
git add upload_mp4_to_youtube.py tests/test_upload_api.py
git commit -m "feat: expose in-process upload_video API and injectable get_code_callback"
```

---

### Task 4: ffmpeg 解析與 QSettings 持久化

**Files:**
- Create: `app/__init__.py`
- Create: `app/ffmpeg.py`
- Create: `app/settings.py`
- Create: `tests/test_ffmpeg.py`
- Create: `tests/test_settings.py`

**Interfaces:**
- Consumes: PySide6 `QSettings`
- Produces:
  - `app/ffmpeg.py`：`resolve_ffmpeg() -> str | None`（解析順序：`sys.executable` 目錄 → `sys._MEIPASS` → `shutil.which("ffmpeg")`；windows 用 `ffmpeg.exe`）
  - `app/settings.py`：`class AppSettings(QSettings)`，`value(key, default=None)` / `set_value(key, value)` 封裝，keys：`src_dir`、`dst_dir`、`merge_all`、`mute_seconds`、`upload_enabled`、`upload_title`、`upload_description`、`upload_privacy`、`upload_tags`、`upload_playlist`、`client_secrets`、`start_time`、`end_time`

- [ ] **Step 1: 寫失敗測試**

`tests/test_ffmpeg.py`:

```python
import os
import shutil
import sys
import pytest
from app.ffmpeg import resolve_ffmpeg


def test_resolve_from_executable_dir(monkeypatch, tmp_path):
    exe = tmp_path / "concat-e3v"
    (tmp_path / "ffmpeg").write_bytes(b"x")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert resolve_ffmpeg() == str(tmp_path / "ffmpeg")


def test_resolve_from_meipass(monkeypatch, tmp_path):
    exe = tmp_path / "concat-e3v"
    meipass = tmp_path / "_internal"
    (meipass / "ffmpeg").write_bytes(b"x")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
    assert resolve_ffmpeg() == str(meipass / "ffmpeg")


def test_resolve_windows_exe_name(monkeypatch, tmp_path):
    exe = tmp_path / "concat-e3v.exe"
    (tmp_path / "ffmpeg.exe").write_bytes(b"x")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(os, "name", "nt")
    assert resolve_ffmpeg() == str(tmp_path / "ffmpeg.exe")


def test_resolve_from_path(monkeypatch, tmp_path):
    fake = tmp_path / "ffmpeg"
    fake.write_bytes(b"x")
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: str(fake))
    assert resolve_ffmpeg() == str(fake)


def test_resolve_none(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert resolve_ffmpeg() is None
```

`tests/test_settings.py`:

```python
from pathlib import Path
from app.settings import AppSettings


def test_settings_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    s = AppSettings()
    s.set_value("src_dir", "/tmp/src")
    s2 = AppSettings()
    assert s2.value("src_dir") == "/tmp/src"


def test_settings_default(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    s = AppSettings()
    assert s.value("merge_all", False) is False
```

- [ ] **Step 2: 跑測試確認失敗**

```bash
~/.pyenv/versions/e3v/bin/python -m pytest tests/test_ffmpeg.py tests/test_settings.py -v
```

Expected: FAIL（`app` 模組不存在）。

- [ ] **Step 3: 實作**

`app/__init__.py`:
```python
```

`app/ffmpeg.py`:
```python
import os
import shutil
import sys
from pathlib import Path


def _candidate_dirs() -> list[Path]:
    dirs: list[Path] = []
    if getattr(sys, "frozen", False):
        dirs.append(Path(sys.executable).parent)
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            dirs.append(Path(meipass))
    return dirs


def resolve_ffmpeg() -> str | None:
    name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    for base in _candidate_dirs():
        candidate = base / name
        if candidate.is_file():
            return str(candidate)
    return shutil.which("ffmpeg")
```

`app/settings.py`:
```python
from PySide6.QtCore import QSettings


class AppSettings(QSettings):
    def __init__(self):
        super().__init__("concat-e3v", "concat-e3v-gui")

    def set_value(self, key: str, value):
        self.setValue(key, value)

    def value(self, key: str, default=None):
        return super().value(key, default)
```

- [ ] **Step 4: 跑測試確認通過**

```bash
~/.pyenv/versions/e3v/bin/python -m pytest tests/test_ffmpeg.py tests/test_settings.py -v
```

Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add app/ tests/test_ffmpeg.py tests/test_settings.py
git commit -m "feat: add ffmpeg resolution and QSettings persistence"
```

---

### Task 5: pipeline.py 管線編排

**Files:**
- Create: `app/pipeline.py`
- Create: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: Task 2 的 `VideoProcessor`（`merge_all`/`mute_seconds`/`ffmpeg_bin`/`concat(cancel_event=...)`）、Task 3 的 `upload_video` 與 `check_youtube_upload_available`
- Produces:
  - `app/pipeline.py`：
    - `@dataclass class PipelineConfig`：`src_dir: str`、`dst_dir: str`、`start_time: datetime`、`end_time: datetime`、`merge_all: bool = False`、`mute_seconds: int = 0`、`ffmpeg_bin: str = "ffmpeg"`、`upload_enabled: bool = False`、`upload_title: str | None = None`、`upload_description: str | None = None`、`upload_privacy: str = "private"`、`upload_tags: str | None = None`、`upload_playlist: str | None = None`、`client_secrets: str | None = None`、`credentials_file: str | None = None`、`cancel_event: threading.Event | None = None`、`auth_callback: Callable[[], bool] | None = None`、`log: Callable[[str], None] = <no-op>`
    - `run_pipeline(cfg: PipelineConfig) -> dict`，回傳 `{"status": "done"|"aborted"|"failed", "video_names": list[str], "upload_results": list[dict], "reason": str | None}`

- [ ] **Step 1: 寫失敗測試**（`tests/test_pipeline.py`）

```python
from datetime import datetime
import threading
import pytz
import pytest
from app.pipeline import PipelineConfig, run_pipeline

TAIPEI = pytz.timezone("Asia/Taipei")


def make_cfg(tmp_path, **kw):
    base = dict(
        src_dir=str(tmp_path / "src"),
        dst_dir=str(tmp_path / "dst"),
        start_time=datetime(2026, 8, 25, 0, 0, 0).astimezone(TAIPEI),
        end_time=datetime(2026, 8, 25, 2, 0, 0).astimezone(TAIPEI),
        ffmpeg_bin="ffmpeg",
    )
    base.update(kw)
    return PipelineConfig(**base)


def test_pipeline_skips_youtube_check_when_disabled(monkeypatch, tmp_path):
    called = []

    class FakeProcessor:
        def __init__(self, *a, **kw):
            pass

        def concat(self, cancel_event=None):
            called.append("concat")
            return ["out.mp4"]

    monkeypatch.setattr("app.pipeline.VideoProcessor", FakeProcessor)
    monkeypatch.setattr("app.pipeline.upload_video", lambda *a, **kw: called.append("upload"))
    cfg = make_cfg(tmp_path)
    result = run_pipeline(cfg)
    assert result["status"] == "done"
    assert called == ["concat"]


def test_pipeline_checks_youtube_first_when_enabled(monkeypatch, tmp_path):
    order = []

    def fake_auth():
        order.append("auth")
        return True

    class FakeProcessor:
        def __init__(self, *a, **kw):
            pass

        def concat(self, cancel_event=None):
            order.append("concat")
            return ["out.mp4"]

    monkeypatch.setattr("app.pipeline.VideoProcessor", FakeProcessor)
    monkeypatch.setattr(
        "app.pipeline.upload_video",
        lambda *a, **kw: order.append("upload") or {"exit_code": 0, "video_id": "v1"},
    )
    cfg = make_cfg(tmp_path, upload_enabled=True, auth_callback=fake_auth)
    result = run_pipeline(cfg)
    assert result["status"] == "done"
    assert order == ["auth", "concat", "auth", "upload"]


def test_pipeline_aborts_when_auth_fails(monkeypatch, tmp_path):
    monkeypatch.setattr("app.pipeline.VideoProcessor", lambda *a, **kw: None)
    cfg = make_cfg(tmp_path, upload_enabled=True, auth_callback=lambda: False)
    result = run_pipeline(cfg)
    assert result["status"] == "aborted"
    assert result["reason"] == "youtube-auth-failed"


def test_pipeline_rechecks_before_upload(monkeypatch, tmp_path):
    checks = {"n": 0}

    def fake_auth():
        checks["n"] += 1
        return True

    class FakeProcessor:
        def __init__(self, *a, **kw):
            pass

        def concat(self, cancel_event=None):
            return ["out.mp4"]

    monkeypatch.setattr("app.pipeline.VideoProcessor", FakeProcessor)
    monkeypatch.setattr("app.pipeline.upload_video", lambda *a, **kw: {"exit_code": 0})
    cfg = make_cfg(tmp_path, upload_enabled=True, auth_callback=fake_auth)
    run_pipeline(cfg)
    assert checks["n"] == 2


def test_pipeline_passes_upload_options(monkeypatch, tmp_path):
    seen = {}

    class FakeProcessor:
        def __init__(self, *a, **kw):
            pass

        def concat(self, cancel_event=None):
            return ["out.mp4"]

    def fake_upload(video_path, **kw):
        seen.update(kw)
        return {"exit_code": 0}

    monkeypatch.setattr("app.pipeline.VideoProcessor", FakeProcessor)
    monkeypatch.setattr("app.pipeline.upload_video", fake_upload)
    cfg = make_cfg(
        tmp_path,
        upload_enabled=True,
        auth_callback=lambda: True,
        upload_title="T",
        upload_description="D",
        upload_privacy="unlisted",
        upload_tags="a,b",
        upload_playlist="P",
    )
    run_pipeline(cfg)
    assert seen["title"] == "T"
    assert seen["description"] == "D"
    assert seen["privacy"] == "unlisted"
    assert seen["tags"] == "a,b"
    assert seen["playlist"] == "P"


def test_pipeline_logs_progress(monkeypatch, tmp_path):
    logs = []

    class FakeProcessor:
        def __init__(self, *a, **kw):
            pass

        def concat(self, cancel_event=None):
            return ["out.mp4"]

    monkeypatch.setattr("app.pipeline.VideoProcessor", FakeProcessor)
    cfg = make_cfg(tmp_path, log=logs.append)
    run_pipeline(cfg)
    assert any("合併後影片" in line for line in logs)
```

- [ ] **Step 2: 跑測試確認失敗**

```bash
~/.pyenv/versions/e3v/bin/python -m pytest tests/test_pipeline.py -v
```

Expected: FAIL（`app.pipeline` 不存在）。

- [ ] **Step 3: 實作 `app/pipeline.py`**

```python
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Event
from typing import Callable

from e3vvid.video_processor import VideoProcessor
from upload_mp4_to_youtube import upload_video


def _noop(msg: str) -> None:
    pass


@dataclass
class PipelineConfig:
    src_dir: str
    dst_dir: str
    start_time: datetime
    end_time: datetime
    merge_all: bool = False
    mute_seconds: int = 0
    ffmpeg_bin: str = "ffmpeg"
    upload_enabled: bool = False
    upload_title: str | None = None
    upload_description: str | None = None
    upload_privacy: str = "private"
    upload_tags: str | None = None
    upload_playlist: str | None = None
    client_secrets: str | None = None
    credentials_file: str | None = None
    cancel_event: Event | None = None
    auth_callback: Callable[[], bool] | None = None
    log: Callable[[str], None] = field(default=_noop)


def _check_auth(cfg: PipelineConfig) -> bool:
    if cfg.auth_callback is None:
        return False
    return cfg.auth_callback()


def run_pipeline(cfg: PipelineConfig) -> dict:
    if cfg.upload_enabled and not _check_auth(cfg):
        return {
            "status": "aborted",
            "reason": "youtube-auth-failed",
            "video_names": [],
            "upload_results": [],
        }

    cfg.log(f"開始合併: {cfg.src_dir} -> {cfg.dst_dir}")
    processor = VideoProcessor(
        src_video_dir=cfg.src_dir,
        dst_video_dir=cfg.dst_dir,
        start_time=cfg.start_time,
        end_time=cfg.end_time,
        merge_all=cfg.merge_all,
        mute_seconds=cfg.mute_seconds,
        ffmpeg_bin=cfg.ffmpeg_bin,
    )

    video_names = processor.concat(cancel_event=cfg.cancel_event)
    if not video_names:
        return {
            "status": "failed",
            "reason": "concat-failed",
            "video_names": [],
            "upload_results": [],
        }
    cfg.log(f"合併後影片: {video_names}")

    upload_results = []
    if cfg.upload_enabled:
        if not _check_auth(cfg):
            return {
                "status": "aborted",
                "reason": "youtube-auth-failed",
                "video_names": video_names,
                "upload_results": [],
            }
        for name in video_names:
            if cfg.cancel_event is not None and cfg.cancel_event.is_set():
                break
            path = Path(cfg.dst_dir) / name
            cfg.log(f"上傳 {path} 到 YouTube...")
            result = upload_video(
                str(path),
                title=cfg.upload_title,
                description=cfg.upload_description,
                tags=cfg.upload_tags,
                privacy=cfg.upload_privacy,
                playlist=cfg.upload_playlist,
                client_secrets=cfg.client_secrets,
                credentials_file=cfg.credentials_file,
            )
            upload_results.append(result)
            if result.get("exit_code") == 0:
                cfg.log(f"上傳成功: {result.get('video_id')}")
            else:
                cfg.log(f"上傳失敗: {result.get('error')}")

    return {
        "status": "done",
        "video_names": video_names,
        "upload_results": upload_results,
        "reason": None,
    }
```

- [ ] **Step 4: 跑測試確認通過**

```bash
~/.pyenv/versions/e3v/bin/python -m pytest tests/test_pipeline.py -v
```

Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add app/pipeline.py tests/test_pipeline.py
git commit -m "feat: add testable pipeline orchestration"
```

---

### Task 6: worker.py（QThread 包裝 + 授權互動）

**Files:**
- Create: `app/worker.py`
- Create: `tests/test_worker.py`

**Interfaces:**
- Consumes: Task 5 `PipelineConfig`/`run_pipeline`、Task 3 `check_youtube_upload_available`
- Produces:
  - `app/worker.py`：
    - `class PipelineWorker(QThread)`：`log = pyqtSignal(str)`、`finished = pyqtSignal(dict)`、`auth_required = pyqtSignal(str)`（初始檢查失敗）、`auth_code_required = pyqtSignal(str)`（需要貼驗證碼）
    - `PipelineWorker.__init__(self, cfg: PipelineConfig, parent=None)`
    - `cancel(self) -> None`（設定取消旗標，管線在下個步驟中止）
    - `submit_auth_code(self, code: str) -> None`（主執行緒回傳使用者貼的驗證碼）
    - `retry_auth(self) -> None`（主執行緒按下「重試」後放行重查）
    - `run(self)`：設定 `cfg.cancel_event`/`cfg.auth_callback`/`cfg.log` 後呼叫 `run_pipeline`，`finished.emit(result)`；例外則 emit `{"status": "failed", "reason": str(exc), ...}`

- [ ] **Step 1: 寫失敗測試**（`tests/test_worker.py`，用 `QT_QPA_PLATFORM=offscreen`）

```python
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime
import threading
import pytz
import pytest
from PySide6.QtCore import QCoreApplication
from app.pipeline import PipelineConfig
from app.worker import PipelineWorker

TAIPEI = pytz.timezone("Asia/Taipei")


@pytest.fixture(scope="module")
def qapp():
    app = QCoreApplication.instance() or QCoreApplication([])
    return app


def make_cfg(tmp_path, **kw):
    base = dict(
        src_dir=str(tmp_path / "src"),
        dst_dir=str(tmp_path / "dst"),
        start_time=datetime(2026, 8, 25, 0, 0, 0).astimezone(TAIPEI),
        end_time=datetime(2026, 8, 25, 2, 0, 0).astimezone(TAIPEI),
        upload_enabled=True,
    )
    base.update(kw)
    return PipelineConfig(**base)


def test_worker_emits_finished_on_success(qapp, monkeypatch, tmp_path):
    def fake_run_pipeline(cfg):
        cfg.log("hi")
        return {"status": "done", "video_names": ["out.mp4"], "upload_results": [], "reason": None}

    def fake_check(*a, **kw):
        return None

    monkeypatch.setattr("app.worker.run_pipeline", fake_run_pipeline)
    monkeypatch.setattr("app.worker.check_youtube_upload_available", fake_check)

    cfg = make_cfg(tmp_path)
    worker = PipelineWorker(cfg)
    results = {}

    def on_finished(result):
        results.update(result)
        worker.quit()

    worker.finished.connect(on_finished)
    worker.start()
    assert worker.wait(5000)
    assert results["status"] == "done"


def test_worker_emits_failed_on_exception(qapp, monkeypatch, tmp_path):
    def boom(cfg):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.worker.run_pipeline", boom)
    cfg = make_cfg(tmp_path)
    worker = PipelineWorker(cfg)
    results = {}

    def on_finished(result):
        results.update(result)
        worker.quit()

    worker.finished.connect(on_finished)
    worker.start()
    assert worker.wait(5000)
    assert results["status"] == "failed"
    assert results["reason"] == "boom"


def test_worker_cancel_sets_event(qapp, tmp_path):
    cfg = make_cfg(tmp_path)
    worker = PipelineWorker(cfg)
    worker.cancel()
    assert cfg.cancel_event is not None
    assert cfg.cancel_event.is_set()
```

- [ ] **Step 2: 跑測試確認失敗**

```bash
~/.pyenv/versions/e3v/bin/python -m pytest tests/test_worker.py -v
```

Expected: FAIL（`app.worker` 不存在）。

- [ ] **Step 3: 實作 `app/worker.py`**

```python
import threading

from PySide6.QtCore import QThread, Signal

from app.pipeline import PipelineConfig, run_pipeline
from upload_mp4_to_youtube import check_youtube_upload_available


class PipelineWorker(QThread):
    log = Signal(str)
    finished = Signal(dict)
    auth_required = Signal(str)
    auth_code_required = Signal(str)

    def __init__(self, cfg: PipelineConfig, parent=None):
        super().__init__(parent)
        self._cfg = cfg
        self._cancel = threading.Event()
        cfg.cancel_event = self._cancel
        self._code_event = threading.Event()
        self._code: str | None = None
        self._retry_event = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()
        self._code_event.set()
        self._retry_event.set()

    def submit_auth_code(self, code: str) -> None:
        self._code = code
        self._code_event.set()

    def retry_auth(self) -> None:
        self._retry_event.set()

    def _get_code_callback(self, url: str) -> str:
        self.auth_code_required.emit(url)
        self._code_event.wait()
        self._code_event.clear()
        if self._cancel.is_set():
            raise RuntimeError("auth cancelled")
        return self._code or ""

    def _auth_check(self) -> bool:
        while not self._cancel.is_set():
            try:
                check_youtube_upload_available(
                    client_secrets=self._cfg.client_secrets,
                    credentials_file=self._cfg.credentials_file,
                    get_code_callback=self._get_code_callback,
                )
                return True
            except Exception as exc:
                self.auth_required.emit(str(exc))
                self._retry_event.wait()
                self._retry_event.clear()
        return False

    def run(self) -> None:
        cfg = self._cfg
        cfg.auth_callback = self._auth_check
        cfg.log = self.log.emit
        try:
            result = run_pipeline(cfg)
        except Exception as exc:
            result = {
                "status": "failed",
                "reason": str(exc),
                "video_names": [],
                "upload_results": [],
            }
        self.finished.emit(result)
```

- [ ] **Step 4: 跑測試確認通過**

```bash
~/.pyenv/versions/e3v/bin/python -m pytest tests/test_worker.py -v
```

Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add app/worker.py tests/test_worker.py
git commit -m "feat: add QThread pipeline worker with auth interaction"
```

---

### Task 7: GUI 主視窗與授權對話框

**Files:**
- Create: `app/main.py`
- Create: `app/ui/__init__.py`
- Create: `app/ui/auth_dialog.py`
- Create: `app/ui/main_window.py`
- Create: `tests/test_gui_smoke.py`

**Interfaces:**
- Consumes: Task 4 `resolve_ffmpeg`/`AppSettings`、Task 6 `PipelineWorker`
- Produces:
  - `app/main.py`：`main() -> int`（QApplication 入口，`app.exec()`）
  - `app/ui/auth_dialog.py`：`class AuthDialog(QDialog)`，`__init__(self, url: str, parent=None)`，`code(self) -> str`
  - `app/ui/main_window.py`：`class MainWindow(QMainWindow)`，`_on_start()`（驗證 → 啟動 worker）、`_on_finished(result: dict)`、`_on_auth_required(message: str)`、`_on_auth_code_required(url: str)`、`_build_cfg() -> PipelineConfig`（欄位 → config）、`_save_settings()` / `_load_settings()`

- [ ] **Step 1: 寫冒煙測試**（`tests/test_gui_smoke.py`）

```python
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QCheckBox, QSpinBox, QDateTimeEdit
from app.ui.main_window import MainWindow
from app.pipeline import PipelineConfig


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


def test_main_window_constructs(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr("app.ui.main_window.resolve_ffmpeg", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    window = MainWindow()
    assert window.windowTitle() == "concat-e3v"
    assert window.merge_all_check is not None
    assert isinstance(window.mute_spin, QSpinBox)
    assert isinstance(window.start_edit, QDateTimeEdit)
    assert isinstance(window.end_edit, QDateTimeEdit)


def test_build_cfg_fields(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr("app.ui.main_window.resolve_ffmpeg", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    window = MainWindow()
    window.src_edit.setText(str(tmp_path))
    window.dst_edit.setText(str(tmp_path / "out"))
    window.merge_all_check.setChecked(True)
    window.mute_spin.setValue(10)
    cfg = window._build_cfg()
    assert isinstance(cfg, PipelineConfig)
    assert cfg.merge_all is True
    assert cfg.mute_seconds == 10
    assert cfg.ffmpeg_bin == "/usr/bin/ffmpeg"


def test_validation_rejects_bad_time(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr("app.ui.main_window.resolve_ffmpeg", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    window = MainWindow()
    window.src_edit.setText(str(tmp_path))
    window.dst_edit.setText(str(tmp_path / "out"))
    window.start_edit.setDateTime(window.end_edit.dateTime())
    assert window._validate() != []
```

- [ ] **Step 2: 跑測試確認失敗**

```bash
~/.pyenv/versions/e3v/bin/python -m pytest tests/test_gui_smoke.py -v
```

Expected: FAIL（`app.ui` 不存在）。

- [ ] **Step 3: 實作**

`app/main.py`:
```python
import sys

from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("concat-e3v")
    app.setOrganizationName("concat-e3v")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
```

`app/ui/__init__.py`:
```python
```

`app/ui/auth_dialog.py`:
```python
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QLineEdit,
    QPushButton, QVBoxLayout,
)


class AuthDialog(QDialog):
    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("YouTube 授權")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("請在瀏覽器中開啟以下連結並登入授權："))
        url_edit = QLineEdit(url)
        url_edit.setReadOnly(True)
        layout.addWidget(url_edit)

        open_btn = QPushButton("在瀏覽器開啟")
        open_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(url))
        )
        layout.addWidget(open_btn)

        layout.addWidget(QLabel("授權後請將驗證碼貼到下方："))
        self._code_edit = QLineEdit()
        self._code_edit.setPlaceholderText("驗證碼")
        layout.addWidget(self._code_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._code_edit.setFocus()

    def code(self) -> str:
        return self._code_edit.text().strip()
```

`app/ui/main_window.py`（完整實作）：

```python
from datetime import datetime, timedelta
from pathlib import Path

import pytz
from PySide6.QtCore import Qt, QDateTime, QTimeZone
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateTimeEdit, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout,
    QWidget,
)

from app.ffmpeg import resolve_ffmpeg
from app.pipeline import PipelineConfig
from app.settings import AppSettings
from app.ui.auth_dialog import AuthDialog
from app.worker import PipelineWorker

TAIPEI = pytz.timezone("Asia/Taipei")


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("concat-e3v")
        self.resize(640, 640)

        self._settings = AppSettings()
        self._ffmpeg_bin = resolve_ffmpeg()
        self._worker: PipelineWorker | None = None

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        form = QFormLayout()
        layout.addLayout(form)

        self.src_edit = QLineEdit()
        src_btn = QPushButton("瀏覽...")
        src_btn.clicked.connect(lambda: self._pick_dir(self.src_edit))
        self.src_edit.textChanged.connect(self._save_src_dir)
        form.addRow("來源目錄:", self._row(self.src_edit, src_btn))

        self.dst_edit = QLineEdit()
        dst_btn = QPushButton("瀏覽...")
        dst_btn.clicked.connect(lambda: self._pick_dir(self.dst_edit))
        self.dst_edit.textChanged.connect(self._save_dst_dir)
        form.addRow("輸出目錄:", self._row(self.dst_edit, dst_btn))

        tz = QTimeZone(b"Asia/Taipei")
        now = QDateTime.currentDateTime()
        self.start_edit = QDateTimeEdit()
        self.start_edit.setTimeZone(tz)
        self.start_edit.setCalendarPopup(True)
        self.start_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.start_edit.setDateTime(QDateTime(now.date(), now.time()).addSecs(-now.time().second()))
        self.end_edit = QDateTimeEdit()
        self.end_edit.setTimeZone(tz)
        self.end_edit.setCalendarPopup(True)
        self.end_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.end_edit.setDateTime(
            QDateTime(now.date(), now.time()).addSecs(3600 - now.time().second())
        )
        form.addRow("開始時間:", self.start_edit)
        form.addRow("結束時間:", self.end_edit)

        self.merge_all_check = QCheckBox("合併成一個檔（忽略時間間隔，全部串成單一 mp4）")
        form.addRow(self.merge_all_check)

        mute_row = QHBoxLayout()
        self.mute_check = QCheckBox("靜音前")
        self.mute_spin = QSpinBox()
        self.mute_spin.setRange(0, 604800)
        self.mute_spin.setSuffix(" 秒")
        mute_row.addWidget(self.mute_check)
        mute_row.addWidget(self.mute_spin)
        mute_row.addStretch()
        form.addRow(mute_row)

        self.upload_group = QGroupBox("上傳到 YouTube")
        self.upload_group.setCheckable(True)
        up_layout = QFormLayout(self.upload_group)
        self.upload_title = QLineEdit()
        self.upload_title.setPlaceholderText("預設 = 檔名")
        up_layout.addRow("標題:", self.upload_title)
        self.upload_desc = QPlainTextEdit()
        self.upload_desc.setMaximumHeight(70)
        up_layout.addRow("描述:", self.upload_desc)
        self.upload_privacy = QComboBox()
        self.upload_privacy.addItem("私人 (private)", "private")
        self.upload_privacy.addItem("不公開 (unlisted)", "unlisted")
        self.upload_privacy.addItem("公開 (public)", "public")
        up_layout.addRow("隱私:", self.upload_privacy)
        self.upload_tags = QLineEdit()
        self.upload_tags.setPlaceholderText("逗號分隔，例如: dashcam, drive")
        up_layout.addRow("標籤:", self.upload_tags)
        self.upload_playlist = QLineEdit()
        up_layout.addRow("播放清單:", self.upload_playlist)
        self.cs_edit = QLineEdit()
        cs_btn = QPushButton("瀏覽...")
        cs_btn.clicked.connect(lambda: self._pick_file(self.cs_edit, "Client Secrets JSON (*.json)"))
        up_layout.addRow("Client Secrets:", self._row(self.cs_edit, cs_btn))
        layout.addWidget(self.upload_group)

        ffmpeg_label = QLabel(
            f"ffmpeg: {self._ffmpeg_bin or '找不到！請確認已安裝或已打包'}"
        )
        layout.addWidget(ffmpeg_label)

        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        layout.addWidget(self.log_edit, 1)

        self.start_btn = QPushButton("開始處理")
        self.start_btn.clicked.connect(self._on_start)
        layout.addWidget(self.start_btn)

        self._load_settings()

    def _row(self, edit: QLineEdit, btn: QPushButton) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(edit, 1)
        lay.addWidget(btn)
        return row

    def _pick_dir(self, edit: QLineEdit):
        path = QFileDialog.getExistingDirectory(self, "選擇目錄", edit.text())
        if path:
            edit.setText(path)

    def _pick_file(self, edit: QLineEdit, filter_: str):
        path, _ = QFileDialog.getOpenFileName(self, "選擇檔案", edit.text(), filter_)
        if path:
            edit.setText(path)

    def _load_settings(self):
        s = self._settings
        self.src_edit.setText(s.value("src_dir", ""))
        self.dst_edit.setText(s.value("dst_dir", ""))
        self.merge_all_check.setChecked(bool(s.value("merge_all", False)))
        self.mute_check.setChecked(int(s.value("mute_seconds", 0)) > 0)
        self.mute_spin.setValue(int(s.value("mute_seconds", 0)))
        self.upload_group.setChecked(bool(s.value("upload_enabled", False)))
        self.upload_title.setText(s.value("upload_title", ""))
        self.upload_desc.setPlainText(s.value("upload_description", ""))
        idx = self.upload_privacy.findData(s.value("upload_privacy", "private"))
        self.upload_privacy.setCurrentIndex(max(idx, 0))
        self.upload_tags.setText(s.value("upload_tags", ""))
        self.upload_playlist.setText(s.value("upload_playlist", ""))
        self.cs_edit.setText(s.value("client_secrets", ""))
        saved_start = s.value("start_time", "")
        if saved_start:
            self.start_edit.setDateTime(QDateTime.fromString(saved_start, Qt.ISODate))
        saved_end = s.value("end_time", "")
        if saved_end:
            self.end_edit.setDateTime(QDateTime.fromString(saved_end, Qt.ISODate))

    def _save_settings(self):
        s = self._settings
        s.set_value("src_dir", self.src_edit.text())
        s.set_value("dst_dir", self.dst_edit.text())
        s.set_value("merge_all", self.merge_all_check.isChecked())
        s.set_value("mute_seconds", self.mute_spin.value() if self.mute_check.isChecked() else 0)
        s.set_value("upload_enabled", self.upload_group.isChecked())
        s.set_value("upload_title", self.upload_title.text())
        s.set_value("upload_description", self.upload_desc.toPlainText())
        s.set_value("upload_privacy", self.upload_privacy.currentData())
        s.set_value("upload_tags", self.upload_tags.text())
        s.set_value("upload_playlist", self.upload_playlist.text())
        s.set_value("client_secrets", self.cs_edit.text())
        s.set_value("start_time", self.start_edit.dateTime().toString(Qt.ISODate))
        s.set_value("end_time", self.end_edit.dateTime().toString(Qt.ISODate))

    def _save_src_dir(self, _text):
        self._settings.set_value("src_dir", self.src_edit.text())

    def _save_dst_dir(self, _text):
        self._settings.set_value("dst_dir", self.dst_edit.text())

    def _validate(self) -> list[str]:
        errors = []
        src = self.src_edit.text().strip()
        dst = self.dst_edit.text().strip()
        if not src or not Path(src).is_dir():
            errors.append("來源目錄不存在")
        if not dst:
            errors.append("輸出目錄未填")
        start = self.start_edit.dateTime().toPython()
        end = self.end_edit.dateTime().toPython()
        if start >= end:
            errors.append("開始時間必須早於結束時間")
        if self._ffmpeg_bin is None:
            errors.append("找不到 ffmpeg")
        return errors

    def _build_cfg(self) -> PipelineConfig:
        tz = pytz.timezone("Asia/Taipei")
        start = self.start_edit.dateTime().toPython().astimezone(tz)
        end = self.end_edit.dateTime().toPython().astimezone(tz)
        return PipelineConfig(
            src_dir=self.src_edit.text().strip(),
            dst_dir=self.dst_edit.text().strip(),
            start_time=start,
            end_time=end,
            merge_all=self.merge_all_check.isChecked(),
            mute_seconds=self.mute_spin.value() if self.mute_check.isChecked() else 0,
            ffmpeg_bin=self._ffmpeg_bin or "ffmpeg",
            upload_enabled=self.upload_group.isChecked(),
            upload_title=self.upload_title.text().strip() or None,
            upload_description=self.upload_desc.toPlainText().strip() or None,
            upload_privacy=self.upload_privacy.currentData(),
            upload_tags=self.upload_tags.text().strip() or None,
            upload_playlist=self.upload_playlist.text().strip() or None,
            client_secrets=self.cs_edit.text().strip() or None,
        )

    def _on_start(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self.log_edit.appendPlainText("已送出停止要求...")
            return
        errors = self._validate()
        if errors:
            QMessageBox.warning(self, "輸入錯誤", "\n".join(errors))
            return
        self._save_settings()
        cfg = self._build_cfg()
        self.log_edit.clear()
        self.log_edit.appendPlainText("開始處理...")
        self._worker = PipelineWorker(cfg, parent=self)
        self._worker.log.connect(self.log_edit.appendPlainText)
        self._worker.finished.connect(self._on_finished)
        self._worker.auth_required.connect(self._on_auth_required)
        self._worker.auth_code_required.connect(self._on_auth_code_required)
        self.start_btn.setText("停止")
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
        self.start_btn.setText("開始處理")
        status = result.get("status")
        if status == "done":
            self.log_edit.appendPlainText("處理完成")
            uploaded = result.get("upload_results", [])
            for r in uploaded:
                if r.get("exit_code") == 0:
                    self.log_edit.appendPlainText(f"已上傳: {r.get('file')} -> {r.get('video_id')}")
                else:
                    self.log_edit.appendPlainText(f"上傳失敗: {r.get('file')} ({r.get('error')})")
            QMessageBox.information(self, "完成", "處理完成")
        elif status == "aborted":
            self.log_edit.appendPlainText(f"已中止: {result.get('reason')}")
        else:
            self.log_edit.appendPlainText(f"處理失敗: {result.get('reason')}")
            QMessageBox.critical(self, "失敗", str(result.get("reason")))
```

- [ ] **Step 4: 跑測試確認通過**

```bash
~/.pyenv/versions/e3v/bin/python -m pytest tests/test_gui_smoke.py -v
```

Expected: 全部 PASS。

- [ ] **Step 5: 手動驗證 GUI 啟動**

```bash
~/.pyenv/versions/e3v/bin/python app/main.py
```

Expected: 視窗開啟；選目錄、改時間、勾選合併/靜音/上傳面板皆正常；關閉無錯誤。以 `Front` 為來源、`Front/hokaido` 為輸出實測一次合併（不勾上傳）。

- [ ] **Step 6: Commit**

```bash
git add app/main.py app/ui/ tests/test_gui_smoke.py
git commit -m "feat: add PySide6 main window with auth dialog"
```

---

### Task 8: 打包（PyInstaller + 內建 ffmpeg）與文件

**Files:**
- Modify: `upload_mp4_to_youtube.py`（frozen 模式修正 vendored 路徑）
- Create: `build/app.spec`
- Create: `build/build_mac.sh`
- Create: `build/build_linux.sh`
- Create: `build/build_windows.bat`
- Modify: `README.md`

**Interfaces:**
- Consumes: Task 7 完成的 `app/main.py`、vendored `youtube-upload/`
- Produces: `dist/concat-e3v`（mac/linux 單一執行檔、windows `concat-e3v.exe`），內建 ffmpeg 與 `youtube-upload` 套件

- [ ] **Step 1: 修正 frozen 模式的路徑解析**

在 `upload_mp4_to_youtube.py` 修改 `_ensure_vendored_youtube_upload` 與新增 helper：

```python
def _vendored_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "youtube-upload"
    return YOUTUBE_UPLOAD_SRC


def _ensure_vendored_youtube_upload(
    parser: argparse.ArgumentParser,
) -> None:
    src = _vendored_root()
    if src.exists():
        sys.path.insert(0, src.as_posix())
    else:
        parser.error(
            f"Missing vendored folder: {src}"
        )
```

- [ ] **Step 2: 寫 build/app.spec**

```python
# -*- mode: python ; coding: utf-8 -*-
import os
import platform
import sys

plat = {"Darwin": "mac", "Linux": "linux", "Windows": "windows"}[platform.system()]
suffix = ".exe" if plat == "windows" else ""
ffmpeg = os.path.join("build", "bin", plat, f"ffmpeg{suffix}")
if not os.path.exists(ffmpeg):
    sys.exit(f"ffmpeg binary not found: {ffmpeg} — run the platform build script first")

a = Analysis(
    ["app/main.py"],
    pathex=[os.getcwd()],
    binaries=[(ffmpeg, ".")],
    datas=[("youtube-upload", "youtube-upload")],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="concat-e3v",
    debug=False,
    strip=False,
    upx=False,
    console=False,
)
```

- [ ] **Step 3: 寫 build/build_mac.sh**

```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLAT="mac"
BIN_DIR="$ROOT/build/bin/$PLAT"
FFMPEG="$BIN_DIR/ffmpeg"
mkdir -p "$BIN_DIR"

if [ ! -x "$FFMPEG" ]; then
  echo "下載 ffmpeg (macOS)..."
  ARCH="$(uname -m)"
  if [ "$ARCH" = "arm64" ]; then
    URL="https://evermeet.cx/ffmpeg/getrelease/arm64/zip"
  else
    URL="https://evermeet.cx/ffmpeg/getrelease/zip"
  fi
  curl -L -o /tmp/ffmpeg-mac.zip "$URL"
  unzip -o /tmp/ffmpeg-mac.zip -d "$BIN_DIR"
fi

PYTHON="${PYTHON:-$HOME/.pyenv/versions/e3v/bin/python}"
cd "$ROOT"
"$PYTHON" -m PyInstaller --noconfirm build/app.spec
echo "產物: $ROOT/dist/concat-e3v"
```

- [ ] **Step 4: 寫 build/build_linux.sh**

```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLAT="linux"
BIN_DIR="$ROOT/build/bin/$PLAT"
FFMPEG="$BIN_DIR/ffmpeg"
mkdir -p "$BIN_DIR"

if [ ! -x "$FFMPEG" ]; then
  echo "下載 ffmpeg (linux)..."
  ARCH="$(uname -m)"
  if [ "$ARCH" = "aarch64" ]; then
    URL="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz"
  else
    URL="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
  fi
  curl -L -o /tmp/ffmpeg-linux.tar.xz "$URL"
  tar -xJf /tmp/ffmpeg-linux.tar.xz -C /tmp
  find /tmp -maxdepth 2 -name ffmpeg -type f -exec cp {} "$FFMPEG" \;
  chmod +x "$FFMPEG"
fi

PYTHON="${PYTHON:-python3}"
cd "$ROOT"
"$PYTHON" -m PyInstaller --noconfirm build/app.spec
echo "產物: $ROOT/dist/concat-e3v"
```

- [ ] **Step 5: 寫 build/build_windows.bat**

```bat
@echo off
setlocal
set ROOT=%~dp0..
set BIN_DIR=%ROOT%\build\bin\windows
set FFMPEG=%BIN_DIR%\ffmpeg.exe
if not exist "%BIN_DIR%" mkdir "%BIN_DIR%"
if not exist "%FFMPEG%" (
  echo Downloading ffmpeg (windows)...
  powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile '%TEMP%\ffmpeg-win.zip'"
  powershell -NoProfile -Command "Expand-Archive -Path '%TEMP%\ffmpeg-win.zip' -DestinationPath '%TEMP%\ffmpeg-win-x' -Force"
  for /r "%TEMP%\ffmpeg-win-x" %%F in (ffmpeg.exe) do copy /y "%%F" "%FFMPEG%" >nul
)
cd /d "%ROOT%"
python -m PyInstaller --noconfirm build\app.spec
echo Build output: %ROOT%\dist\concat-e3v.exe
endlocal
```

- [ ] **Step 6: 本機實測 mac 打包**

```bash
chmod +x build/build_mac.sh && ./build/build_mac.sh
```

Expected: 下載 ffmpeg → PyInstaller 成功 → `dist/concat-e3v` 存在且可執行。

啟動驗證（背景跑 3 秒確認不崩潰）：

```bash
./dist/concat-e3v & sleep 3; kill %1 2>/dev/null; echo "launch ok"
```

- [ ] **Step 7: 更新 README.md**

在「How to use」之後新增段落：

```markdown
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
```

- [ ] **Step 8: Commit**

```bash
git add build/ upload_mp4_to_youtube.py README.md
git commit -m "build: add PyInstaller spec and per-platform build scripts with bundled ffmpeg"
```

---

## 完成驗證清單

- [ ] `pytest` 全綠（`~/.pyenv/versions/e3v/bin/python -m pytest tests/ -v`）
- [ ] `python app/main.py` 可開視窗、可完成一次合併（用 `Front` 目錄實測）
- [ ] `./dist/concat-e3v` 打包產物可啟動（本機 mac）
- [ ] 勾選上傳時：無憑證 → 彈授權對話框 → 貼 code → 通過後才開始合併