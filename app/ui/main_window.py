from datetime import datetime, timedelta
from pathlib import Path

import pytz
from PySide6.QtCore import Qt, QDateTime, QTimeZone
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateTimeEdit, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout,
    QWidget,
)

from app.ffmpeg import resolve_ffmpeg
from app.pipeline import PipelineConfig
from app.settings import AppSettings
from app.ui.auth_dialog import AuthDialog
from app.worker import PipelineWorker

TAIPEI = pytz.timezone("Asia/Taipei")


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("concat-e3v")
        self.resize(640, 640)

        self._settings = AppSettings()
        self._ffmpeg_bin = resolve_ffmpeg()
        self._worker: PipelineWorker | None = None

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        form = QFormLayout()
        layout.addLayout(form)

        self.src_edit = QLineEdit()
        src_btn = QPushButton("瀏覽...")
        src_btn.clicked.connect(lambda: self._pick_dir(self.src_edit))
        self.src_edit.textChanged.connect(self._save_src_dir)
        form.addRow("來源目錄:", self._row(self.src_edit, src_btn))

        self.dst_edit = QLineEdit()
        dst_btn = QPushButton("瀏覽...")
        dst_btn.clicked.connect(lambda: self._pick_dir(self.dst_edit))
        self.dst_edit.textChanged.connect(self._save_dst_dir)
        form.addRow("輸出目錄:", self._row(self.dst_edit, dst_btn))

        tz = QTimeZone(b"Asia/Taipei")
        now = QDateTime.currentDateTime()
        self.start_edit = QDateTimeEdit()
        self.start_edit.setTimeZone(tz)
        self.start_edit.setCalendarPopup(True)
        self.start_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.start_edit.setDateTime(QDateTime(now.date(), now.time()).addSecs(-now.time().second()))
        self.end_edit = QDateTimeEdit()
        self.end_edit.setTimeZone(tz)
        self.end_edit.setCalendarPopup(True)
        self.end_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.end_edit.setDateTime(
            QDateTime(now.date(), now.time()).addSecs(3600 - now.time().second())
        )
        form.addRow("開始時間:", self.start_edit)
        form.addRow("結束時間:", self.end_edit)

        self.merge_all_check = QCheckBox("合併成一個檔（忽略時間間隔，全部串成單一 mp4）")
        form.addRow(self.merge_all_check)

        mute_row = QHBoxLayout()
        self.mute_check = QCheckBox("靜音前")
        self.mute_spin = QSpinBox()
        self.mute_spin.setRange(0, 604800)
        self.mute_spin.setSuffix(" 秒")
        mute_row.addWidget(self.mute_check)
        mute_row.addWidget(self.mute_spin)
        mute_row.addStretch()
        form.addRow(mute_row)

        self.upload_group = QGroupBox("上傳到 YouTube")
        self.upload_group.setCheckable(True)
        up_layout = QFormLayout(self.upload_group)
        self.upload_title = QLineEdit()
        self.upload_title.setPlaceholderText("預設 = 檔名")
        up_layout.addRow("標題:", self.upload_title)
        self.upload_desc = QPlainTextEdit()
        self.upload_desc.setMaximumHeight(70)
        up_layout.addRow("描述:", self.upload_desc)
        self.upload_privacy = QComboBox()
        self.upload_privacy.addItem("私人 (private)", "private")
        self.upload_privacy.addItem("不公開 (unlisted)", "unlisted")
        self.upload_privacy.addItem("公開 (public)", "public")
        up_layout.addRow("隱私:", self.upload_privacy)
        self.upload_tags = QLineEdit()
        self.upload_tags.setPlaceholderText("逗號分隔，例如: dashcam, drive")
        up_layout.addRow("標籤:", self.upload_tags)
        self.upload_playlist = QLineEdit()
        up_layout.addRow("播放清單:", self.upload_playlist)
        self.cs_edit = QLineEdit()
        cs_btn = QPushButton("瀏覽...")
        cs_btn.clicked.connect(lambda: self._pick_file(self.cs_edit, "Client Secrets JSON (*.json)"))
        up_layout.addRow("Client Secrets:", self._row(self.cs_edit, cs_btn))
        layout.addWidget(self.upload_group)

        ffmpeg_label = QLabel(
            f"ffmpeg: {self._ffmpeg_bin or '找不到！請確認已安裝或已打包'}"
        )
        layout.addWidget(ffmpeg_label)

        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        layout.addWidget(self.log_edit, 1)

        self.start_btn = QPushButton("開始處理")
        self.start_btn.clicked.connect(self._on_start)
        layout.addWidget(self.start_btn)

        self._load_settings()

    def _row(self, edit: QLineEdit, btn: QPushButton) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(edit, 1)
        lay.addWidget(btn)
        return row

    def _pick_dir(self, edit: QLineEdit):
        path = QFileDialog.getExistingDirectory(self, "選擇目錄", edit.text())
        if path:
            edit.setText(path)

    def _pick_file(self, edit: QLineEdit, filter_: str):
        path, _ = QFileDialog.getOpenFileName(self, "選擇檔案", edit.text(), filter_)
        if path:
            edit.setText(path)

    def _load_settings(self):
        s = self._settings
        self.src_edit.setText(s.value("src_dir", ""))
        self.dst_edit.setText(s.value("dst_dir", ""))
        self.merge_all_check.setChecked(bool(s.value("merge_all", False)))
        self.mute_check.setChecked(int(s.value("mute_seconds", 0)) > 0)
        self.mute_spin.setValue(int(s.value("mute_seconds", 0)))
        self.upload_group.setChecked(bool(s.value("upload_enabled", False)))
        self.upload_title.setText(s.value("upload_title", ""))
        self.upload_desc.setPlainText(s.value("upload_description", ""))
        idx = self.upload_privacy.findData(s.value("upload_privacy", "private"))
        self.upload_privacy.setCurrentIndex(max(idx, 0))
        self.upload_tags.setText(s.value("upload_tags", ""))
        self.upload_playlist.setText(s.value("upload_playlist", ""))
        self.cs_edit.setText(s.value("client_secrets", ""))
        saved_start = s.value("start_time", "")
        if saved_start:
            self.start_edit.setDateTime(QDateTime.fromString(saved_start, Qt.ISODate))
        saved_end = s.value("end_time", "")
        if saved_end:
            self.end_edit.setDateTime(QDateTime.fromString(saved_end, Qt.ISODate))

    def _save_settings(self):
        s = self._settings
        s.set_value("src_dir", self.src_edit.text())
        s.set_value("dst_dir", self.dst_edit.text())
        s.set_value("merge_all", self.merge_all_check.isChecked())
        s.set_value("mute_seconds", self.mute_spin.value() if self.mute_check.isChecked() else 0)
        s.set_value("upload_enabled", self.upload_group.isChecked())
        s.set_value("upload_title", self.upload_title.text())
        s.set_value("upload_description", self.upload_desc.toPlainText())
        s.set_value("upload_privacy", self.upload_privacy.currentData())
        s.set_value("upload_tags", self.upload_tags.text())
        s.set_value("upload_playlist", self.upload_playlist.text())
        s.set_value("client_secrets", self.cs_edit.text())
        s.set_value("start_time", self.start_edit.dateTime().toString(Qt.ISODate))
        s.set_value("end_time", self.end_edit.dateTime().toString(Qt.ISODate))

    def _save_src_dir(self, _text):
        self._settings.set_value("src_dir", self.src_edit.text())

    def _save_dst_dir(self, _text):
        self._settings.set_value("dst_dir", self.dst_edit.text())

    def _validate(self) -> list[str]:
        errors = []
        src = self.src_edit.text().strip()
        dst = self.dst_edit.text().strip()
        if not src or not Path(src).is_dir():
            errors.append("來源目錄不存在")
        if not dst:
            errors.append("輸出目錄未填")
        start = self.start_edit.dateTime().toPython()
        end = self.end_edit.dateTime().toPython()
        if start >= end:
            errors.append("開始時間必須早於結束時間")
        if self._ffmpeg_bin is None:
            errors.append("找不到 ffmpeg")
        return errors

    def _build_cfg(self) -> PipelineConfig:
        tz = pytz.timezone("Asia/Taipei")
        start = self.start_edit.dateTime().toPython().astimezone(tz)
        end = self.end_edit.dateTime().toPython().astimezone(tz)
        return PipelineConfig(
            src_dir=self.src_edit.text().strip(),
            dst_dir=self.dst_edit.text().strip(),
            start_time=start,
            end_time=end,
            merge_all=self.merge_all_check.isChecked(),
            mute_seconds=self.mute_spin.value() if self.mute_check.isChecked() else 0,
            ffmpeg_bin=self._ffmpeg_bin or "ffmpeg",
            upload_enabled=self.upload_group.isChecked(),
            upload_title=self.upload_title.text().strip() or None,
            upload_description=self.upload_desc.toPlainText().strip() or None,
            upload_privacy=self.upload_privacy.currentData(),
            upload_tags=self.upload_tags.text().strip() or None,
            upload_playlist=self.upload_playlist.text().strip() or None,
            client_secrets=self.cs_edit.text().strip() or None,
        )

    def _on_start(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self.log_edit.appendPlainText("已送出停止要求...")
            return
        errors = self._validate()
        if errors:
            QMessageBox.warning(self, "輸入錯誤", "\n".join(errors))
            return
        self._save_settings()
        cfg = self._build_cfg()
        self.log_edit.clear()
        self.log_edit.appendPlainText("開始處理...")
        self._worker = PipelineWorker(cfg, parent=self)
        self._worker.log.connect(self.log_edit.appendPlainText)
        self._worker.finished.connect(self._on_finished)
        self._worker.auth_required.connect(self._on_auth_required)
        self._worker.auth_code_required.connect(self._on_auth_code_required)
        self.start_btn.setText("停止")
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
        self.start_btn.setText("開始處理")
        status = result.get("status")
        if status == "done":
            self.log_edit.appendPlainText("處理完成")
            uploaded = result.get("upload_results", [])
            for r in uploaded:
                if r.get("exit_code") == 0:
                    self.log_edit.appendPlainText(f"已上傳: {r.get('file')} -> {r.get('video_id')}")
                else:
                    self.log_edit.appendPlainText(f"上傳失敗: {r.get('file')} ({r.get('error')})")
            QMessageBox.information(self, "完成", "處理完成")
        elif status == "aborted":
            self.log_edit.appendPlainText(f"已中止: {result.get('reason')}")
        else:
            self.log_edit.appendPlainText(f"處理失敗: {result.get('reason')}")
            QMessageBox.critical(self, "失敗", str(result.get("reason")))