from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QLineEdit,
    QPushButton, QVBoxLayout,
)


class AuthDialog(QDialog):
    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("YouTube 授權")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("請在瀏覽器中開啟以下連結並登入授權："))
        url_edit = QLineEdit(url)
        url_edit.setReadOnly(True)
        layout.addWidget(url_edit)

        open_btn = QPushButton("在瀏覽器開啟")
        open_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(url))
        )
        layout.addWidget(open_btn)

        layout.addWidget(QLabel("授權後請將驗證碼貼到下方："))
        self._code_edit = QLineEdit()
        self._code_edit.setPlaceholderText("驗證碼")
        layout.addWidget(self._code_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._code_edit.setFocus()

    def code(self) -> str:
        return self._code_edit.text().strip()