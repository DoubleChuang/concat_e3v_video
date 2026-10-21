import os
from datetime import datetime, timedelta
from pathlib import Path
import re
import shutil
import subprocess
import threading
import pytz
import pytest
from e3vvid.video_processor import (
    AudioInfo,
    VideoProcessor,
    _parse_ffmpeg_info,
)

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
        TAIPEI.localize(datetime(2026, 8, 25, 0, 0, 0)),
        TAIPEI.localize(datetime(2026, 8, 25, 2, 0, 0)),
        merge_all=merge_all, mute_seconds=mute_seconds, ffmpeg_bin=ffmpeg_bin,
    )


def test_convert_filename_to_datetime_uses_configured_timezone(tmp_path):
    proc = make_processor(tmp_path, ["20260825000000_1.ts"])
    dt = proc.convert_filename_to_datetime("20260825000000_1.ts")
    assert dt.hour == 0
    assert dt.utcoffset() == timedelta(hours=8)


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


def test_concat_cancel_kills_and_drains(tmp_path, monkeypatch):
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
            return "", "killed stderr"

    monkeypatch.setattr("e3vvid.video_processor.Popen", HangingPopen)
    proc = make_processor(
        tmp_path,
        ["20260825000000_1.ts", "20260825000100_2.ts"],
    )
    cancel = threading.Event()

    def set_cancel():
        _time.sleep(0.2)
        cancel.set()

    t = threading.Thread(target=set_cancel)
    t.start()
    names = proc.concat(cancel_event=cancel)
    t.join()
    assert names == []
    assert len(instances) == 1  # second segment never started
    assert instances[0].killed
    assert instances[0].communicated


def test_concat_works_with_read_only_cwd(tmp_path, monkeypatch):
    proc = make_processor(tmp_path, ["20260825000000_1.ts"])
    ro_dir = tmp_path / "ro"
    ro_dir.mkdir()
    monkeypatch.chdir(ro_dir)
    monkeypatch.setattr("e3vvid.video_processor.Popen", _FakePopen)
    try:
        os.chmod(ro_dir, 0o500)
        names = proc.concat()
    finally:
        os.chmod(ro_dir, 0o700)
    assert names == ["2026_08_25T00:00:00.mp4"]
    assert list(ro_dir.glob("videolist*.txt")) == []


def test_concat_videolist_is_outside_cwd_with_abs_paths(tmp_path, monkeypatch):
    captured = {}

    class CapturingPopen(_FakePopen):
        def __init__(self, cmd, stdout=None, stderr=None, text=False):
            super().__init__(cmd, stdout, stderr, text)
            captured["videolist"] = Path(cmd[cmd.index("-i") + 1])

    proc = make_processor(tmp_path, ["20260825000000_1.ts"])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("e3vvid.video_processor.Popen", CapturingPopen)
    proc.concat()

    videolist = captured["videolist"]
    assert not videolist.is_relative_to(Path.cwd().resolve())
    assert videolist.exists() is False  # cleaned up after concat
    content_lines = (
        proc.get_videos(str(Path(tmp_path) / "src"))
    )
    assert all(Path(p).is_absolute() for p in content_lines)


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
    stderr = (
        "  Duration: 00:00:10.00\n"
        "  Stream #0:1: Audio: aac (HE-AAC), 48000 Hz, stereo\n"
    )
    _, audio = _parse_ffmpeg_info(stderr)
    assert audio is not None
    assert not audio.is_supported


def test_parse_ffmpeg_info_unknown_channels_returns_none_audio():
    stderr = (
        "  Duration: 00:00:10.00\n"
        "  Stream #0:1: Audio: aac (LC), 48000 Hz, 5.1(side)\n"
    )
    duration, audio = _parse_ffmpeg_info(stderr)
    assert duration == 10.0
    assert audio is None


AUDIO_48K = AudioInfo("aac", "LC", 48000, 2)


def _lines(tmp_path, names):
    return [f"file '{(tmp_path / 'src' / n).as_posix()}'\n" for n in names]


