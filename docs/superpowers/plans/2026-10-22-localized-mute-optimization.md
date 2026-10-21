# 靜音局部重編（檔案前綴）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 勾選「靜音前 N 秒」時只重編覆蓋前 N 秒的檔案前綴音訊，其餘音訊與全部影片 stream copy；多個輸出群組的前綴重編並行、最後合併依序。

**Architecture:** `VideoProcessor` 先用內建 ffmpeg 讀檔頭取得每個 TS 的長度與音訊參數，選出覆蓋 N 秒的最短前綴；只對前綴重編音訊（精確 `lt(t,N)` 靜音、影片 copy），再與其餘原始 TS 以 concat demuxer `-c copy` 合併。前綴重編用 `ThreadPoolExecutor` 並行，合併依序。探測失敗、非 AAC LC、參數不一致或任何 ffmpeg 失敗時，該群組 fallback 回現有的整條音軌重編。

**Tech Stack:** Python 3.11+、ffmpeg（內建）、pytest、`concurrent.futures`（stdlib）

**Spec:** `docs/superpowers/specs/2026-10-22-localized-mute-optimization-design.md`

## Global Constraints

- 不新增第三方依賴；只使用 Python stdlib 與既有的 ffmpeg。
- 不打包 `ffprobe`；探測一律用 `self._ffmpeg_bin -hide_banner -i <file>`。
- `mute_seconds == 0` 的 `-c copy` 路徑行為不變。
- 輸出檔名規則不變：`%Y_%m_%dT%H:%M:%S_muted.mp4`（`mute_seconds > 0`）。
- `VideoProcessor.concat(cancel_event=None) -> list[str]` 簽章與「任一輸出失敗回傳 `[]`」語意不變。
- UI、`app/pipeline.py`、`app/worker.py` 不改。
- 既有測試必須維持通過；新測試用 pytest。
- 未經使用者明確要求不 commit（本計畫不含 commit 步驟）。

## Review Focus

- 來源音訊不是 AAC LC（HE-AAC、MP3、AC3 等）→ 必須走 fallback，不能產生壞檔或無聲輸出。
- `Duration` 為 `N/A` 或 TS 長度不準 → 不能低估前綴而少靜音；用 0.5 秒安全邊界與 fallback。
- N 跨多檔或 N ≥ 群組總長 → 前綴/剩餘切割與整組靜音必須正確。
- `merge_all=True` 且有時間 gap → 必須用實際累積長度，不能用牆鐘時間推估。
- 並行前綴期間取消 → 不能留下孤兒 ffmpeg，必須回傳 `[]`。
- 前綴 MP4 與原始 TS 合併的 AAC 接縫／影音同步 → 整合測試驗證，必要時 fallback。
- 空檔、損壞檔、單檔群組 → 探測失敗走 fallback；單檔群組直接輸出，不多做 concat。

---

## Prerequisites

目前工作區沒有 pytest 與 ffmpeg。先在暫存 venv 安裝最小依賴；沒有 ffmpeg 時整合測試會 skip，單元測試不需要 ffmpeg。

- [x] 建立測試 venv 並安裝最小依賴：

```bash
python3 -m venv /tmp/opencode/concat-e3v-venv
/tmp/opencode/concat-e3v-venv/bin/pip install pytest pytz python-dateutil
```

- [x] 跑現有 `tests/test_video_processor.py` 確認 baseline：

```bash
/tmp/opencode/concat-e3v-venv/bin/python -m pytest tests/test_video_processor.py -v
```

Expected: 既有 11 個測試 PASS（`ffmpeg` 不存在不影響這些 fake Popen 測試）。

- [x] 之後每個 task 都用 `/tmp/opencode/concat-e3v-venv/bin/python -m pytest`；完整套件需要 PySide6/Google 依賴，於 Task 7 再安裝 `requirements.txt` + `requirements-dev.txt`。

---

### Task 1: 解析 ffmpeg 檔頭（AudioInfo / _parse_ffmpeg_info）

**Files:**
- Modify: `e3vvid/video_processor.py`
- Test: `tests/test_video_processor.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class AudioInfo(codec: str, profile: str | None, sample_rate: int, channels: int)`，具 `is_supported: bool` 與 `compatible(other: AudioInfo) -> bool`。
  - `_parse_ffmpeg_info(stderr: str) -> tuple[float | None, AudioInfo | None]`。
- Consumes: 無。

- [x] **Step 1: 寫失敗測試**

在測試檔 import 加入 `AudioInfo, _parse_ffmpeg_info`，新增 4 個測試：

