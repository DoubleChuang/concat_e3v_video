import threading
from typing import Callable

from upload_mp4_to_youtube import check_youtube_upload_available


class AuthFlow:
    """Reusable YouTube auth retry loop shared by Qt workers."""

    def __init__(
        self,
        code_event: threading.Event,
        retry_event: threading.Event,
        cancel_event: threading.Event,
        emit_code_required: Callable[[str], None],
        emit_auth_required: Callable[[str], None],
    ):
        self._code_event = code_event
        self._retry_event = retry_event
        self._cancel_event = cancel_event
        self._emit_code_required = emit_code_required
        self._emit_auth_required = emit_auth_required
        self._code: str | None = None

    def set_code(self, code: str) -> None:
        self._code = code
        self._code_event.set()

    def _get_code_callback(self, url: str) -> str:
        self._emit_code_required(url)
        self._code_event.wait()
        self._code_event.clear()
        if self._cancel_event.is_set():
            raise RuntimeError("auth cancelled")
        return self._code or ""

    def auth_check(
        self,
        client_secrets: str | None,
        credentials_file: str | None,
    ) -> bool:
        while not self._cancel_event.is_set():
            try:
                check_youtube_upload_available(
                    client_secrets=client_secrets,
                    credentials_file=credentials_file,
                    get_code_callback=self._get_code_callback,
                )
                return True
            except BaseException as exc:
                self._emit_auth_required(str(exc))
                self._retry_event.wait()
                self._retry_event.clear()
        return False