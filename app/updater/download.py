"""HTTP download adapter: streaming writes, progress reporting, sha256 verify.

Verification matters: the artifact is executed after download, so a size or hash
mismatch is always a failure and never leaves half a file behind.
"""

from __future__ import annotations

import hashlib
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from app.updater.errors import DownloadError
from app.updater.models import Asset
from app.updater.ports import ProgressCallback
from app.updater.tls import CERT_ERROR_HINT, create_ssl_context, is_certificate_error

Opener = Callable[..., Any]
_CHUNK_SIZE = 1 << 20  # 1 MiB


class HttpDownloader:
    def __init__(
        self,
        timeout: float = 60.0,
        chunk_size: int = _CHUNK_SIZE,
        attempts: int = 2,
        opener: Opener | None = None,
        user_agent: str = "concat-e3v-updater",
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self._timeout = timeout
        self._chunk_size = chunk_size
        self._attempts = max(1, attempts)
        self._opener = opener or urllib.request.urlopen
        self._user_agent = user_agent
        self._ssl_context = ssl_context or create_ssl_context()

    def download(
        self,
        asset: Asset,
        destination: Path,
        on_progress: ProgressCallback | None = None,
    ) -> Path:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        part = destination.with_name(destination.name + ".part")

        last_error: Exception | None = None
        for attempt in range(1, self._attempts + 1):
            try:
                self._download_once(asset, part, on_progress)
                break
            except _RetryableDownloadError as exc:
                last_error = exc
                part.unlink(missing_ok=True)
                if attempt == self._attempts:
                    raise DownloadError(str(exc)) from exc
        if not part.exists():  # pragma: no cover - the loop either breaks or raises
            raise DownloadError(str(last_error or "下載失敗"))

        part.replace(destination)
        return destination

    def _download_once(
        self,
        asset: Asset,
        part: Path,
        on_progress: ProgressCallback | None,
    ) -> None:
        request = urllib.request.Request(
            asset.url, headers={"User-Agent": self._user_agent}
        )
        digest = hashlib.sha256()
        received = 0
        try:
            with self._opener(
                request, timeout=self._timeout, context=self._ssl_context
            ) as response:
                total = int(response.headers.get("Content-Length") or asset.size or 0)
                with open(part, "wb") as handle:
                    while True:
                        chunk = response.read(self._chunk_size)
                        if not chunk:
                            break
                        handle.write(chunk)
                        digest.update(chunk)
                        received += len(chunk)
                        if on_progress is not None:
                            on_progress(received, total)
        except urllib.error.HTTPError as exc:
            raise DownloadError(f"下載失敗（HTTP {exc.code}）") from exc
        except (urllib.error.URLError, ssl.SSLError, TimeoutError, OSError) as exc:
            # A certificate problem will not fix itself on retry; fail with advice.
            if is_certificate_error(exc):
                raise DownloadError(CERT_ERROR_HINT) from exc
            raise _RetryableDownloadError(f"下載中斷：{exc}") from exc

        if on_progress is not None:
            on_progress(received, received)
        asset.verify(received, digest.hexdigest())


class _RetryableDownloadError(Exception):
    """Network-level failure that is worth retrying."""