```python
def test_parse_ffmpeg_info_lc_aac():
    stderr = (
        "  Duration: 00:01:00.00, start: 1.400000\n"
        "  Stream #0:1[0x101]: Audio: aac (LC) ([15][0][0][0] / 0x000F), "
        "48000 Hz, stereo, fltp, 128 kb/s\n"
    )
    duration, audio = _parse_ffmpeg_info(stderr)
    assert duration == 60.0
    assert audio == AudioInfo("aac", "LC", 48000, 2)
    assert audio.is_supported

def test_parse_ffmpeg_info_unavailable_and_non_aac():
    stderr = (
        "  Duration: N/A, start: 0.000000\n"
        "  Stream #0:1: Audio: mp3, 44100 Hz, stereo, fltp, 128 kb/s\n"
    )
    duration, audio = _parse_ffmpeg_info(stderr)
    assert duration is None
    assert audio == AudioInfo("mp3", None, 44100, 2)
    assert not audio.is_supported

def test_parse_ffmpeg_info_he_aac_not_supported():
    stderr = "  Duration: 00:00:10.00\n  Stream #0:1: Audio: aac (HE-AAC), 48000 Hz, stereo\n"
    _, audio = _parse_ffmpeg_info(stderr)
    assert audio is not None
    assert not audio.is_supported

def test_parse_ffmpeg_info_unknown_channels_returns_none_audio():
    stderr = "  Duration: 00:00:10.00\n  Stream #0:1: Audio: aac (LC), 48000 Hz, 5.1(side)\n"
    duration, audio = _parse_ffmpeg_info(stderr)
    assert duration == 10.0
    assert audio is None
```

- [x] **Step 2: 跑測試確認失敗**

Run: `/tmp/opencode/concat-e3v-venv/bin/python -m pytest tests/test_video_processor.py -k parse_ffmpeg_info -v`

Expected: FAIL（ImportError: `AudioInfo`）。

- [x] **Step 3: 實作**

在 `e3vvid/video_processor.py` 頂端加 `import re`、`from dataclasses import dataclass`，class 外定義：

- `AudioInfo`：`is_supported` 回傳 `codec == "aac" and profile in (None, "LC")`；`compatible` 要求雙方 `is_supported` 且 `sample_rate`、`channels` 相同。
- `_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")`。
- `_AUDIO_RE = re.compile(r"Audio:\s*([A-Za-z0-9_]+)(?:\s*\(([^)]+)\))?(?:\s*\([^)]*\))?,\s*(\d+)\s*Hz,\s*([^,]+)")`。
- `_parse_ffmpeg_info`：抓第一個 Duration（換秒；`N/A` → None）與第一個 Audio；profile 轉大寫；`mono`/`stereo` → 1/2，`(\d+) channels` 也接受，其餘 channels 回傳 `(duration, None)`。

第二個 optional parenthesis 用來吃掉 `aac (LC) ([15][0][0][0] / 0x000F)` 這類 codec tag。

- [x] **Step 4: 跑測試確認通過**

Run: `/tmp/opencode/concat-e3v-venv/bin/python -m pytest tests/test_video_processor.py -k parse_ffmpeg_info -v`

Expected: 4 passed。

---

### Task 2: 探測與前綴規劃（GroupPlan / _plan_group）

**Files:**
- Modify: `e3vvid/video_processor.py`
- Test: `tests/test_video_processor.py`

**Interfaces:**
- Produces:
  - `@dataclass class GroupPlan(index: int, lines: list[str], output_name: str, prefix_lines: list[str], rest_lines: list[str], audio: AudioInfo | None, use_fast_path: bool, prefix_ok: bool = True, prefix_out: str = "")`
  - `VideoProcessor._probe_media(path: str) -> tuple[float | None, AudioInfo | None]`
  - `VideoProcessor._line_to_path(line: str) -> str`（staticmethod；去掉 `file '` 與結尾 `'`）
  - `VideoProcessor._plan_group(index: int, lines: list[str], cancel_event: Event | None = None) -> GroupPlan | None`
- Consumes: Task 1 的 `AudioInfo`、`_parse_ffmpeg_info`。

行為：
- `output_name` 由 `lines[0]` 的檔名時間戳產生，固定加 `_muted.mp4`。
- 依序 `_probe_media` 每個檔案，累積 `duration`；累積 `>= mute_seconds + 0.5` 即停止，前綴至少 1 檔。
- 第一個檔案的 `AudioInfo` 必須 `is_supported`；剩餘檔案非空時，再探測剩餘第一個檔案，必須 `audio.compatible(rest_audio)`。
- 任何探測失敗、非 AAC LC、參數不一致 → `use_fast_path=False`（仍回傳 GroupPlan，`prefix_lines` 至少第一檔）。
- `cancel_event` 已設置 → 回傳 `None`。

