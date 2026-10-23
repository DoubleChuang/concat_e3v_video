"""更新相關的對話框。

只負責顯示與取得使用者決定，不碰網路；流程由 :mod:`app.ui.update_presenter` 控制。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
)

from app.updater.service import CheckResult


class UpdateAvailableDialog(QDialog):
    """顯示新版本資訊；``choice`` 為 ``update`` / ``later`` / ``page``。"""

    def __init__(
        self,
        result: CheckResult,
        can_self_update: bool,
        parent=None,
    ) -> None:
        super().__init__(parent)
        assert result.release is not None
        self.choice = "later"
        self.setWindowTitle("發現新版本")
        self.resize(520, 380)

        layout = QVBoxLayout(self)
        release = result.release
        title = QLabel(f"有新版本 v{release.version}（目前 v{result.current}）")
        title.setWordWrap(True)
        font = title.font()
        font.setPointSize(font.pointSize() + 2)
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)

        if not can_self_update:
            hint = QLabel(
                "這個執行方式不支援自動替換，按下「前往下載頁面」手動下載新版本。"
            )
            hint.setWordWrap(True)
            layout.addWidget(hint)

        notes = QPlainTextEdit()
        notes.setReadOnly(True)
        notes.setPlainText(release.notes.strip() or "（這個版本沒有更新說明）")
        layout.addWidget(notes, 1)

        buttons = QDialogButtonBox(self)
        self.update_btn = buttons.addButton(
            "下載並更新" if can_self_update else "前往下載頁面",
            QDialogButtonBox.AcceptRole,
        )
        self.later_btn = buttons.addButton("稍後", QDialogButtonBox.RejectRole)
        self.update_btn.clicked.connect(self._accept)
        self.later_btn.clicked.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self) -> None:
        self.choice = "update" if self.update_btn.text() == "下載並更新" else "page"
        self.accept()


class DownloadProgressDialog(QDialog):
    """下載中不可關閉，避免留下半個檔案。"""

    def __init__(self, version: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("下載更新")
        self.setModal(True)
        self.setFixedWidth(420)
        self.setWindowFlag(Qt.WindowCloseButtonHint, False)

        layout = QVBoxLayout(self)
        self.label = QLabel(f"正在下載 v{version}…")
        self.label.setWordWrap(True)
        layout.addWidget(self.label)

        self.bar = QProgressBar()
        self.bar.setRange(0, 0)  # 總量未知時先跑 indeterminate
        layout.addWidget(self.bar)

    def set_progress(self, received: int, total: int) -> None:
        if total > 0:
            self.bar.setRange(0, total)
            self.bar.setValue(min(received, total))
            self.label.setText(
                f"正在下載… {received / 1048576:.1f} / {total / 1048576:.1f} MB"
            )
        else:
            self.label.setText(f"正在下載… {received / 1048576:.1f} MB")

    def closeEvent(self, event):  # noqa: N802 - Qt 命名
        event.ignore()
