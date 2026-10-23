"""「說明」選單：檢查更新、啟動時自動檢查、關於。

HomeWindow 是 QWidget、MainWindow 是 QMainWindow，這裡統一處理：
QMainWindow 用內建 menuBar，其餘用 layout 的 setMenuBar。
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import QMainWindow, QMenuBar, QMessageBox, QWidget

from app.settings import AppSettings, get_bool
from app.ui.update_presenter import UpdatePresenter
from app.version import __version__

AUTO_CHECK_KEY = "update_auto_check"


@dataclass
class HelpMenu:
    bar: QMenuBar
    check_action: object
    auto_check_action: object
    about_action: object


def attach_help_menu(
    window: QWidget,
    presenter: UpdatePresenter,
    settings: AppSettings,
) -> HelpMenu:
    if isinstance(window, QMainWindow):
        bar = window.menuBar()
    else:
        bar = QMenuBar(window)
        layout = window.layout()
        if layout is not None:
            layout.setMenuBar(bar)

    menu = bar.addMenu("說明")

    check_action = menu.addAction("檢查更新…")
    check_action.triggered.connect(lambda: presenter.check(window, manual=True))

    auto_check_action = menu.addAction("啟動時自動檢查更新")
    auto_check_action.setCheckable(True)
    auto_check_action.setChecked(get_bool(settings, AUTO_CHECK_KEY, True))

    def _persist(checked: bool) -> None:
        settings.set_value(AUTO_CHECK_KEY, checked)

    auto_check_action.toggled.connect(_persist)

    about_action = menu.addAction("關於 concat-e3v")
    about_action.triggered.connect(lambda: _show_about(window))

    presenter.busy_changed.connect(lambda busy: check_action.setEnabled(not busy))
    return HelpMenu(bar, check_action, auto_check_action, about_action)


def _show_about(window: QWidget) -> None:
    QMessageBox.about(
        window,
        "關於 concat-e3v",
        f"concat-e3v v{__version__}\n\n"
        "合併 E3V 行車紀錄影片，並可上傳到 YouTube。\n"
        "更新來源：https://github.com/DoubleChuang/concat_e3v_video",
    )


def auto_check_enabled(settings: AppSettings) -> bool:
    return get_bool(settings, AUTO_CHECK_KEY, True)
