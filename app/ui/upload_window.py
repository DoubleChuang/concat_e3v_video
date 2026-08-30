from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFileDialog, QFormLayout,
    QHBoxLayout, QLineEdit, QListWidget, QMessageBox, QPlainTextEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from app.settings import AppSettings
from app.ui.auth_dialog import AuthDialog
from app.upload_worker import UploadConfig, UploadWorker
from upload_mp4_to_youtube import SUPPORTED_VIDEO_EXTENSIONS, list_video_files


def _file_dialog_filter() -> str:
    exts = " ".join(sorted(SUPPORTED_VIDEO_EXTENSIONS))
    return f"影片 ({exts})"


class UploadWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("上傳到 YouTube")
        self.resize(560, 560)
        self._settings = AppSettings()
        self._worker: UploadWorker | None = None
        self._uploading = False

        layout = QVBoxLayout(self)

        pick_row = QHBoxLayout()
        self.files_btn = QPushButton("選擇檔案...")
        self.files_btn.clicked.connect(self._pick_files)
        self.dir_btn = QPushButton("選擇資料夾...")
        self.dir_btn.clicked.connect(self._pick_dir)
        pick_row.addWidget(self.files_btn)
        pick_row.addWidget(self.dir_btn)
        pick_row.addStretch()
        layout.addLayout(pick_row)

        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        layout.addWidget(self.file_list)

        remove_row = QHBoxLayout()
        self.remove_btn = QPushButton("移除選取")
        self.remove_btn.clicked.connect(self._remove_selected)
        self.clear_btn = QPushButton("清空")
        self.clear_btn.clicked.connect(self.file_list.clear)
        remove_row.addWidget(self.remove_btn)
        remove_row.addWidget(self.clear_btn)
        remove_row.addStretch()
        layout.addLayout(remove_row)

        form = QFormLayout()
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("預設 = 檔名")
        form.addRow("標題:", self.title_edit)
        self.desc_edit = QPlainTextEdit()
        self.desc_edit.setMaximumHeight(70)
        form.addRow("描述:", self.desc_edit)
        self.privacy_combo = QComboBox()
        self.privacy_combo.addItem("私人 (private)", "private")
        self.privacy_combo.addItem("不公開 (unlisted)", "unlisted")
        self.privacy_combo.addItem("公開 (public)", "public")
        form.addRow("隱私:", self.privacy_combo)
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("逗號分隔，例如: dashcam, drive")
        form.addRow("標籤:", self.tags_edit)
        self.playlist_edit = QLineEdit()
        form.addRow("播放清單:", self.playlist_edit)
        self.cs_edit = QLineEdit()
        cs_btn = QPushButton("瀏覽...")
        cs_btn.clicked.connect(self._pick_client_secrets)
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.cs_edit, 1)
        lay.addWidget(cs_btn)
        form.addRow("Client Secrets:", row)
        layout.addLayout(form)

        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        layout.addWidget(self.log_edit, 1)

        self.upload_btn = QPushButton("上傳")
        self.upload_btn.clicked.connect(self._on_upload)
        layout.addWidget(self.upload_btn)

        self._load_settings()

    def _pick_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "選擇影片", "", _file_dialog_filter()
        )
        self._add_paths(paths)

    def _pick_dir(self):
        path = QFileDialog.getExistingDirectory(self, "選擇資料夾")
        if not path:
            return
        self._add_paths([p.as_posix() for p in list_video_files(path)])

    def _add_paths(self, paths):
        existing = set(self._paths())
        for p in paths:
            if p not in existing:
                self.file_list.addItem(p)
                existing.add(p)

    def _paths(self) -> list[str]:
        return [
            self.file_list.item(i).text()
            for i in range(self.file_list.count())
        ]

    def _remove_selected(self):
        for item in self.file_list.selectedItems():
            self.file_list.takeItem(self.file_list.row(item))

    def _pick_client_secrets(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "選擇 Client Secrets", self.cs_edit.text(),
            "Client Secrets JSON (*.json)",
        )
        if path:
            self.cs_edit.setText(path)

    def _load_settings(self):
        s = self._settings
        self.title_edit.setText(s.value("upload_title", ""))
        self.desc_edit.setPlainText(s.value("upload_description", ""))
        idx = self.privacy_combo.findData(s.value("upload_privacy", "private"))
        self.privacy_combo.setCurrentIndex(max(idx, 0))
        self.tags_edit.setText(s.value("upload_tags", ""))
        self.playlist_edit.setText(s.value("upload_playlist", ""))
        self.cs_edit.setText(s.value("client_secrets", ""))

    def _save_settings(self):
        s = self._settings
        s.set_value("upload_title", self.title_edit.text())
        s.set_value("upload_description", self.desc_edit.toPlainText())
        s.set_value("upload_privacy", self.privacy_combo.currentData())
        s.set_value("upload_tags", self.tags_edit.text())
        s.set_value("upload_playlist", self.playlist_edit.text())
        s.set_value("client_secrets", self.cs_edit.text())

    def _on_upload(self):
        if self._uploading:
            self._worker.cancel()
            self.log_edit.appendPlainText("已送出停止要求...")
            return
        files = self._paths()
        if not files:
            QMessageBox.warning(self, "輸入錯誤", "請先選擇檔案")
            return
        self._save_settings()
        self.log_edit.clear()
        self.log_edit.appendPlainText("開始上傳...")
        cfg = UploadConfig(
            files=files,
            title=self.title_edit.text().strip() or None,
            description=self.desc_edit.toPlainText().strip() or None,
            privacy=self.privacy_combo.currentData(),
            tags=self.tags_edit.text().strip() or None,
            playlist=self.playlist_edit.text().strip() or None,
            client_secrets=self.cs_edit.text().strip() or None,
        )
        self._worker = UploadWorker(cfg, parent=self)
        self._worker.log.connect(self.log_edit.appendPlainText)
        self._worker.finished.connect(self._on_finished)
        self._worker.auth_required.connect(self._on_auth_required)
        self._worker.auth_code_required.connect(self._on_auth_code_required)
        self.upload_btn.setText("停止")
        self._uploading = True
        self._worker.start()

    def _on_auth_required(self, message: str):
        answer = QMessageBox.question(
            self, "YouTube 授權失敗",
            f"無法驗證 YouTube 權限或憑證已過期：\n{message}\n\n要重新授權嗎？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer == QMessageBox.Yes and self._worker is not None:
            self._worker.retry_auth()
        elif self._worker is not None:
            self._worker.cancel()

    def _on_auth_code_required(self, url: str):
        dialog = AuthDialog(url, self)
        if dialog.exec() == AuthDialog.Accepted and self._worker is not None:
            self._worker.submit_auth_code(dialog.code())
        elif self._worker is not None:
            self._worker.cancel()

    def _on_finished(self, result: dict):
        if self._worker is not self.sender():
            return
        self._uploading = False
        self.upload_btn.setText("上傳")
        status = result.get("status")
        uploaded = result.get("uploaded", [])
        failed = result.get("failed", [])
        if status == "done":
            self.log_edit.appendPlainText("上傳完成")
            for r in uploaded:
                self.log_edit.appendPlainText(
                    f"已上傳: {r.get('file')} -> {r.get('video_id')}"
                )
            for r in failed:
                self.log_edit.appendPlainText(
                    f"上傳失敗: {r.get('file')} ({r.get('error')})"
                )
            if failed:
                QMessageBox.warning(
                    self, "部分失敗",
                    f"成功 {len(uploaded)} 個，失敗 {len(failed)} 個",
                )
            else:
                QMessageBox.information(
                    self, "完成", f"成功上傳 {len(uploaded)} 個影片"
                )
        elif status == "aborted":
            self.log_edit.appendPlainText(f"已中止: {result.get('reason')}")
        else:
            self.log_edit.appendPlainText(f"上傳失敗: {result.get('reason')}")
            QMessageBox.critical(self, "失敗", str(result.get("reason")))

    def closeEvent(self, event):
        if self._uploading:
            self._worker.cancel()
            self._worker.wait(5000)
            if self._uploading:
                event.ignore()
                return
        super().closeEvent(event)