- [x] **Step 1: 寫失敗測試**

在測試檔 import 加入 `GroupPlan`。用 `AUDIO_48K = AudioInfo("aac", "LC", 48000, 2)`；用 `monkeypatch.setattr(proc, "_probe_media", fake_probe)`，`fake_probe` 依序回傳給定的 `(duration, audio)`。新增：

| 測試 | 檔案數 / N | 期望 |
|---|---|---|
| `test_plan_group_prefix_within_first_file` | 2 檔，N=10，各 60s | fast path；prefix 1、rest 1；`output_name == "2026_08_25T00:00:00_muted.mp4"` |
| `test_plan_group_prefix_spans_files` | 3 檔，N=70，各 60s | prefix 2、rest 1 |
| `test_plan_group_mutes_whole_group` | 2 檔，N=200，各 60s | prefix 2、rest 0 |
| `test_plan_group_uses_cumulative_durations_for_merge_all_gaps` | 3 檔（00:00/00:01/00:05），merge_all，N=70 | prefix 2、rest 1（不可用牆鐘 gap 推估） |
| `test_plan_group_falls_back_on_probe_failure` | 第一檔回 `(None, None)` | `not use_fast_path` |
| `test_plan_group_falls_back_on_non_aac` | 第一檔 `AudioInfo("mp3", None, 44100, 2)` | `not use_fast_path` |
| `test_plan_group_falls_back_on_rest_param_mismatch` | rest 為 44100/2 | `not use_fast_path` |
| `test_plan_group_profile_none_and_lc_are_compatible` | prefix profile None、rest LC | `use_fast_path` |
| `test_plan_group_cancel_returns_none` | cancel 已設置 | `is None` |

- [x] **Step 2: 跑測試確認失敗**

Run: `/tmp/opencode/concat-e3v-venv/bin/python -m pytest tests/test_video_processor.py -k plan_group -v`

Expected: FAIL（`GroupPlan` / `_plan_group` 不存在）。

- [x] **Step 3: 實作**

- `_probe_media`：`Popen([self._ffmpeg_bin, "-hide_banner", "-i", path], stdout=PIPE, stderr=PIPE, text=True)`，`communicate()` 後把 stderr 交給 `_parse_ffmpeg_info`；忽略 return code。
- `_line_to_path`：`text = line.strip()`；若 `text.startswith("file '") and text.endswith("'")` 回傳 `text[6:-1]`，否則回傳 `text`。
- `_plan_group`：`threshold = self._mute_seconds + 0.5`；累積到門檻為止；`prefix_count = max(1, prefix_count)`；`rest_lines` 非空時探測 `paths[prefix_count]`；`audio is None` 時不可呼叫 `.compatible`。

- [x] **Step 4: 跑測試確認通過**

Run: `/tmp/opencode/concat-e3v-venv/bin/python -m pytest tests/test_video_processor.py -k plan_group -v`

Expected: 9 passed。

### Task 3: 指令建構（_build_prefix_cmd / _build_final_concat_cmd）

**Files:**
- Modify: `e3vvid/video_processor.py`
- Test: `tests/test_video_processor.py`

**Interfaces:**
- Produces:
  - `VideoProcessor._build_prefix_cmd(videolist: str, out_path: str, audio: AudioInfo) -> list[str]`
  - `VideoProcessor._build_final_concat_cmd(videolist: str, out_path: str) -> list[str]`
- Consumes: Task 1 的 `AudioInfo`。

- [x] **Step 1: 寫失敗測試**

```python
def test_build_prefix_cmd_uses_stream_copy_and_matching_audio(tmp_path):
    proc = make_processor(tmp_path, ["20260825000000_1.ts"], mute_seconds=10)
    cmd = proc._build_prefix_cmd(
        "/tmp/prefix.txt", "/tmp/prefix0.mp4", AudioInfo("aac", "LC", 48000, 2)
    )
    assert cmd[0] == "ffmpeg"
    assert cmd[cmd.index("-c:v") + 1] == "copy"
    assert "volume=0.0:enable='lt(t,10)'" in cmd
    assert cmd[cmd.index("-c:a") + 1] == "aac"
    assert cmd[cmd.index("-ar") + 1] == "48000"
    assert cmd[cmd.index("-ac") + 1] == "2"
    assert cmd[cmd.index("-profile:a") + 1] == "aac_low"
    assert cmd[-1] == "/tmp/prefix0.mp4"

def test_build_final_concat_cmd_uses_stream_copy(tmp_path):
    proc = make_processor(tmp_path, ["20260825000000_1.ts"], mute_seconds=10)
    cmd = proc._build_final_concat_cmd("/tmp/final.txt", "/tmp/out.mp4")
    assert cmd[cmd.index("-i") + 1] == "/tmp/final.txt"
    assert cmd[cmd.index("-c") + 1] == "copy"
    assert cmd[-1] == "/tmp/out.mp4"
```

