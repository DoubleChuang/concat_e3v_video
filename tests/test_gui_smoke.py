import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from datetime import timedelta
from PySide6.QtCore import QSettings, QDateTime, QTimeZone
from PySide6.QtWidgets import QApplication, QCheckBox, QSpinBox, QDateTimeEdit
from app.settings import AppSettings
from app.ui.main_window import MainWindow
from app.pipeline import PipelineConfig


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


def _make_window(tmp_path, monkeypatch) -> MainWindow:
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    monkeypatch.setattr(
        "app.ui.main_window.AppSettings",
        lambda: AppSettings(QSettings.IniFormat),
    )
    monkeypatch.setattr("app.ui.main_window.resolve_ffmpeg", lambda: "/usr/bin/ffmpeg")
    return MainWindow()


def test_main_window_constructs(qapp, monkeypatch, tmp_path):
    window = _make_window(tmp_path, monkeypatch)
    assert window.windowTitle() == "concat-e3v"
    assert window.merge_all_check is not None
    assert isinstance(window.mute_spin, QSpinBox)
    assert isinstance(window.start_edit, QDateTimeEdit)
    assert isinstance(window.end_edit, QDateTimeEdit)


def test_build_cfg_fields(qapp, monkeypatch, tmp_path):
    window = _make_window(tmp_path, monkeypatch)
    window.src_edit.setText(str(tmp_path))
    window.dst_edit.setText(str(tmp_path / "out"))
    window.merge_all_check.setChecked(True)
    window.mute_check.setChecked(True)
    window.mute_spin.setValue(10)
    cfg = window._build_cfg()
    assert isinstance(cfg, PipelineConfig)
    assert cfg.merge_all is True
    assert cfg.mute_seconds == 10
    assert cfg.ffmpeg_bin == "/usr/bin/ffmpeg"


def test_validation_rejects_bad_time(qapp, monkeypatch, tmp_path):
    window = _make_window(tmp_path, monkeypatch)
    window.src_edit.setText(str(tmp_path))
    window.dst_edit.setText(str(tmp_path / "out"))
    window.start_edit.setDateTime(window.end_edit.dateTime())
    assert window._validate() != []


def test_build_cfg_attaches_taipei_tz_without_shifting(qapp, monkeypatch, tmp_path):
    window = _make_window(tmp_path, monkeypatch)
    window.start_edit.setDateTime(QDateTime(2026, 8, 25, 0, 0, 0, 0, QTimeZone(b"Asia/Taipei")))
    window.end_edit.setDateTime(QDateTime(2026, 8, 25, 1, 0, 0, 0, QTimeZone(b"Asia/Taipei")))
    cfg = window._build_cfg()
    assert cfg.start_time.hour == 0
    assert cfg.end_time.hour == 1
    assert cfg.start_time.tzinfo is not None
    assert cfg.start_time.utcoffset() == timedelta(hours=8)


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