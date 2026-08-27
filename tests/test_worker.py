import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime
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


def _run_and_pump(qapp, worker, timeout=5.0):
    import time as _t
    worker.start()
    deadline = _t.time() + timeout
    while worker.isRunning() and _t.time() < deadline:
        qapp.processEvents()
        _t.sleep(0.01)
    qapp.processEvents()
    return not worker.isRunning()


def test_worker_survives_system_exit_from_auth(qapp, monkeypatch, tmp_path):
    def fake_check(*a, **kw):
        raise SystemExit(2)

    def fake_run_pipeline(cfg):
        if cfg.upload_enabled and cfg.auth_callback is not None and not cfg.auth_callback():
            return {"status": "aborted", "reason": "youtube-auth-failed", "video_names": [], "upload_results": []}
        return {"status": "done", "video_names": [], "upload_results": [], "reason": None}

    monkeypatch.setattr("app.worker.check_youtube_upload_available", fake_check)
    monkeypatch.setattr("app.worker.run_pipeline", fake_run_pipeline)
    cfg = make_cfg(tmp_path)
    worker = PipelineWorker(cfg)
    results = {}
    auth_msgs = []

    def on_auth_required(msg):
        auth_msgs.append(msg)
        worker.cancel()  # user declines retry

    worker.auth_required.connect(on_auth_required)
    worker.finished.connect(lambda r: results.update(r))
    assert _run_and_pump(qapp, worker)
    assert len(auth_msgs) == 1
    assert results["status"] == "aborted"


def test_worker_survives_system_exit_in_pipeline(qapp, monkeypatch, tmp_path):
    def boom(cfg):
        raise SystemExit(2)

    monkeypatch.setattr("app.worker.run_pipeline", boom)
    cfg = make_cfg(tmp_path)
    worker = PipelineWorker(cfg)
    results = {}
    worker.finished.connect(lambda r: results.update(r))
    assert _run_and_pump(qapp, worker)
    assert results["status"] == "failed"


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
    qapp.processEvents()
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
    qapp.processEvents()
    assert results["status"] == "failed"
    assert results["reason"] == "boom"


def test_worker_cancel_sets_event(qapp, tmp_path):
    cfg = make_cfg(tmp_path)
    worker = PipelineWorker(cfg)
    worker.cancel()
    assert cfg.cancel_event is not None
    assert cfg.cancel_event.is_set()


def test_worker_auth_code_submitted(qapp, monkeypatch, tmp_path):
    calls = {}

    def fake_check(*a, **kw):
        cb = kw.get("get_code_callback")
        calls["code_returned"] = cb("https://accounts.google.com/auth")
        return None

    def fake_run_pipeline(cfg):
        if cfg.upload_enabled and cfg.auth_callback is not None and not cfg.auth_callback():
            return {"status": "aborted", "reason": "youtube-auth-failed", "video_names": [], "upload_results": []}
        return {"status": "done", "video_names": [], "upload_results": [], "reason": None}

    monkeypatch.setattr("app.worker.check_youtube_upload_available", fake_check)
    monkeypatch.setattr("app.worker.run_pipeline", fake_run_pipeline)
    cfg = make_cfg(tmp_path)
    worker = PipelineWorker(cfg)
    results = {}
    urls = []

    def on_code_required(url):
        urls.append(url)
        worker.submit_auth_code("MYCODE")

    worker.auth_code_required.connect(on_code_required)
    worker.finished.connect(lambda r: results.update(r))
    assert _run_and_pump(qapp, worker)
    assert urls == ["https://accounts.google.com/auth"]
    assert calls["code_returned"] == "MYCODE"
    assert results["status"] == "done"


def test_worker_cancel_while_waiting_for_code(qapp, monkeypatch, tmp_path):
    def fake_check(*a, **kw):
        cb = kw.get("get_code_callback")
        cb("https://accounts.google.com/auth")
        return None

    def fake_run_pipeline(cfg):
        if cfg.upload_enabled and cfg.auth_callback is not None and not cfg.auth_callback():
            return {"status": "aborted", "reason": "youtube-auth-failed", "video_names": [], "upload_results": []}
        return {"status": "done", "video_names": [], "upload_results": [], "reason": None}

    monkeypatch.setattr("app.worker.check_youtube_upload_available", fake_check)
    monkeypatch.setattr("app.worker.run_pipeline", fake_run_pipeline)
    cfg = make_cfg(tmp_path)
    worker = PipelineWorker(cfg)
    results = {}

    def on_code_required(url):
        worker.cancel()

    worker.auth_code_required.connect(on_code_required)
    worker.finished.connect(lambda r: results.update(r))
    assert _run_and_pump(qapp, worker)
    assert results["status"] == "aborted"


def test_worker_auth_retry_after_failure(qapp, monkeypatch, tmp_path):
    calls = {"n": 0}

    def fake_check(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("expired credentials")
        return None

    def fake_run_pipeline(cfg):
        if cfg.upload_enabled and cfg.auth_callback is not None and not cfg.auth_callback():
            return {"status": "aborted", "reason": "youtube-auth-failed", "video_names": [], "upload_results": []}
        return {"status": "done", "video_names": [], "upload_results": [], "reason": None}

    monkeypatch.setattr("app.worker.check_youtube_upload_available", fake_check)
    monkeypatch.setattr("app.worker.run_pipeline", fake_run_pipeline)
    cfg = make_cfg(tmp_path)
    worker = PipelineWorker(cfg)
    results = {}

    def on_auth_required(msg):
        worker.retry_auth()

    worker.auth_required.connect(on_auth_required)
    worker.finished.connect(lambda r: results.update(r))
    assert _run_and_pump(qapp, worker)
    assert calls["n"] == 2
    assert results["status"] == "done"