def _plan(proc, lines, durations, audios, mute_seconds, monkeypatch, cancel=None):
    proc._mute_seconds = mute_seconds
    calls = {"n": 0}

    def fake_probe(path):
        i = calls["n"]
        calls["n"] += 1
        return durations[i], audios[i]

    monkeypatch.setattr(proc, "_probe_media", fake_probe)
    return proc._plan_group(0, lines, cancel)


def test_plan_group_prefix_within_first_file(tmp_path, monkeypatch):
    names = ["20260825000000_1.ts", "20260825000100_2.ts"]
    proc = make_processor(tmp_path, names)
    plan = _plan(
        proc, _lines(tmp_path, names), [60.0, 60.0], [AUDIO_48K, AUDIO_48K],
        10, monkeypatch,
    )
    assert plan.use_fast_path
    assert len(plan.prefix_lines) == 1
    assert len(plan.rest_lines) == 1
    assert plan.output_name == "2026_08_25T00:00:00_muted.mp4"


def test_plan_group_prefix_spans_files(tmp_path, monkeypatch):
    names = [
        "20260825000000_1.ts",
        "20260825000100_2.ts",
        "20260825000200_3.ts",
    ]
    proc = make_processor(tmp_path, names)
    plan = _plan(
        proc, _lines(tmp_path, names), [60.0] * 3, [AUDIO_48K] * 3,
        70, monkeypatch,
    )
    assert plan.use_fast_path
    assert len(plan.prefix_lines) == 2
    assert len(plan.rest_lines) == 1


def test_plan_group_mutes_whole_group(tmp_path, monkeypatch):
    names = ["20260825000000_1.ts", "20260825000100_2.ts"]
    proc = make_processor(tmp_path, names)
    plan = _plan(
        proc, _lines(tmp_path, names), [60.0] * 2, [AUDIO_48K] * 2,
        200, monkeypatch,
    )
    assert plan.use_fast_path
    assert len(plan.prefix_lines) == 2
    assert plan.rest_lines == []


def test_plan_group_uses_cumulative_durations_for_merge_all_gaps(tmp_path, monkeypatch):
    names = [
        "20260825000000_1.ts",
        "20260825000100_2.ts",
        "20260825000500_3.ts",
    ]
    proc = make_processor(tmp_path, names, merge_all=True)
    plan = _plan(
        proc, _lines(tmp_path, names), [60.0] * 3, [AUDIO_48K] * 3,
        70, monkeypatch,
    )
    assert len(plan.prefix_lines) == 2
    assert len(plan.rest_lines) == 1


def test_plan_group_falls_back_on_probe_failure(tmp_path, monkeypatch):
    names = ["20260825000000_1.ts", "20260825000100_2.ts"]
    proc = make_processor(tmp_path, names)
    plan = _plan(
        proc, _lines(tmp_path, names), [None, 60.0], [None, AUDIO_48K],
        10, monkeypatch,
    )
    assert not plan.use_fast_path


def test_plan_group_falls_back_on_non_aac(tmp_path, monkeypatch):
    names = ["20260825000000_1.ts", "20260825000100_2.ts"]
    proc = make_processor(tmp_path, names)
    mp3 = AudioInfo("mp3", None, 44100, 2)
    plan = _plan(
        proc, _lines(tmp_path, names), [60.0, 60.0], [mp3, AUDIO_48K],
        10, monkeypatch,
    )
    assert not plan.use_fast_path


def test_plan_group_falls_back_on_rest_param_mismatch(tmp_path, monkeypatch):
    names = ["20260825000000_1.ts", "20260825000100_2.ts"]
    proc = make_processor(tmp_path, names)
    other = AudioInfo("aac", "LC", 44100, 2)
    plan = _plan(
        proc, _lines(tmp_path, names), [60.0, 60.0], [AUDIO_48K, other],
        10, monkeypatch,
    )
    assert not plan.use_fast_path


