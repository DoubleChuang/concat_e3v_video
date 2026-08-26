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