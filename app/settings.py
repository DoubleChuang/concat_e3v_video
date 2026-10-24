from PySide6.QtCore import QSettings


class AppSettings(QSettings):
    def __init__(self, format: QSettings.Format = QSettings.NativeFormat):
        super().__init__(format, QSettings.UserScope, "concat-e3v", "concat-e3v-gui")

    def set_value(self, key: str, value):
        self.setValue(key, value)

    def value(self, key: str, default=None):
        return super().value(key, default)


def get_upload_history_file(s: AppSettings) -> str:
    from upload_mp4_to_youtube import UPLOAD_HISTORY_DEFAULT

    return str(s.value("upload_history_file", "") or UPLOAD_HISTORY_DEFAULT.as_posix())


def as_bool(value, default: bool = False) -> bool:
    """QSettings stores bools as strings (IniFormat especially); normalise here."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def get_bool(s: AppSettings, key: str, default: bool = False) -> bool:
    return as_bool(s.value(key, default), default)