- [x] **Step 2: 跑測試確認失敗**

Run: `/tmp/opencode/concat-e3v-venv/bin/python -m pytest tests/test_video_processor.py -k build_ -v`

Expected: FAIL（方法不存在）。

- [x] **Step 3: 實作**

- `_build_prefix_cmd` 回傳 `[ffmpeg_bin, "-y", "-f", "concat", "-safe", "0", "-i", videolist, "-c:v", "copy", "-af", f"volume=0.0:enable='lt(t,{self._mute_seconds})'", "-c:a", "aac", "-ar", str(audio.sample_rate), "-ac", str(audio.channels), "-profile:a", "aac_low", out_path]`。
- `_build_final_concat_cmd` 回傳 `[ffmpeg_bin, "-y", "-f", "concat", "-safe", "0", "-i", videolist, "-c", "copy", out_path]`。
- 既有 `_build_concat_cmd` 不動（no-mute 與 fallback 使用）。

- [x] **Step 4: 跑測試確認通過**

Run: `/tmp/opencode/concat-e3v-venv/bin/python -m pytest tests/test_video_processor.py -k build_ -v`

Expected: 2 passed。

---

### Task 4: 共用 ffmpeg 執行器與 no-mute 路徑重構（_run_ffmpeg / _concat_copy）

**Files:**
- Modify: `e3vvid/video_processor.py`
- Test: `tests/test_video_processor.py`

**Interfaces:**
- Produces:
  - `VideoProcessor._run_ffmpeg(cmd: list[str], cancel_event: Event | None = None) -> tuple[int, str, str]`（returncode, stdout, stderr）
  - `VideoProcessor._concat_copy(video_list: list[list[str]], dst: Path, cancel_event: Event | None) -> list[str]`
- Consumes: 既有 `_build_concat_cmd`、`convert_filename_to_datetime`。

- [x] **Step 1: 寫失敗測試**

```python
def test_run_ffmpeg_returns_result(tmp_path, monkeypatch):
    monkeypatch.setattr("e3vvid.video_processor.Popen", _FakePopen)
    proc = make_processor(tmp_path, ["20260825000000_1.ts"])
    assert proc._run_ffmpeg(["ffmpeg", "-version"]) == (0, "", "")

def test_run_ffmpeg_cancel_kills_and_drains(tmp_path, monkeypatch):
    import time as _time
    instances = []

    class HangingPopen(_FakePopen):
        def __init__(self, cmd, stdout=None, stderr=None, text=False):
            super().__init__(cmd, stdout, stderr, text)
            self.killed = False
            self.communicated = False
            instances.append(self)

        def poll(self):
            return None if not self.killed else -9

        def kill(self):
            self.killed = True

        def communicate(self):
            self.communicated = True
            if self.killed:
                self.returncode = -9
            return "", "killed"

    monkeypatch.setattr("e3vvid.video_processor.Popen", HangingPopen)
    proc = make_processor(tmp_path, ["20260825000000_1.ts"])
    cancel = threading.Event()
    t = threading.Thread(target=lambda: (_time.sleep(0.2), cancel.set()))
    t.start()
    rc, _, _ = proc._run_ffmpeg(["ffmpeg", "-i", "x"], cancel)
    t.join()
    assert rc == -9
    assert instances[0].killed
    assert instances[0].communicated
```

- [x] **Step 2: 跑測試確認失敗**

Run: `/tmp/opencode/concat-e3v-venv/bin/python -m pytest tests/test_video_processor.py -k run_ffmpeg -v`

Expected: FAIL（`_run_ffmpeg` 不存在）。

- [x] **Step 3: 實作**

