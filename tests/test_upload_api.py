import sys
import types
from pathlib import Path
import pytest
import upload_mp4_to_youtube as up


@pytest.fixture
def fake_vendored(monkeypatch):
    """預先注入 fake youtube_upload 套件到 sys.modules，避免打到真的 vendored 套件。"""
    youtube_upload = types.ModuleType("youtube_upload")
    auth = types.ModuleType("youtube_upload.auth")
    browser = types.ModuleType("youtube_upload.auth.browser")
    console = types.ModuleType("youtube_upload.auth.console")
    main_mod = types.ModuleType("youtube_upload.main")

    youtube_upload.auth = auth
    youtube_upload.main = main_mod
    auth.browser = browser
    auth.console = console
    main_mod.main = lambda args: None

    for name, mod in {
        "youtube_upload": youtube_upload,
        "youtube_upload.auth": auth,
        "youtube_upload.auth.browser": browser,
        "youtube_upload.auth.console": console,
        "youtube_upload.main": main_mod,
    }.items():
        monkeypatch.setitem(sys.modules, name, mod)

    return auth, browser, console, main_mod


class FakeYouTube:
    def __init__(self, calls):
        self._calls = calls

    def channels(self):
        return self

    def list(self, mine=True, part="id", maxResults=1):
        self._calls["listed"] = True
        return self

    def execute(self):
        return {"items": [{"id": "x"}]}


def test_check_available_uses_custom_get_code_callback(monkeypatch, fake_vendored):
    auth, _browser, _console, _main = fake_vendored
    calls = {}

    def fake_get_resource(client_secrets, credentials_file, get_code_callback=None):
        calls["callback"] = get_code_callback
        return FakeYouTube(calls)

    auth.get_resource = fake_get_resource
    monkeypatch.setattr(up, "_default_client_secrets_path", lambda: "/tmp/cs.json")

    def my_callback(url):
        return "CODE"

    up.check_youtube_upload_available(
        client_secrets="/tmp/cs.json",
        credentials_file="/tmp/cred.json",
        get_code_callback=my_callback,
    )
    assert calls["callback"] is my_callback
    assert calls.get("listed")


def test_upload_video_returns_result_dict(monkeypatch, tmp_path, fake_vendored):
    video = tmp_path / "test.mp4"
    video.write_bytes(b"x")

    def fake_upload_one(ns, video_path, youtube_upload_main):
        return {
            "file": video_path.as_posix(),
            "name": video_path.name,
            "exit_code": 0,
            "video_id": "abc123",
        }

    monkeypatch.setattr(up, "_upload_one_video", fake_upload_one)

    result = up.upload_video(
        str(video), title="My Title", privacy="unlisted"
    )
    assert result["exit_code"] == 0
    assert result["video_id"] == "abc123"
    assert result["name"] == "test.mp4"


def test_upload_video_default_title_is_stem(monkeypatch, tmp_path, fake_vendored):
    video = tmp_path / "2026_08_25T00:00:00.mp4"
    video.write_bytes(b"x")
    seen = {}

    def fake_upload_one(ns, video_path, youtube_upload_main):
        seen["title"] = ns.title
        seen["privacy"] = ns.privacy
        return {"file": str(video_path), "name": video_path.name, "exit_code": 0}

    monkeypatch.setattr(up, "_upload_one_video", fake_upload_one)

    up.upload_video(str(video))
    assert seen["title"] == "2026_08_25T00:00:00"
    assert seen["privacy"] == "private"


def test_upload_video_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        up.upload_video(str(tmp_path / "nope.mp4"))


@pytest.mark.parametrize("suffix", [".mp4", ".mov", ".mkv", ".avi", ".webm", ".3gp"])
def test_upload_video_accepts_supported_formats(monkeypatch, tmp_path, fake_vendored, suffix):
    video = tmp_path / f"clip{suffix}"
    video.write_bytes(b"x")
    seen = {}

    def fake_upload_one(ns, video_path, youtube_upload_main):
        seen["file"] = video_path.as_posix()
        return {"file": video_path.as_posix(), "name": video_path.name, "exit_code": 0, "video_id": "abc"}

    monkeypatch.setattr(up, "_upload_one_video", fake_upload_one)
    result = up.upload_video(str(video))
    assert result["exit_code"] == 0
    assert seen["file"] == video.as_posix()


@pytest.mark.parametrize("suffix", [".txt", ".pdf"])
def test_upload_video_rejects_unsupported_format(tmp_path, suffix):
    video = tmp_path / f"clip{suffix}"
    video.write_bytes(b"x")
    with pytest.raises(ValueError):
        up.upload_video(str(video))


def test_upload_video_rejects_directory(tmp_path):
    with pytest.raises(ValueError):
        up.upload_video(str(tmp_path))


def test_list_video_files_filters_and_sorts(tmp_path):
    for name in ["b.mp4", "a.mov", "c.mkv", "note.txt", ".DS_Store"]:
        (tmp_path / name).write_bytes(b"x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "nested.mp4").write_bytes(b"x")
    names = [p.name for p in up.list_video_files(tmp_path)]
    assert names == ["a.mov", "b.mp4", "c.mkv"]


def test_list_video_files_missing_dir(tmp_path):
    assert up.list_video_files(tmp_path / "nope") == []