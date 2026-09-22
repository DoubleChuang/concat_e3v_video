from datetime import datetime
import json
import threading
import pytz
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


def test_pipeline_aborts_when_cancelled_during_concat(monkeypatch, tmp_path):
    cancel = threading.Event()
    cancel.set()

    class FakeProcessor:
        def __init__(self, *a, **kw):
            pass

        def concat(self, cancel_event=None):
            return []

    monkeypatch.setattr("app.pipeline.VideoProcessor", FakeProcessor)
    cfg = make_cfg(tmp_path, cancel_event=cancel)
    result = run_pipeline(cfg)
    assert result["status"] == "aborted"
    assert result["reason"] == "cancelled"


def test_pipeline_aborts_when_cancelled_during_upload(monkeypatch, tmp_path):
    cancel = threading.Event()

    class FakeProcessor:
        def __init__(self, *a, **kw):
            pass

        def concat(self, cancel_event=None):
            return ["out.mp4"]

    monkeypatch.setattr("app.pipeline.VideoProcessor", FakeProcessor)

    def fake_upload(video_path, **kw):
        cancel.set()
        return {"exit_code": 0}

    monkeypatch.setattr("app.pipeline.upload_video", fake_upload)
    cfg = make_cfg(
        tmp_path,
        upload_enabled=True,
        auth_callback=lambda: True,
        cancel_event=cancel,
    )
    result = run_pipeline(cfg)
    assert result["status"] == "aborted"
    assert result["reason"] == "cancelled"


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