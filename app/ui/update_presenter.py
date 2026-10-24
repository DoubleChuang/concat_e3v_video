"""Presentation layer for the update flow: service results -> dialogs and decisions.

Every Qt object stays on the main thread; the real network/file work runs in the
QThreads from :mod:`app.ui.update_worker`, whose signals queue back to the main
thread automatically.
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
    """Default wiring for callers that do not inject a service (e.g. window tests)."""
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

    # ------------------------------------------------------------------- check
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
        if result.plan is None:  # pragma: no cover - defensive
            return
        dialog = UpdateAvailableDialog(
            result, self._service.can_self_update(), self._parent
        )
        dialog.exec()
        if dialog.choice == "update":
            self._start_update(result.plan)
        elif dialog.choice == "page":
            self._open_release_page(result)

    # ---------------------------------------------------------------- download
    def _start_update(self, plan: UpdatePlan) -> None:
        # Do not use self.busy here: the check worker is still winding down and
        # would swallow the "download and update" click that just happened.
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
        # Let the worker really finish before quitting, otherwise Qt may destroy
        # objects while the thread is still running.
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
        """Wait for background workers before exit so no QThread is destroyed running."""
        for worker in (self._check_worker, self._apply_worker):
            if worker is not None and worker.isRunning():
                worker.wait(timeout_ms)