- `_run_ffmpeg`：若 `cancel_event` 已設置 → `(-9, "", "cancelled")`；否則 `logging.info(cmd)`、`Popen`、需要時每 0.1 秒 poll 並在取消時 `kill()`，最後 `communicate()` 回傳 tuple。
- 把 `concat()` 的 no-mute 迴圈抽成 `_concat_copy`：建立 `videolist{i}.txt`、用 `_build_concat_cmd`、呼叫 `_run_ffmpeg`；`rc != 0` → `print("處理失敗:", err)` + `return []`；成功 append 檔名；取消 → `[]`。檔名沿用現有邏輯：`mute_seconds > 0` 時加 `_muted` 後綴，且用 `_line_to_path(v[0])` 取時間戳。
- `concat()`：`mute_seconds == 0` → `_concat_copy`；`> 0` 暫時也走 `_concat_copy`（`_build_concat_cmd` 仍會加靜音 filter，維持舊行為），Task 5 再切到 `_concat_muted`。

- [x] **Step 4: 跑測試**

Run: `/tmp/opencode/concat-e3v-venv/bin/python -m pytest tests/test_video_processor.py -v`

Expected: 全部 PASS（含既有 11 個）。

---

### Task 5: 靜音快速路徑與 fallback（_concat_muted，先依序）

**Files:**
- Modify: `e3vvid/video_processor.py`
- Test: `tests/test_video_processor.py`

**Interfaces:**
- Produces: `VideoProcessor._concat_muted(video_list: list[list[str]], dst: Path, cancel_event: Event | None) -> list[str]`
- Consumes: Task 2 的 `_plan_group`/`GroupPlan`、Task 3 的 builders、Task 4 的 `_run_ffmpeg`、既有 `_build_concat_cmd` 作為 fallback。

行為：
- 先為所有群組建立 `GroupPlan`；取消 → `[]`。
- 快速路徑可行：建 prefix list、prefix 輸出路徑（有剩餘 → `tmpdir/prefix{i}.mp4`；無剩餘 → `dst/output_name`）、執行 `_build_prefix_cmd`。
- 前綴失敗 → `prefix_ok=False`，稍後 fallback。
- 有剩餘：建 final list（prefix 輸出路徑 + 剩餘原始 lines），執行 `_build_final_concat_cmd`；失敗 → fallback。
- 無剩餘：直接把 `output_name` 加入結果（prefix 已寫入最終路徑）。
- Fallback：用整組 lines 建 videolist，執行 `_build_concat_cmd`；失敗 → `[]`。
- 此 task 的前綴先依序執行（for loop）；Task 6 改成 ThreadPoolExecutor。

- [x] **Step 1: 寫失敗測試**

用捕獲指令與 list 內容的 fake Popen：