def test_plan_group_falls_back_on_later_rest_param_mismatch(
    tmp_path, monkeypatch
):
    names = [
        "20260825000000_1.ts",
        "20260825000100_2.ts",
        "20260825000200_3.ts",
    ]
    proc = make_processor(tmp_path, names)
    other = AudioInfo("aac", "LC", 44100, 2)
    plan = _plan(
        proc, _lines(tmp_path, names), [60.0] * 3,
        [AUDIO_48K, AUDIO_48K, other], 10, monkeypatch,
    )
    assert not plan.use_fast_path


def test_plan_group_profile_none_and_lc_are_compatible(tmp_path, monkeypatch):
    names = ["20260825000000_1.ts", "20260825000100_2.ts"]
    proc = make_processor(tmp_path, names)
    no_profile = AudioInfo("aac", None, 48000, 2)
    plan = _plan(
        proc, _lines(tmp_path, names), [60.0, 60.0],
        [no_profile, AUDIO_48K], 10, monkeypatch,
    )
    assert plan.use_fast_path


def test_plan_group_cancel_returns_none(tmp_path):
    proc = make_processor(tmp_path, ["20260825000000_1.ts"])
    cancel = threading.Event()
    cancel.set()
    assert proc._plan_group(
        0, ["file '/x/20260825000000_1.ts'\n"], cancel
    ) is None


