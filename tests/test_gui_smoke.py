import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
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