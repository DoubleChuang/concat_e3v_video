import hashlib
import io
import urllib.error

import pytest

from app.updater.download import HttpDownloader
from app.updater.errors import DownloadError
from app.updater.models import Asset

DATA = b"new-binary" * 1000
URL = "https://example.test/artifact"


class _Response(io.BytesIO):
    def __init__(self, data: bytes, headers: dict | None = None):
        super().__init__(data)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _opener(data: bytes = DATA, headers: dict | None = None):
    def opener(request, timeout=None):
        return _Response(data, headers)

    return opener


def _asset(**kwargs) -> Asset:
    defaults = dict(
        name="artifact",
        url=URL,
        size=len(DATA),
        sha256=hashlib.sha256(DATA).hexdigest(),
    )
    defaults.update(kwargs)
    return Asset(**defaults)


def test_download_writes_file_and_verifies(tmp_path):
    destination = tmp_path / "artifact"
    result = HttpDownloader(opener=_opener()).download(_asset(), destination)
    assert result == destination
    assert destination.read_bytes() == DATA
    assert not destination.with_name("artifact.part").exists()


def test_download_reports_progress(tmp_path):
    seen = []
    HttpDownloader(opener=_opener(DATA, {"Content-Length": str(len(DATA))}), chunk_size=512).download(
        _asset(), tmp_path / "a", on_progress=lambda r, t: seen.append((r, t))
    )
    assert seen[-1] == (len(DATA), len(DATA))


def test_download_rejects_hash_mismatch(tmp_path):
    with pytest.raises(DownloadError):
        HttpDownloader(opener=_opener()).download(
            _asset(sha256="0" * 64), tmp_path / "a"
        )
    assert not (tmp_path / "a").exists()


def test_download_rejects_size_mismatch(tmp_path):
    with pytest.raises(DownloadError):
        HttpDownloader(opener=_opener()).download(
            _asset(size=len(DATA) + 1, sha256=None), tmp_path / "a"
        )


def test_download_maps_http_error(tmp_path):
    def opener(request, timeout=None):
        raise urllib.error.HTTPError(URL, 500, "boom", {}, None)

    with pytest.raises(DownloadError):
        HttpDownloader(attempts=1, opener=opener).download(_asset(), tmp_path / "a")


def test_download_retries_transient_failure(tmp_path):
    calls = {"n": 0}

    def opener(request, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.URLError("connection reset")
        return _Response(DATA)

    HttpDownloader(attempts=2, opener=opener).download(_asset(), tmp_path / "a")
    assert calls["n"] == 2
    assert (tmp_path / "a").read_bytes() == DATA


def test_download_gives_up_after_attempts(tmp_path):
    def opener(request, timeout=None):
        raise urllib.error.URLError("down")

    with pytest.raises(DownloadError):
        HttpDownloader(attempts=2, opener=opener).download(_asset(), tmp_path / "a")
