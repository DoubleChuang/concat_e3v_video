"""Dialogs for the update flow.

They only display information and collect the user's decision; no network. The
flow itself is driven by :mod:`app.ui.update_presenter`.
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
    """Show the new version; ``choice`` is ``update`` / ``later`` / ``page``."""

    def __init__(
        self,
        result: CheckResult,
        can_self_update: bool,
        parent=None,
    ) -> None:
        super().__init__(parent)
        if result.release is None:
            raise ValueError("UpdateAvailableDialog needs a CheckResult with a release")
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
        self._can_self_update = can_self_update
        self.update_btn = buttons.addButton(
            "下載並更新" if can_self_update else "前往下載頁面",
            QDialogButtonBox.AcceptRole,
        )
        self.later_btn = buttons.addButton("稍後", QDialogButtonBox.RejectRole)
        self.update_btn.clicked.connect(self._on_update_clicked)
        self.later_btn.clicked.connect(self.reject)
        layout.addWidget(buttons)

    def _on_update_clicked(self) -> None:
        self.choice = "update" if self._can_self_update else "page"
        self.accept()


class DownloadProgressDialog(QDialog):
    """Cannot be closed while downloading, so no half-written file is left behind."""

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
        self.bar.setRange(0, 0)  # indeterminate until the total size is known
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

    def closeEvent(self, event):  # noqa: N802 - Qt naming
        event.ignore()
