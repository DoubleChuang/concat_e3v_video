from pathlib import Path

from app.ui.upload_window import parse_pasted_paths, resolve_pasted_paths


def test_parse_pasted_paths_newline(tmp_path):
    a, b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    assert parse_pasted_paths(f"{a}\n{b}") == [str(a), str(b)]


def test_parse_pasted_paths_comma_and_quotes(tmp_path):
    a, b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    raw = f'"{a}", \'{b}\''
    assert parse_pasted_paths(raw) == [str(a), str(b)]


def test_parse_pasted_paths_expanduser_and_blanks():
    assert parse_pasted_paths("  \n ~ \n\n /tmp/x.mp4 ") == [
        str(Path.home()),
        "/tmp/x.mp4",
    ]


def test_resolve_pasted_paths(tmp_path):
    ok = tmp_path / "a.mp4"
    ok.write_bytes(b"x")
    txt = tmp_path / "b.txt"
    txt.write_bytes(b"x")
    missing = tmp_path / "nope.mp4"
    valid, invalid = resolve_pasted_paths(f"{ok}\n{txt}\n{missing}")
    assert valid == [ok]
    reasons = {p: r for p, r in invalid}
    assert reasons[str(txt)] == "不支援的格式"
    assert reasons[str(missing)] == "檔案不存在"