```python
class CapturingPopen(_FakePopen):
    captured = []
    lists = {}
    fail_prefix = False
    fail_final = False

    def __init__(self, cmd, stdout=None, stderr=None, text=False):
        super().__init__(cmd, stdout, stderr, text)
        type(self).captured.append(list(cmd))
        p = Path(cmd[cmd.index("-i") + 1])
        if p.exists():
            type(self).lists[p.name] = p.read_text()
        out = Path(cmd[-1]).name
        if type(self).fail_prefix and out.startswith("prefix"):
            self.returncode = 1
        if type(self).fail_final and "final" in p.name:
            self.returncode = 1

def _muted_fast_proc(tmp_path, monkeypatch, names, mute_seconds=10):
    proc = make_processor(tmp_path, names, mute_seconds=mute_seconds)
    monkeypatch.setattr(proc, "_probe_media", lambda p: (60.0, AUDIO_48K))
    return proc

def test_concat_muted_fast_path_runs_prefix_then_final(tmp_path, monkeypatch):
    proc = _muted_fast_proc(tmp_path, monkeypatch,
        ["20260825000000_1.ts", "20260825000100_2.ts"])
    monkeypatch.setattr("e3vvid.video_processor.Popen", CapturingPopen)
    CapturingPopen.captured, CapturingPopen.lists = [], {}
    CapturingPopen.fail_prefix, CapturingPopen.fail_final = False, False
    assert proc.concat() == ["2026_08_25T00:00:00_muted.mp4"]
    assert len(CapturingPopen.captured) == 2
    prefix_cmd, final_cmd = CapturingPopen.captured
    assert "volume=0.0:enable='lt(t,10)'" in prefix_cmd
    assert prefix_cmd[prefix_cmd.index("-c:v") + 1] == "copy"
    assert final_cmd[final_cmd.index("-c") + 1] == "copy"
    assert len(CapturingPopen.lists["prefix0.txt"].splitlines()) == 1
    final_lines = CapturingPopen.lists["final0.txt"].splitlines()
    assert len(final_lines) == 2 and "prefix0.mp4" in final_lines[0]

def test_concat_muted_single_file_writes_directly(tmp_path, monkeypatch):
    proc = _muted_fast_proc(tmp_path, monkeypatch, ["20260825000000_1.ts"])
    monkeypatch.setattr("e3vvid.video_processor.Popen", CapturingPopen)
    CapturingPopen.captured, CapturingPopen.lists = [], {}
    CapturingPopen.fail_prefix, CapturingPopen.fail_final = False, False
    assert proc.concat() == ["2026_08_25T00:00:00_muted.mp4"]
    assert len(CapturingPopen.captured) == 1
    assert CapturingPopen.captured[0][-1].endswith("2026_08_25T00:00:00_muted.mp4")

def test_concat_muted_prefix_failure_falls_back(tmp_path, monkeypatch):
    proc = _muted_fast_proc(tmp_path, monkeypatch,
        ["20260825000000_1.ts", "20260825000100_2.ts"])
    monkeypatch.setattr("e3vvid.video_processor.Popen", CapturingPopen)
    CapturingPopen.captured, CapturingPopen.lists = [], {}
    CapturingPopen.fail_prefix, CapturingPopen.fail_final = True, False
    assert proc.concat() == ["2026_08_25T00:00:00_muted.mp4"]
    assert len(CapturingPopen.captured) == 2  # prefix(fail) + fallback
    assert len(CapturingPopen.lists["videolist0.txt"].splitlines()) == 2

def test_concat_muted_final_concat_failure_falls_back(tmp_path, monkeypatch):
    proc = _muted_fast_proc(tmp_path, monkeypatch,
        ["20260825000000_1.ts", "20260825000100_2.ts"])
    monkeypatch.setattr("e3vvid.video_processor.Popen", CapturingPopen)
    CapturingPopen.captured, CapturingPopen.lists = [], {}
    CapturingPopen.fail_prefix, CapturingPopen.fail_final = False, True
    assert proc.concat() == ["2026_08_25T00:00:00_muted.mp4"]
    assert len(CapturingPopen.captured) == 3  # prefix + final(fail) + fallback
    assert len(CapturingPopen.lists["videolist0.txt"].splitlines()) == 2

def test_concat_muted_cancel_before_start_returns_empty(tmp_path, monkeypatch):
    proc = _muted_fast_proc(tmp_path, monkeypatch, ["20260825000000_1.ts"])
    cancel = threading.Event()
    cancel.set()
    monkeypatch.setattr("e3vvid.video_processor.Popen", CapturingPopen)
    CapturingPopen.captured = []
    assert proc.concat(cancel_event=cancel) == []
    assert CapturingPopen.captured == []
```

- [x] **Step 2: 跑測試確認失敗**

Run: `/tmp/opencode/concat-e3v-venv/bin/python -m pytest tests/test_video_processor.py -k muted -v`

Expected: FAIL（`_concat_muted` 不存在或仍走整條重編）。

- [x] **Step 3: 實作**

- `concat()`：`mute_seconds > 0` → `_concat_muted`；`== 0` → `_concat_copy`。
- `_concat_muted`：`tempfile.TemporaryDirectory()` 包住整段；prefix list 用 `"".join(plan.prefix_lines)`；final list 先寫 `file '<prefix_out>'\n` 再 `writelines(rest_lines)`；fallback list 用 `writelines(plan.lines)`。
- 取消檢查點：建立 plans 前、每個 group 前、每個 ffmpeg 呼叫後；取消 → `[]`，且不執行 fallback。
- 失敗處理：前綴失敗只標記 `prefix_ok=False`；final 失敗直接走 fallback；fallback 失敗 `print("處理失敗:", err)` + `return []`。

- [x] **Step 4: 跑測試**

Run: `/tmp/opencode/concat-e3v-venv/bin/python -m pytest tests/test_video_processor.py -v`

Expected: 全部 PASS（含 `test_concat_returns_muted_name`：空檔探測失敗 → fallback）。

### Task 6: 前綴平行化（ThreadPoolExecutor）

**Files:**
- Modify: `e3vvid/video_processor.py`
- Test: `tests/test_video_processor.py`

**Interfaces:**
- Consumes: Task 5 的 `_concat_muted`、Task 4 的 `_run_ffmpeg`。
- Produces: 無新公開介面；`_concat_muted` 的 phase 1 改為並行。

行為：
- 先建立所有 plans、prefix list、prefix 指令。
- `workers = max(1, min(4, os.cpu_count() or 1))`；用 `ThreadPoolExecutor` + `as_completed` 執行所有快速路徑的前綴。
- 每個 future 失敗（rc != 0 或 exception）→ `plan.prefix_ok = False`，繼續其他 plan。
- phase 1 結束後若取消 → `[]`。
- phase 2 依 `plans` 原始順序執行 final concat / fallback。

