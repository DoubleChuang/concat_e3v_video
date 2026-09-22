import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from app.settings import AppSettings
from app.ui.home_window import HomeWindow


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


def _make_home(tmp_path, monkeypatch) -> HomeWindow:
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    monkeypatch.setattr(
        "app.ui.home_window.AppSettings",
        lambda: AppSettings(QSettings.IniFormat),
    )
    return HomeWindow()


def test_home_window_constructs(qapp, monkeypatch, tmp_path):
    home = _make_home(tmp_path, monkeypatch)
    assert home.windowTitle() == "concat-e3v"
    assert home.e3v_btn.text() == "處理E3V影片"
    assert home.upload_btn.text() == "單獨上傳影片"
    assert home.history_edit is not None


def test_e3v_button_emits_signal(qapp, monkeypatch, tmp_path):
    home = _make_home(tmp_path, monkeypatch)
    seen = []
    home.e3v_requested.connect(lambda: seen.append(1))
    home.e3v_btn.click()
    assert seen == [1]


def test_upload_button_emits_signal(qapp, monkeypatch, tmp_path):
    home = _make_home(tmp_path, monkeypatch)
    seen = []
    home.upload_requested.connect(lambda: seen.append(1))
    home.upload_btn.click()
    assert seen == [1]


def test_history_field_roundtrip(qapp, monkeypatch, tmp_path):
    home = _make_home(tmp_path, monkeypatch)
    home.history_edit.setText(str(tmp_path / "h.json"))
    s = AppSettings(QSettings.IniFormat)
    assert s.value("upload_history_file") == str(tmp_path / "h.json")
    home2 = _make_home(tmp_path, monkeypatch)
    assert home2.history_edit.text() == str(tmp_path / "h.json")


def test_close_quits_app(qapp, monkeypatch, tmp_path):
    home = _make_home(tmp_path, monkeypatch)
    quit_called = []
    monkeypatch.setattr(qapp, "quit", lambda: quit_called.append(1))
    home.close()
    assert quit_called == [1]