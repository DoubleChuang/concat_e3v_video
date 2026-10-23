import io
import json
import urllib.error

import pytest

from app.updater.errors import ReleaseLookupError
from app.updater.github import GitHubReleaseSource, parse_release
from app.updater.targets import parse_target

PAYLOAD = {
    "tag_name": "v0.0.9",
    "body": "修正更新流程",
    "html_url": "https://github.com/DoubleChuang/concat_e3v_video/releases/tag/v0.0.9",
    "assets": [
        {
            "name": "concat-e3v-linux-x86_64",
            "browser_download_url": "https://example.test/linux",
            "size": 123,
            "digest": "sha256:ABC123",
        },
        {
            "name": "concat-e3v-windows.exe",
            "browser_download_url": "https://example.test/win.exe",
            "size": 456,
            "digest": None,
        },
    ],
}


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _opener_for(payload: dict):
    def opener(request, timeout=None):
        return _Response(json.dumps(payload).encode("utf-8"))

    return opener


def test_parse_release_maps_fields_and_digest():
    release = parse_release(PAYLOAD)
    assert str(release.version) == "0.0.9"
    assert release.tag == "v0.0.9"
    assert release.notes == "修正更新流程"
    assert release.page_url.endswith("v0.0.9")
    linux = release.assets[0]
    assert linux.sha256 == "abc123"
    assert release.assets[1].sha256 is None


def test_parse_release_selects_asset_for_target():
    release = parse_release(PAYLOAD)
    assert release.asset_for(parse_target("linux", "x86_64")).name == (
        "concat-e3v-linux-x86_64"
    )
    assert release.asset_for(parse_target("win32", "AMD64")).name == (
        "concat-e3v-windows.exe"
    )
    assert release.asset_for(parse_target("darwin", "arm64")) is None


def test_parse_release_rejects_missing_tag():
    with pytest.raises(ReleaseLookupError):
        parse_release({"tag_name": ""})


def test_parse_release_rejects_non_version_tag():
    with pytest.raises(ReleaseLookupError):
        parse_release({"tag_name": "nightly-build"})


def test_source_returns_release():
    source = GitHubReleaseSource(opener=_opener_for(PAYLOAD))
    assert str(source.latest().version) == "0.0.9"


def test_source_maps_404_to_lookup_error():
    def opener(request, timeout=None):
        raise urllib.error.HTTPError("url", 404, "Not Found", {}, None)

    with pytest.raises(ReleaseLookupError):
        GitHubReleaseSource(opener=opener).latest()


def test_source_maps_offline_to_lookup_error():
    def opener(request, timeout=None):
        raise urllib.error.URLError("no network")

    with pytest.raises(ReleaseLookupError):
        GitHubReleaseSource(opener=opener).latest()


def test_source_sends_required_headers():
    seen = {}

    def opener(request, timeout=None):
        seen["url"] = request.full_url
        seen["ua"] = request.get_header("User-agent")
        return _Response(json.dumps(PAYLOAD).encode("utf-8"))

    GitHubReleaseSource("owner/repo", opener=opener).latest()
    assert seen["url"].endswith("/repos/owner/repo/releases/latest")
    assert seen["ua"]
