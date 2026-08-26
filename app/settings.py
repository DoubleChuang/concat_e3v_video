from PySide6.QtCore import QSettings


class AppSettings(QSettings):
    def __init__(self, format: QSettings.Format = QSettings.NativeFormat):
        super().__init__(format, QSettings.UserScope, "concat-e3v", "concat-e3v-gui")

    def set_value(self, key: str, value):
        self.setValue(key, value)

    def value(self, key: str, default=None):
        return super().value(key, default)