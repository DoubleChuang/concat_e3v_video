import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

import app.main as app_main
from app.settings import AppSettings
from app.ui.home_window import HomeWindow
from app.ui.main_window import MainWindow


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


def _make_main(tmp_path, monkeypatch) -> MainWindow:
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    monkeypatch.setattr(
        "app.ui.main_window.AppSettings",
        lambda: AppSettings(QSettings.IniFormat),
    )
    monkeypatch.setattr(
        "app.ui.main_window.resolve_ffmpeg", lambda: "/usr/bin/ffmpeg"
    )
    return MainWindow()


def test_e3v_button_switches_to_main_window(qapp, monkeypatch, tmp_path):
    home = _make_home(tmp_path, monkeypatch)
    main = _make_main(tmp_path, monkeypatch)
    app_main._connect(home, main)
    home.show()
    assert not main.isVisible()
    home.e3v_requested.emit()
    assert main.isVisible()
    assert not home.isVisible()


def test_upload_button_opens_upload_dialog(qapp, monkeypatch, tmp_path):
    opened = []

    class FakeDialog:
        def __init__(self, parent=None):
            opened.append(parent)

        def exec(self):
            opened.append("exec")
            return 0

    monkeypatch.setattr(app_main, "UploadWindow", FakeDialog)
    home = _make_home(tmp_path, monkeypatch)
    main = _make_main(tmp_path, monkeypatch)
    app_main._connect(home, main)
    home.show()
    home.upload_requested.emit()
    assert opened == [home, "exec"]


def test_back_requested_returns_to_home(qapp, monkeypatch, tmp_path):
    home = _make_home(tmp_path, monkeypatch)
    main = _make_main(tmp_path, monkeypatch)
    app_main._connect(home, main)
    home.show()
    main.show()
    main.back_requested.emit()
    assert home.isVisible()
    assert not main.isVisible()


def test_connect_wires_quit_guard(qapp, monkeypatch, tmp_path):
    home = _make_home(tmp_path, monkeypatch)
    main = _make_main(tmp_path, monkeypatch)
    app_main._connect(home, main)
    assert home.quit_guard is not None
    assert home.quit_guard() is False