from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from app.settings import AppSettings
from app.ui.update_menu import attach_help_menu
from app.ui.update_presenter import UpdatePresenter, build_default_presenter
from upload_mp4_to_youtube import UPLOAD_HISTORY_DEFAULT


class HomeWindow(QWidget):
    e3v_requested = Signal()
    upload_requested = Signal()

    def __init__(self, parent=None, updater: UpdatePresenter | None = None):
        super().__init__(parent)
        self.setWindowTitle("concat-e3v")
        self.resize(480, 320)
        self._settings = AppSettings()
        self.quit_guard = None
        self._updater = updater or build_default_presenter(self)

        layout = QVBoxLayout(self)

        title = QLabel("concat-e3v")
        title.setAlignment(Qt.AlignCenter)
        font = title.font()
        font.setPointSize(24)
        title.setFont(font)
        layout.addWidget(title)

        self.e3v_btn = QPushButton("處理E3V影片")
        self.e3v_btn.setMinimumHeight(56)
        self.e3v_btn.clicked.connect(lambda: self.e3v_requested.emit())
        layout.addWidget(self.e3v_btn)

        self.upload_btn = QPushButton("單獨上傳影片")
        self.upload_btn.setMinimumHeight(56)
        self.upload_btn.clicked.connect(lambda: self.upload_requested.emit())
        layout.addWidget(self.upload_btn)

        form = QFormLayout()
        self.history_edit = QLineEdit()
        self.history_edit.setPlaceholderText(f"預設: {UPLOAD_HISTORY_DEFAULT}")
        self.history_edit.textChanged.connect(self._save_history_file)
        history_btn = QPushButton("瀏覽...")
        history_btn.clicked.connect(self._pick_history_file)
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.history_edit, 1)
        lay.addWidget(history_btn)
        form.addRow("紀錄檔:", row)
        layout.addLayout(form)

        layout.addStretch()

        self.help_menu = attach_help_menu(self, self._updater, self._settings)

        self._load_settings()

    def _pick_history_file(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "選擇上傳紀錄檔",
            self.history_edit.text() or str(Path.home()),
            "JSON (*.json)",
        )
        if path:
            self.history_edit.setText(path)

    def _save_history_file(self, _text):
        self._settings.set_value(
            "upload_history_file", self.history_edit.text()
        )

    def _load_settings(self):
        self.history_edit.setText(
            self._settings.value("upload_history_file", "")
        )

    def closeEvent(self, event):
        if self.quit_guard is not None and self.quit_guard():
            QMessageBox.warning(self, "處理中", "請先取消或等待處理完成")
            event.ignore()
            return
        QApplication.instance().quit()
        super().closeEvent(event)