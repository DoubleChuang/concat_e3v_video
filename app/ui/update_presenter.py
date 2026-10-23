"""更新流程的簡報層：把 service 的結果變成對話框與使用者決定。

所有 Qt 物件都留在主執行緒；實際的網路/檔案工作跑在
:mod:`app.ui.update_worker` 的 QThread 裡，訊號自動排回主執行緒。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QMessageBox

from app.updater.models import InstallOutcome, UpdatePlan
from app.updater.service import CheckResult, CheckStatus, UpdateService
from app.ui.update_dialog import DownloadProgressDialog, UpdateAvailableDialog
from app.ui.update_worker import UpdateApplyWorker, UpdateCheckWorker


def build_default_presenter(parent=None) -> UpdatePresenter:
    """沒有注入 service 時（例如直接開視窗的測試）用的預設組裝。"""
    from app.updater.factory import build_update_service

    return UpdatePresenter(build_update_service(), parent)


class UpdatePresenter(QObject):
    busy_changed = Signal(bool)

    def __init__(self, service: UpdateService, parent=None) -> None:
        super().__init__(parent)
        self._service = service
        self._parent = None
        self._manual = True
        self._check_worker: UpdateCheckWorker | None = None
        self._apply_worker: UpdateApplyWorker | None = None
        self._progress_dialog: DownloadProgressDialog | None = None

    @property
    def service(self) -> UpdateService:
        return self._service

    @property
    def busy(self) -> bool:
        return self._check_worker is not None or self._apply_worker is not None

    # ------------------------------------------------------------------ 檢查
    def check(self, parent=None, manual: bool = True) -> None:
        if self.busy:
            return
        self._parent = parent
        self._manual = manual
        worker = UpdateCheckWorker(self._service, parent=self)
        worker.succeeded.connect(self._on_checked)
        worker.failed.connect(self._on_check_failed)
        worker.finished.connect(self._on_check_finished)
        self._check_worker = worker
        self.busy_changed.emit(True)
        worker.start()

    def _on_check_finished(self) -> None:
        self._check_worker = None
        self.busy_changed.emit(False)

    def _on_check_failed(self, message: str) -> None:
        if self._manual:
            QMessageBox.warning(self._parent, "檢查更新失敗", message)

    def _on_checked(self, result: CheckResult) -> None:
        if result.status is CheckStatus.UP_TO_DATE:
            if self._manual:
                QMessageBox.information(
                    self._parent,
                    "已是最新版本",
                    f"目前版本 v{result.current}，沒有更新的版本。",
                )
            return
        if result.status is CheckStatus.UNSUPPORTED_PLATFORM:
            QMessageBox.information(
                self._parent,
                "沒有對應的更新檔",
                f"最新版本是 v{result.release.version if result.release else '?'}，"
                f"但這個平台（{self._service.target.label}）沒有提供檔案。",
            )
            self._open_release_page(result)
            return
        if result.plan is None:  # pragma: no cover - 防禦性
            return
        dialog = UpdateAvailableDialog(
            result, self._service.can_self_update(), self._parent
        )
        dialog.exec()
        if dialog.choice == "update":
            self._start_update(result.plan)
        elif dialog.choice == "page":
            self._open_release_page(result)

    # ------------------------------------------------------------------ 下載
    def _start_update(self, plan: UpdatePlan) -> None:
        # 這裡不能用 self.busy：檢查 worker 還在收尾，會誤擋掉剛按下的「下載並更新」
        if self._apply_worker is not None:
            return
        dialog = DownloadProgressDialog(str(plan.release.version), self._parent)
        self._progress_dialog = dialog
        worker = UpdateApplyWorker(self._service, plan, parent=self)
        worker.progress.connect(self._on_progress)
        worker.succeeded.connect(self._on_applied)
        worker.failed.connect(self._on_apply_failed)
        worker.finished.connect(self._on_apply_finished)
        self._apply_worker = worker
        dialog.show()
        self.busy_changed.emit(True)
        worker.start()

    def _on_progress(self, received: int, total: int) -> None:
        if self._progress_dialog is not None:
            self._progress_dialog.set_progress(received, total)

    def _on_apply_failed(self, message: str) -> None:
        if self._progress_dialog is not None:
            self._progress_dialog.close()
            self._progress_dialog = None
        QMessageBox.warning(self._parent, "更新失敗", message)

    def _on_apply_finished(self) -> None:
        self._apply_worker = None
        self.busy_changed.emit(False)

    def _on_applied(self, outcome: InstallOutcome) -> None:
        if self._progress_dialog is not None:
            self._progress_dialog.close()
            self._progress_dialog = None
        if outcome.manual_fallback:
            QMessageBox.information(
                self._parent, "請手動完成更新", outcome.message
            )
            self._reveal(Path(outcome.artifact_path).parent if outcome.artifact_path else None)
            return
        QMessageBox.information(
            self._parent,
            "更新完成",
            outcome.message or "新版本已下載，重新啟動後生效。",
        )
        # 等 worker 真的結束再離開，避免 Qt 在執行緒還活著時拆掉物件
        worker = self._apply_worker
        if worker is not None and worker.isRunning():
            worker.wait(3000)
        self._restart(outcome)

    def _restart(self, outcome: InstallOutcome) -> None:
        if outcome.relaunch:
            QProcess.startDetached(outcome.relaunch[0], list(outcome.relaunch[1:]))
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _open_release_page(self, result: CheckResult) -> None:
        if result.release and result.release.page_url:
            QDesktopServices.openUrl(QUrl(result.release.page_url))

    def _reveal(self, directory: Path | None) -> None:
        if directory is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))

    def shutdown(self, timeout_ms: int = 3000) -> None:
        """離開前等背景 worker 收尾，避免 QThread 在解構時還在跑。"""
        for worker in (self._check_worker, self._apply_worker):
            if worker is not None and worker.isRunning():
                worker.wait(timeout_ms)
