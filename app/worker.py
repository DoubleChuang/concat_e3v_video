import threading

from PySide6.QtCore import QThread, Signal

from app.pipeline import PipelineConfig, run_pipeline
from upload_mp4_to_youtube import check_youtube_upload_available


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
        self._code: str | None = None
        self._retry_event = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()
        self._code_event.set()
        self._retry_event.set()

    def submit_auth_code(self, code: str) -> None:
        self._code = code
        self._code_event.set()

    def retry_auth(self) -> None:
        self._retry_event.set()

    def _get_code_callback(self, url: str) -> str:
        self.auth_code_required.emit(url)
        self._code_event.wait()
        self._code_event.clear()
        if self._cancel.is_set():
            raise RuntimeError("auth cancelled")
        return self._code or ""

    def _auth_check(self) -> bool:
        while not self._cancel.is_set():
            try:
                check_youtube_upload_available(
                    client_secrets=self._cfg.client_secrets,
                    credentials_file=self._cfg.credentials_file,
                    get_code_callback=self._get_code_callback,
                )
                return True
            except Exception as exc:
                self.auth_required.emit(str(exc))
                self._retry_event.wait()
                self._retry_event.clear()
        return False

    def run(self) -> None:
        cfg = self._cfg
        cfg.auth_callback = self._auth_check
        cfg.log = self.log.emit
        try:
            result = run_pipeline(cfg)
        except Exception as exc:
            result = {
                "status": "failed",
                "reason": str(exc),
                "video_names": [],
                "upload_results": [],
            }
        self.finished.emit(result)