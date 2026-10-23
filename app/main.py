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
from app.updater.service import CheckStatus
from app.updater.tls import configure_ssl_certificates
from app.version import __version__

# 一定要在任何 SSLContext 建立之前設定：PyInstaller 產物沒有系統 CA 路徑，
# 不指定 certifi 就會出現 CERTIFICATE_VERIFY_FAILED。
configure_ssl_certificates()

# 啟動後先讓視窗畫出來，再偷偷檢查更新，避免拖慢開啟速度
AUTO_CHECK_DELAY_MS = 3000


def _run_update_probe() -> int:
    """``--check-updates``：不開視窗，直接把檢查結果印到終端機。

    打包後如果要確認「這台機器連不連得到 GitHub、憑證正不正常」，
    這是最快的方法（macOS 要從 .app 內執行）。
    """
    from app.updater.errors import UpdateError

    service = build_update_service()
    print(f"concat-e3v v{service.current_version}（{service.target.label}）")
    try:
        result = service.check()
    except UpdateError as exc:
        print(f"檢查更新失敗：{exc}")
        return 1
    latest = result.release.version if result.release else "未知"
    print(f"最新版本：{latest}")
    if result.status is CheckStatus.UP_TO_DATE:
        print("已是最新版本")
        return 0
    if result.status is CheckStatus.UNSUPPORTED_PLATFORM:
        print("這個平台沒有提供更新檔")
        return 2
    print(f"有新版本，對應檔案：{result.plan.asset.name if result.plan else '?'}")
    return 0


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
    if "--check-updates" in sys.argv:
        return _run_update_probe()

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
