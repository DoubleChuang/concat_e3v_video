from pathlib import Path
from app.settings import AppSettings


def test_settings_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    s = AppSettings()
    s.set_value("src_dir", "/tmp/src")
    s2 = AppSettings()
    assert s2.value("src_dir") == "/tmp/src"


def test_settings_default(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    s = AppSettings()
    assert s.value("merge_all", False) is False