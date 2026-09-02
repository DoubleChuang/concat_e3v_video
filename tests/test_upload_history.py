import json
import sys

import pytest
import upload_mp4_to_youtube as up


def test_build_history_record_success():
    rec = up.build_history_record(
        {"file": "/tmp/a.mp4", "exit_code": 0, "video_id": "abc123"}
    )
    assert rec["status"] == "success"
    assert rec["youtube_url"] == "https://youtu.be/abc123"
    assert rec["file"] == "/tmp/a.mp4"
    assert rec["timestamp"]


def test_build_history_record_failed_with_error():
    rec = up.build_history_record(
        {"file": "/tmp/a.mp4", "exit_code": 1, "error": "boom"}
    )
    assert rec["status"] == "failed"
    assert rec["error"] == "boom"
    assert "youtube_url" not in rec


def test_build_history_record_failed_fallback_error():
    rec = up.build_history_record({"file": "/tmp/a.mp4", "exit_code": 2})
    assert rec["status"] == "failed"
    assert rec["error"] == "exit code 2"


def test_append_upload_history_creates_file(tmp_path):
    out = tmp_path / "h.json"
    up.append_upload_history(
        out, [{"file": "/a.mp4", "status": "success", "timestamp": "t1"}]
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data == {
        "uploads": [{"file": "/a.mp4", "status": "success", "timestamp": "t1"}]
    }


def test_append_upload_history_appends_and_keeps_old(tmp_path):
    out = tmp_path / "h.json"
    up.append_upload_history(
        out, [{"file": "/a.mp4", "status": "success", "timestamp": "t1"}]
    )
    up.append_upload_history(
        out,
        [{"file": "/b.mp4", "status": "failed", "error": "x", "timestamp": "t2"}],
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    assert [u["file"] for u in data["uploads"]] == ["/a.mp4", "/b.mp4"]


def test_append_upload_history_corrupt_file_treated_as_empty(tmp_path):
    out = tmp_path / "h.json"
    out.write_text("not json", encoding="utf-8")
    up.append_upload_history(
        out, [{"file": "/a.mp4", "status": "success", "timestamp": "t1"}]
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data["uploads"]) == 1


def test_append_upload_history_empty_records_noop(tmp_path):
    out = tmp_path / "h.json"
    up.append_upload_history(out, [])
    assert not out.exists()


def test_cli_main_writes_history(monkeypatch, tmp_path):
    cs = tmp_path / "cs.json"
    cs.write_text("{}", encoding="utf-8")
    video = tmp_path / "a.mp4"
    video.write_bytes(b"x")
    history = tmp_path / "h.json"
    log_file = tmp_path / "up.log"

    def fake_check(*a, **kw):
        return None

    def fake_upload_one(ns, video_path, youtube_upload_main):
        return {
            "file": video_path.as_posix(),
            "name": video_path.name,
            "exit_code": 0,
            "video_id": "v1",
        }

    monkeypatch.setattr(up, "check_youtube_upload_available", fake_check)
    monkeypatch.setattr(up, "_upload_one_video", fake_upload_one)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "upload_mp4_to_youtube.py",
            str(video),
            "--client-secrets",
            str(cs),
            "--history-file",
            str(history),
            "--log-file",
            str(log_file),
        ],
    )

    rc = up.main()
    assert rc == 0
    data = json.loads(history.read_text(encoding="utf-8"))
    assert len(data["uploads"]) == 1
    assert data["uploads"][0]["status"] == "success"
    assert data["uploads"][0]["youtube_url"] == "https://youtu.be/v1"