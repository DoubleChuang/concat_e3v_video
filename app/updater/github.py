"""GitHub Releases 轉接器。

用公開 API（不需要 token）讀取最新正式版；只有讀取，不會寫入任何東西。
JSON → domain 的轉換寫成純函式 :func:`parse_release`，方便離線測試。
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from typing import Any, Callable

from app.updater.errors import ReleaseLookupError
from app.updater.models import Asset, Release
from app.updater.tls import CERT_ERROR_HINT, create_ssl_context, is_certificate_error
from app.updater.version import Version

API_BASE = "https://api.github.com"
DEFAULT_REPOSITORY = "DoubleChuang/concat_e3v_video"
USER_AGENT = "concat-e3v-updater"

Opener = Callable[..., Any]


def _sha256_from_digest(digest: object) -> str | None:
    """GitHub 的 asset digest 長成 ``sha256:abc...``。"""
    if not isinstance(digest, str):
        return None
    algorithm, _, value = digest.partition(":")
    if algorithm.lower() != "sha256" or not value:
        return None
    return value.strip().lower()


def parse_release(payload: dict[str, Any]) -> Release:
    tag = str(payload.get("tag_name") or "").strip()
    if not tag:
        raise ReleaseLookupError("release 缺少 tag_name")
    try:
        version = Version.parse(tag)
    except ValueError as exc:
        raise ReleaseLookupError(f"release tag 不是有效版本號: {tag}") from exc

    assets = tuple(
        Asset(
            name=str(item.get("name") or ""),
            url=str(item.get("browser_download_url") or ""),
            size=int(item.get("size") or 0),
            sha256=_sha256_from_digest(item.get("digest")),
        )
        for item in payload.get("assets") or []
        if item.get("name") and item.get("browser_download_url")
    )
    return Release(
        version=version,
        tag=tag,
        notes=str(payload.get("body") or ""),
        page_url=str(payload.get("html_url") or ""),
        assets=assets,
    )


class GitHubReleaseSource:
    def __init__(
        self,
        repository: str = DEFAULT_REPOSITORY,
        api_base: str = API_BASE,
        timeout: float = 15.0,
        opener: Opener | None = None,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self._repository = repository
        self._api_base = api_base.rstrip("/")
        self._timeout = timeout
        self._opener = opener or urllib.request.urlopen
        self._ssl_context = ssl_context or create_ssl_context()

    def latest(self) -> Release:
        url = f"{self._api_base}/repos/{self._repository}/releases/latest"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with self._opener(
                request, timeout=self._timeout, context=self._ssl_context
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise ReleaseLookupError("這個 repo 還沒有任何正式版本") from exc
            if exc.code in (403, 429):
                raise ReleaseLookupError(
                    "GitHub API 暫時拒絕請求（可能是限流），請稍後再試"
                ) from exc
            raise ReleaseLookupError(f"GitHub API 回應 {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if is_certificate_error(exc):
                raise ReleaseLookupError(CERT_ERROR_HINT) from exc
            raise ReleaseLookupError(f"無法連線到 GitHub：{exc}") from exc
        except json.JSONDecodeError as exc:
            raise ReleaseLookupError("GitHub API 回應格式不正確") from exc

        if not isinstance(payload, dict):
            raise ReleaseLookupError("GitHub API 回應格式不正確")
        return parse_release(payload)
