import threading

from PySide6.QtCore import QThread, Signal

from app.pipeline import PipelineConfig, run_pipeline
from app.auth_flow import AuthFlow


class PipelineWorker(QThread):
    log = Signal(str)
    finished = Signal(dict)
    auth_required = Signal(str)
    auth_code_required = Signal(str)

    def __init__(self, cfg: PipelineConfig, parent=None):
        super().__init__(parent)
        self._cfg = cfg
        self._cancel = threading.Event()
        cfg.cancel_event = self._cancel
        self._code_event = threading.Event()
        self._retry_event = threading.Event()
        self._auth = AuthFlow(
            self._code_event,
            self._retry_event,
            self._cancel,
            emit_code_required=self.auth_code_required.emit,
            emit_auth_required=self.auth_required.emit,
        )

    def cancel(self) -> None:
        self._cancel.set()
        self._code_event.set()
        self._retry_event.set()

    def submit_auth_code(self, code: str) -> None:
        self._auth.set_code(code)

    def retry_auth(self) -> None:
        self._retry_event.set()

    def _auth_check(self) -> bool:
        return self._auth.auth_check(
            client_secrets=self._cfg.client_secrets,
            credentials_file=self._cfg.credentials_file,
        )

    def run(self) -> None:
        cfg = self._cfg
        cfg.auth_callback = self._auth_check
        cfg.log = self.log.emit
        try:
            result = run_pipeline(cfg)
        except BaseException as exc:
            result = {
                "status": "failed",
                "reason": str(exc),
                "video_names": [],
                "upload_results": [],
            }
        self.finished.emit(result)