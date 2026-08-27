from PySide6.QtCore import QSettings
from app.settings import AppSettings


def _isolated_settings(tmp_path) -> AppSettings:
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    return AppSettings(QSettings.IniFormat)


def test_settings_roundtrip(tmp_path):
    s = _isolated_settings(tmp_path)
    s.set_value("src_dir", "/tmp/src")
    s2 = _isolated_settings(tmp_path)
    assert s2.value("src_dir") == "/tmp/src"


def test_settings_default(tmp_path):
    s = _isolated_settings(tmp_path)
    assert s.value("merge_all", False) is False