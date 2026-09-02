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