def test_build_prefix_cmd_uses_stream_copy_and_matching_audio(tmp_path):
    proc = make_processor(tmp_path, ["20260825000000_1.ts"], mute_seconds=10)
    cmd = proc._build_prefix_cmd(
        "/tmp/prefix.txt",
        "/tmp/prefix0.mp4",
        AudioInfo("aac", "LC", 48000, 2),
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
    assert cmd[cmd.index("-bsf:a") + 1] == "aac_adtstoasc"
    assert cmd[-1] == "/tmp/out.mp4"


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
    proc = _muted_fast_proc(
        tmp_path, monkeypatch,
        ["20260825000000_1.ts", "20260825000100_2.ts"],
    )
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
    assert len(final_lines) == 2 and "prefix0.ts" in final_lines[0]


def test_concat_muted_single_file_writes_directly(tmp_path, monkeypatch):
    proc = _muted_fast_proc(tmp_path, monkeypatch, ["20260825000000_1.ts"])
    monkeypatch.setattr("e3vvid.video_processor.Popen", CapturingPopen)
    CapturingPopen.captured, CapturingPopen.lists = [], {}
    CapturingPopen.fail_prefix, CapturingPopen.fail_final = False, False
    assert proc.concat() == ["2026_08_25T00:00:00_muted.mp4"]
    assert len(CapturingPopen.captured) == 1
    assert CapturingPopen.captured[0][-1].endswith(
        "2026_08_25T00:00:00_muted.mp4"
    )


def test_concat_muted_prefix_failure_falls_back(tmp_path, monkeypatch):
    proc = _muted_fast_proc(
        tmp_path, monkeypatch,
        ["20260825000000_1.ts", "20260825000100_2.ts"],
    )
    monkeypatch.setattr("e3vvid.video_processor.Popen", CapturingPopen)
    CapturingPopen.captured, CapturingPopen.lists = [], {}
    CapturingPopen.fail_prefix, CapturingPopen.fail_final = True, False
    assert proc.concat() == ["2026_08_25T00:00:00_muted.mp4"]
    assert len(CapturingPopen.captured) == 2
    assert len(CapturingPopen.lists["videolist0.txt"].splitlines()) == 2


def test_concat_muted_final_concat_failure_falls_back(tmp_path, monkeypatch):
    proc = _muted_fast_proc(
        tmp_path, monkeypatch,
        ["20260825000000_1.ts", "20260825000100_2.ts"],
    )
    monkeypatch.setattr("e3vvid.video_processor.Popen", CapturingPopen)
    CapturingPopen.captured, CapturingPopen.lists = [], {}
    CapturingPopen.fail_prefix, CapturingPopen.fail_final = False, True
    assert proc.concat() == ["2026_08_25T00:00:00_muted.mp4"]
    assert len(CapturingPopen.captured) == 3
    assert len(CapturingPopen.lists["videolist0.txt"].splitlines()) == 2


def test_concat_muted_cancel_before_start_returns_empty(tmp_path, monkeypatch):
    proc = _muted_fast_proc(tmp_path, monkeypatch, ["20260825000000_1.ts"])
    cancel = threading.Event()
    cancel.set()
    monkeypatch.setattr("e3vvid.video_processor.Popen", CapturingPopen)
    CapturingPopen.captured = []
    assert proc.concat(cancel_event=cancel) == []
    assert CapturingPopen.captured == []


def test_concat_muted_prefixes_run_in_parallel(tmp_path, monkeypatch):
    names = [
        "20260825000000_1.ts",
        "20260825000100_2.ts",
        "20260825000500_3.ts",
        "20260825000600_4.ts",
    ]
    proc = make_processor(tmp_path, names, mute_seconds=10)
    monkeypatch.setattr(proc, "_probe_media", lambda p: (60.0, AUDIO_48K))
    monkeypatch.setattr("e3vvid.video_processor.os.cpu_count", lambda: 4)
    calls = []
    parallel_ok = {"value": False}
    barrier = threading.Barrier(2, timeout=5)

    def fake_run(cmd, cancel_event=None):
        if any(
            str(c).endswith(("prefix0.ts", "prefix1.ts"))
            for c in cmd
        ):
            calls.append("prefix")
            try:
                barrier.wait()
            except threading.BrokenBarrierError:
                return 1, "", "barrier"
            parallel_ok["value"] = True
        else:
            calls.append("other")
        return 0, "", ""

    monkeypatch.setattr(proc, "_run_ffmpeg", fake_run)
    assert proc.concat() == [
        "2026_08_25T00:00:00_muted.mp4",
        "2026_08_25T00:05:00_muted.mp4",
    ]
    assert parallel_ok["value"]
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


def _ffmpeg_volume(path, ss):
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-ss", str(ss), "-t", "0.2",
            "-i", str(path), "-vn", "-af", "volumedetect",
            "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
    )
    match = re.search(
        r"mean_volume:\s*(-?[\d.]+|-inf) dB", result.stderr
    )
    if match is None:
        return float("-inf")
    value = match.group(1)
    return float("-inf") if value == "-inf" else float(value)


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
            [
                "ffmpeg", "-y",
                "-f", "lavfi",
                "-i", "testsrc=duration=2:size=160x120:rate=10",
                "-f", "lavfi", "-i", "sine=frequency=1000:duration=2",
                "-c:v", "libx264", "-preset", "ultrafast",
                "-c:a", "aac", "-ar", "48000", "-ac", "1",
                str(src / name),
            ],
            check=True,
            capture_output=True,
        )

    proc = VideoProcessor(
        str(src),
        str(tmp_path / "dst"),
        TAIPEI.localize(datetime(2026, 8, 25, 0, 0, 0)),
        TAIPEI.localize(datetime(2026, 8, 25, 0, 5, 0)),
        mute_seconds=1,
    )
    assert proc.concat() == ["2026_08_25T00:00:00_muted.mp4"]
    out = tmp_path / "dst" / "2026_08_25T00:00:00_muted.mp4"

    assert _ffmpeg_volume(out, 0.5) < -70
    assert _ffmpeg_volume(out, 1.5) > -50
    assert _ffmpeg_volume(out, 2.5) > -50
    assert _ffmpeg_volume(out, 5.5) > -50

    decode = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-v", "warning",
            "-i", str(out), "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
    )
    assert decode.returncode == 0
    assert "aac bitstream error" not in decode.stderr.lower()

    def stream_duration(kind):
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", f"{kind}:0",
                "-show_entries", "stream=duration",
                "-of", "default=nw=1:nk=1",
                str(out),
            ],
            capture_output=True,
            text=True,
        )
        return float(result.stdout.strip())

    assert abs(stream_duration("v") - stream_duration("a")) <= 0.25