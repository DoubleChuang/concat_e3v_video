from PySide6.QtCore import QSettings


class AppSettings(QSettings):
    def __init__(self):
        super().__init__("concat-e3v", "concat-e3v-gui")

    def set_value(self, key: str, value):
        self.setValue(key, value)

    def value(self, key: str, default=None):
        return super().value(key, default)