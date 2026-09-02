import threading
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from app.auth_flow import AuthFlow
from upload_mp4_to_youtube import (
    append_upload_history,
    build_history_record,
    upload_video,
)


@dataclass
class UploadConfig:
    files: list[str]
    title: str | None = None
    description: str | None = None
    privacy: str = "private"
    tags: str | None = None
    playlist: str | None = None
    client_secrets: str | None = None
    credentials_file: str | None = None
    history_file: str | None = None


class UploadWorker(QThread):
    log = Signal(str)
    finished = Signal(dict)
    auth_required = Signal(str)
    auth_code_required = Signal(str)

    def __init__(self, cfg: UploadConfig, parent=None):
        super().__init__(parent)
        self._cfg = cfg
        self._cancel = threading.Event()
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
        try:
            if not self._auth_check():
                self.finished.emit(
                    {
                        "status": "aborted",
                        "reason": "youtube-auth-failed",
                        "uploaded": [],
                        "failed": [],
                    }
                )
                return
            uploaded: list[dict] = []
            failed: list[dict] = []
            for file in cfg.files:
                if self._cancel.is_set():
                    break
                path = Path(file)
                self.log.emit(f"上傳 {path} 到 YouTube...")
                result = upload_video(
                    str(path),
                    title=cfg.title,
                    description=cfg.description,
                    tags=cfg.tags,
                    privacy=cfg.privacy,
                    playlist=cfg.playlist,
                    client_secrets=cfg.client_secrets,
                    credentials_file=cfg.credentials_file,
                )
                if result.get("exit_code") == 0:
                    self.log.emit(f"上傳成功: {result.get('video_id')}")
                    uploaded.append(result)
                else:
                    self.log.emit(f"上傳失敗: {result.get('error')}")
                    failed.append(result)
                if cfg.history_file is not None:
                    append_upload_history(
                        cfg.history_file,
                        [build_history_record(result)],
                    )
                if self._cancel.is_set():
                    break
            if self._cancel.is_set():
                self.finished.emit(
                    {
                        "status": "aborted",
                        "reason": "cancelled",
                        "uploaded": uploaded,
                        "failed": failed,
                    }
                )
                return
            self.finished.emit(
                {
                    "status": "done",
                    "uploaded": uploaded,
                    "failed": failed,
                    "reason": None,
                }
            )
        except BaseException as exc:
            self.finished.emit(
                {
                    "status": "failed",
                    "reason": str(exc),
                    "uploaded": [],
                    "failed": [],
                }
            )