- [x] **Step 1: 寫失敗測試**

```python
def test_concat_muted_prefixes_run_in_parallel(tmp_path, monkeypatch):
    names = [
        "20260825000000_1.ts", "20260825000100_2.ts",
        "20260825000500_3.ts", "20260825000600_4.ts",
    ]
    proc = make_processor(tmp_path, names, mute_seconds=10)
    monkeypatch.setattr(proc, "_probe_media", lambda p: (60.0, AUDIO_48K))
    monkeypatch.setattr("e3vvid.video_processor.os.cpu_count", lambda: 4)
    calls = []
    barrier = threading.Barrier(2, timeout=5)

    def fake_run(cmd, cancel_event=None):
        if any(str(c).endswith(("prefix0.mp4", "prefix1.mp4")) for c in cmd):
            calls.append("prefix")
            barrier.wait()
        else:
            calls.append("other")
        return 0, "", ""

    monkeypatch.setattr(proc, "_run_ffmpeg", fake_run)
    assert proc.concat() == [
        "2026_08_25T00:00:00_muted.mp4", "2026_08_25T00:05:00_muted.mp4",
    ]
    assert calls.count("prefix") == 2
    assert calls[:2] == ["prefix", "prefix"]

def test_concat_muted_cancel_during_prefix_returns_empty(tmp_path, monkeypatch):
    names = ["20260825000000_1.ts", "20260825000100_2.ts"]
    proc = _muted_fast_proc(tmp_path, monkeypatch, names)
    cancel = threading.Event()

    def fake_run(cmd, cancel_event=None):
        cancel.set()
        return 0, "", ""

    monkeypatch.setattr(proc, "_run_ffmpeg", fake_run)
    assert proc.concat(cancel_event=cancel) == []
```

- [x] **Step 2: 跑測試確認失敗**

Run: `/tmp/opencode/concat-e3v-venv/bin/python -m pytest tests/test_video_processor.py -k "parallel or cancel_during" -v`

Expected: FAIL（前綴仍依序；barrier 逾時或 fallback）。

- [x] **Step 3: 實作**

- 把 Task 5 的 prefix for-loop 換成：先建好每個 fast plan 的 prefix list 與指令，放進 `[(plan, cmd)]`；用 `ThreadPoolExecutor(max_workers=workers)` 提交 `self._run_ffmpeg, cmd, cancel_event`；用 `as_completed` 收集，exception/rc != 0 → `logging.error(...)` + `plan.prefix_ok = False`。
- `with` 區塊結束後再檢查 `cancel_event`；phase 2 完全不變。
- import `os`、`from concurrent.futures import ThreadPoolExecutor, as_completed`。

- [x] **Step 4: 跑測試**

Run: `/tmp/opencode/concat-e3v-venv/bin/python -m pytest tests/test_video_processor.py -v`

Expected: 全部 PASS。

---

### Task 7: 整合測試與完整套件驗證

**Files:**
- Test: `tests/test_video_processor.py`（新增 integration test）
- 不改產品程式碼（除非整合測試揭露 bug；那時回到對應 task 修正）。

- [x] **Step 1: 寫整合測試（沒有 ffmpeg/ffprobe 時 skip）**

```python
import re
import shutil
import subprocess

def _ffmpeg_volume(path, ss):
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-ss", str(ss), "-t", "0.2",
         "-i", str(path), "-vn", "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", r.stderr)
    return float(m.group(1))

@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not available",
)
def test_concat_muted_integration(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    for minute in range(3):
        name = f"2026082500{minute:02d}00_1.ts"
        subprocess.run(
            ["ffmpeg", "-y",
             "-f", "lavfi", "-i", "testsrc=duration=2:size=160x120:rate=10",
             "-f", "lavfi", "-i", "sine=frequency=1000:duration=2",
             "-c:v", "libx264", "-preset", "ultrafast",
             "-c:a", "aac", "-ar", "48000", "-ac", "1",
             str(src / name)],
            check=True, capture_output=True,
        )
    proc = VideoProcessor(
        str(src), str(tmp_path / "dst"),
        datetime(2026, 8, 25, 0, 0, 0).astimezone(TAIPEI),
        datetime(2026, 8, 25, 0, 5, 0).astimezone(TAIPEI),
        mute_seconds=1,
    )
    assert proc.concat() == ["2026_08_25T00:00:00_muted.mp4"]
    out = tmp_path / "dst" / "2026_08_25T00:00:00_muted.mp4"

    assert _ffmpeg_volume(out, 0.5) < -70
    assert _ffmpeg_volume(out, 1.5) > -50

    def stream_duration(kind):
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", f"{kind}:0",
             "-show_entries", "stream=duration", "-of", "default=nw=1:nk=1",
             str(out)],
            capture_output=True, text=True,
        )
        return float(r.stdout.strip())

    assert abs(stream_duration("v") - stream_duration("a")) <= 0.25
```

