import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.settings import AppSettings
from app.ui.home_window import HomeWindow
from app.ui.main_window import MainWindow
from app.ui.update_menu import auto_check_enabled
from app.ui.update_presenter import UpdatePresenter
from app.ui.upload_window import UploadWindow
from app.updater.factory import build_update_service
from app.version import __version__

# 啟動後先讓視窗畫出來，再偷偷檢查更新，避免拖慢開啟速度
AUTO_CHECK_DELAY_MS = 3000


def _connect(
    home: HomeWindow,
    main_window: MainWindow,
    presenter: UpdatePresenter | None = None,
) -> None:
    home.quit_guard = main_window._busy
    home.e3v_requested.connect(lambda: (home.hide(), main_window.show()))
    home.upload_requested.connect(lambda: UploadWindow(home).exec())
    main_window.back_requested.connect(lambda: (main_window.hide(), home.show()))


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("concat-e3v")
    app.setOrganizationName("concat-e3v")
    app.setApplicationVersion(__version__)
    app.setQuitOnLastWindowClosed(False)

    presenter = UpdatePresenter(build_update_service(), parent=app)
    home = HomeWindow(updater=presenter)
    main_window = MainWindow(updater=presenter)
    _connect(home, main_window, presenter)
    app.aboutToQuit.connect(presenter.shutdown)
    home.show()

    if auto_check_enabled(AppSettings()):
        QTimer.singleShot(
            AUTO_CHECK_DELAY_MS, lambda: presenter.check(home, manual=False)
        )
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
