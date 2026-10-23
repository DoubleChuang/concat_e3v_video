import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtWidgets import QApplication, QMainWindow

from app.settings import AppSettings, get_bool
from app.ui.home_window import HomeWindow
from app.ui.main_window import MainWindow
from app.ui.update_menu import AUTO_CHECK_KEY


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class FakePresenter(QObject):
    busy_changed = Signal(bool)

    def __init__(self):
        super().__init__()
        self.checks = []

    def check(self, parent=None, manual=True):
        self.checks.append((parent, manual))


@pytest.fixture
def settings(tmp_path, monkeypatch):
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    monkeypatch.setattr(
        "app.ui.home_window.AppSettings", lambda: AppSettings(QSettings.IniFormat)
    )
    monkeypatch.setattr(
        "app.ui.main_window.AppSettings", lambda: AppSettings(QSettings.IniFormat)
    )
    monkeypatch.setattr(
        "app.ui.main_window.resolve_ffmpeg", lambda: "/usr/bin/ffmpeg"
    )
    return AppSettings(QSettings.IniFormat)


def test_home_window_has_help_menu_with_update_actions(qapp, settings):
    presenter = FakePresenter()
    home = HomeWindow(updater=presenter)
    texts = [action.text() for action in home.help_menu.bar.actions()]
    assert texts == ["說明"]
    labels = [a.text() for a in home.help_menu.bar.actions()[0].menu().actions()]
    assert labels == ["檢查更新…", "啟動時自動檢查更新", "關於 concat-e3v"]


def test_main_window_uses_qmainwindow_menu_bar(qapp, settings):
    window = MainWindow(updater=FakePresenter())
    assert isinstance(window, QMainWindow)
    assert window.help_menu.bar is window.menuBar()


def test_check_action_calls_presenter_manually(qapp, settings):
    presenter = FakePresenter()
    home = HomeWindow(updater=presenter)
    home.help_menu.check_action.trigger()
    assert presenter.checks == [(home, True)]


def test_auto_check_action_reflects_and_persists_setting(qapp, settings):
    home = HomeWindow(updater=FakePresenter())
    assert home.help_menu.auto_check_action.isChecked() is get_bool(
        settings, AUTO_CHECK_KEY, True
    )

    home.help_menu.auto_check_action.setChecked(False)
    assert settings.value(AUTO_CHECK_KEY, True) == "false" or (
        settings.value(AUTO_CHECK_KEY, True) is False
    )

    again = HomeWindow(updater=FakePresenter())
    assert again.help_menu.auto_check_action.isChecked() is False


def test_busy_state_disables_check_action(qapp, settings):
    presenter = FakePresenter()
    home = HomeWindow(updater=presenter)
    assert home.help_menu.check_action.isEnabled() is True
    presenter.busy_changed.emit(True)
    assert home.help_menu.check_action.isEnabled() is False
    presenter.busy_changed.emit(False)
    assert home.help_menu.check_action.isEnabled() is True
