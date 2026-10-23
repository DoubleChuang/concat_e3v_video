"""更新流程的執行緒包裝（與 app/worker.py 相同風格：QThread + signals）。

網路 I/O 一定要離開 UI 執行緒，否則檢查更新時整個視窗會凍住。
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from app.updater.errors import UpdateError
from app.updater.models import UpdatePlan
from app.updater.service import UpdateService


class UpdateCheckWorker(QThread):
    succeeded = Signal(object)  # CheckResult
    failed = Signal(str)

    def __init__(self, service: UpdateService, parent=None) -> None:
        super().__init__(parent)
        self._service = service

    def run(self) -> None:
        try:
            self.succeeded.emit(self._service.check())
        except UpdateError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # pragma: no cover - 防禦性
            self.failed.emit(f"檢查更新時發生未預期的錯誤：{exc}")


class UpdateApplyWorker(QThread):
    progress = Signal(int, int)
    succeeded = Signal(object)  # InstallOutcome
    failed = Signal(str)

    def __init__(self, service: UpdateService, plan: UpdatePlan, parent=None) -> None:
        super().__init__(parent)
        self._service = service
        self._plan = plan

    def run(self) -> None:
        try:
            artifact = self._service.download(self._plan, self.progress.emit)
            outcome = self._service.apply(self._plan, artifact)
            self.succeeded.emit(outcome)
        except UpdateError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # pragma: no cover - 防禦性
            self.failed.emit(f"更新時發生未預期的錯誤：{exc}")
