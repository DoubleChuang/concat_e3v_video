from datetime import datetime, timedelta
import threading
import pytz
import pytest
from e3vvid.video_processor import VideoProcessor

TAIPEI = pytz.timezone("Asia/Taipei")


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