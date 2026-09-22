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