- [x] **Step 2: 跑整合測試**

Run: `/tmp/opencode/concat-e3v-venv/bin/python -m pytest tests/test_video_processor.py -k integration -v`

Expected: 有 ffmpeg/ffprobe → PASS；沒有 → SKIPPED。

- [x] **Step 3: 跑完整套件**

安裝完整依賴（PySide6/Google/測試工具）：

```bash
/tmp/opencode/concat-e3v-venv/bin/pip install -r requirements.txt -r requirements-dev.txt
/tmp/opencode/concat-e3v-venv/bin/python -m pytest
```

Expected: 全部 PASS（既有 98 個 + 新增測試）。若 GUI 測試因無顯示環境失敗，設定 `QT_QPA_PLATFORM=offscreen` 後重跑。若 Python 3.14 無法安裝 `requirements.txt`（例如 `cryptography==42.0.8` 無 wheel），改用專案支援的 Python 3.11（`.python-version` 指定的 `e3v`）建立 venv，並在回報中註明；至少 `tests/test_video_processor.py` 必須全過。

- [x] **Step 4: 驗證 diff 與行為**

```bash
git diff --stat -- e3vvid/video_processor.py tests/test_video_processor.py
git diff -- e3vvid/video_processor.py tests/test_video_processor.py
```

確認：
- `mute_seconds == 0` 的指令與輸出檔名不變。
- `mute_seconds > 0` 的快速路徑有 `-c:v copy`、`lt(t,N)`、`-c:a aac`、`-ar`、`-ac`。
- fallback 指令與原本的 `_build_concat_cmd` 一致。
- 沒有動到 UI / pipeline / worker。

---

## Self-Review

- **Spec coverage:** 探測（Task 1-2）、前綴選擇（Task 2）、前綴/合併指令（Task 3）、取消與共用 runner（Task 4）、快速路徑與 fallback（Task 5）、並行（Task 6）、整合與 A/V 驗證（Task 7）。無 UI/pipeline 變更。
- **Type consistency:** `AudioInfo`、`GroupPlan`、`_plan_group`、`_build_prefix_cmd`、`_build_final_concat_cmd`、`_run_ffmpeg`、`_concat_copy`、`_concat_muted` 在各 task 使用一致名稱與簽章。
- **Review Focus tests:** 非 AAC/HE-AAC（Task 1-2）、Duration N/A（Task 1-2）、N 跨檔/整組（Task 2）、merge_all gap（Task 2）、並行取消（Task 6）、前綴/合併失敗 fallback（Task 5）、接縫與同步（Task 7）、空檔/單檔（Task 2、5）。
- **Proportion:** 本計畫以介面、測試名稱/斷言與關鍵決策為主，未逐行轉錄實作。
- **Commit:** 依 Global Constraints，未包含 commit 步驟。

## Post-Review Fixes (2026-10-22)

Final review with real ffmpeg found that mixing an MP4 prefix with the remaining TS
files corrupts the audio time base (video 6.048s vs audio 11.411s) and skips
ADTS→raw AAC conversion. Fixes applied and verified:

- Temporary prefix output is `.ts` whenever `rest_lines` exists; no-rest groups still
  write the final MP4 directly.
- `_build_final_concat_cmd` adds `-bsf:a aac_adtstoasc`.
- `_plan_group` probes **every** rest file's audio parameters, not just the first.
- Parallel test now asserts the barrier actually succeeded, so it fails under
  sequential execution.
- Integration test checks post-seam audio at 2.5s/5.5s and full decode for
  `aac bitstream error`; datetimes use `TAIPEI.localize`.
- `convert_filename_to_datetime` interprets filenames in the configured timezone
  (`pytz.localize`, with a generic `tzinfo` fallback) so tests and output names do
  not depend on the host timezone.
- Final verification: `PATH=/tmp/opencode/btbn/bin:$PATH QT_QPA_PLATFORM=offscreen
  /tmp/opencode/concat-e3v-venv/bin/python -m pytest -q` → 125 passed;
  `TZ=UTC ... pytest -q` → 124 passed, 1 skipped (no ffmpeg on PATH).

