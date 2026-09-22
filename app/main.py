import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

from app.ui.home_window import HomeWindow
from app.ui.main_window import MainWindow
from app.ui.upload_window import UploadWindow


def _connect(home: HomeWindow, main_window: MainWindow) -> None:
    home.e3v_requested.connect(lambda: (home.hide(), main_window.show()))
    home.upload_requested.connect(lambda: UploadWindow(home).exec())
    main_window.back_requested.connect(lambda: (main_window.hide(), home.show()))


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("concat-e3v")
    app.setOrganizationName("concat-e3v")
    app.setQuitOnLastWindowClosed(False)
    home = HomeWindow()
    main_window = MainWindow()
    _connect(home, main_window)
    home.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())