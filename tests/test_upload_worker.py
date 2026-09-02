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
    worker = UploadWorker(
        UploadConfig(
            files=files,
            title="My Title",
            description="My Desc",
            privacy="unlisted",
            tags="tag1, tag2",
            playlist="My Playlist",
            client_secrets="/tmp/cs.json",
            credentials_file="/tmp/cred.json",
        )
    )
    results = {}
    worker.finished.connect(lambda r: results.update(r))
    assert _run_and_pump(qapp, worker)
    assert results["status"] == "done"
    assert [c[0] for c in calls] == files
    assert calls[0][1] == {
        "title": "My Title",
        "description": "My Desc",
        "tags": "tag1, tag2",
        "privacy": "unlisted",
        "playlist": "My Playlist",
        "client_secrets": "/tmp/cs.json",
        "credentials_file": "/tmp/cred.json",
    }
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
    assert results["reason"] == "youtube-auth-failed"


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


def test_upload_worker_cancelled_result_keeps_completed_files(qapp, monkeypatch, tmp_path):
    import threading
    import time as _t

    calls = []
    proceed = threading.Event()

    def fake_upload_video(path, **kw):
        calls.append(path)
        proceed.wait(5.0)
        return {"file": path, "name": path, "exit_code": 0, "video_id": f"id{len(calls)}"}

    monkeypatch.setattr("app.upload_worker.upload_video", fake_upload_video)
    monkeypatch.setattr("app.auth_flow.check_youtube_upload_available", lambda **kw: None)
    worker = UploadWorker(
        UploadConfig(files=[str(tmp_path / "a.mp4"), str(tmp_path / "b.mp4")])
    )
    results = {}
    worker.finished.connect(lambda r: results.update(r))
    worker.start()
    deadline = _t.time() + 5.0
    while not calls and _t.time() < deadline:
        qapp.processEvents()
        _t.sleep(0.01)
    assert calls
    worker.cancel()
    proceed.set()
    assert worker.wait(5000)
    qapp.processEvents()
    assert results["status"] == "aborted"
    assert len(results["uploaded"]) >= 1


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


def test_upload_worker_history_write_error_continues_batch(qapp, monkeypatch, tmp_path):
    calls = []

    def fake_upload_video(path, **kw):
        return {"file": path, "name": path, "exit_code": 0, "video_id": f"id{len(calls)}"}

    def boom(*a, **kw):
        raise OSError("disk full")

    monkeypatch.setattr("app.upload_worker.upload_video", fake_upload_video)
    monkeypatch.setattr(
        "app.auth_flow.check_youtube_upload_available", lambda **kw: None
    )
    monkeypatch.setattr("app.upload_worker.append_upload_history", boom)
    worker = UploadWorker(
        UploadConfig(
            files=[str(tmp_path / "a.mp4"), str(tmp_path / "b.mp4")],
            history_file=str(tmp_path / "h.json"),
        )
    )
    results = {}
    logs = []
    worker.log.connect(logs.append)
    worker.finished.connect(lambda r: results.update(r))
    assert _run_and_pump(qapp, worker)
    assert results["status"] == "done"
    assert len(results["uploaded"]) == 2
    assert any("無法寫入上傳紀錄" in line for line in logs)
