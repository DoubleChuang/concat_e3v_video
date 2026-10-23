import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

import app.ui.update_presenter as presenter_module
from app.updater.errors import ReleaseLookupError
from app.updater.models import Asset, InstallOutcome, Release
from app.updater.service import UpdateService
from app.updater.targets import parse_target
from app.updater.version import Version
from app.ui.update_presenter import UpdatePresenter


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class FakeSource:
    def __init__(self, release=None, error=None):
        self.release = release
        self.error = error

    def latest(self):
        if self.error is not None:
            raise self.error
        return self.release


class FakeDownloader:
    def __init__(self):
        self.calls = []

    def download(self, asset, destination, on_progress=None):
        self.calls.append(asset.name)
        destination.write_bytes(b"payload")
        if on_progress is not None:
            on_progress(4, 8)
            on_progress(8, 8)
        return destination


class FakeInstaller:
    def __init__(self, can_install=True, outcome=None):
        self._can = can_install
        self.outcome = outcome or InstallOutcome(
            applied=True, restart_required=True, relaunch=("/opt/concat-e3v",)
        )
        self.installed = []

    def can_install(self):
        return self._can

    def install(self, artifact, plan):
        self.installed.append((artifact, plan))
        return self.outcome


class FakeCheckWorker(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self._service = service

    def start(self):
        try:
            self.succeeded.emit(self._service.check())
        except Exception as exc:
            self.failed.emit(str(exc))
        self.finished.emit()


class FakeApplyWorker(QObject):
    progress = Signal(int, int)
    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, service, plan, parent=None):
        super().__init__(parent)
        self._service = service
        self._plan = plan

    def isRunning(self):  # noqa: N802 - 模擬 QThread
        return False

    def start(self):
        try:
            artifact = self._service.download(self._plan, self.progress.emit)
            self.succeeded.emit(self._service.apply(self._plan, artifact))
        except Exception as exc:
            self.failed.emit(str(exc))
        self.finished.emit()


class FakeMessageBox:
    infos = []
    warnings = []

    @classmethod
    def information(cls, *args, **kwargs):
        cls.infos.append(args)

    @classmethod
    def warning(cls, *args, **kwargs):
        cls.warnings.append(args)

    @classmethod
    def reset(cls):
        cls.infos = []
        cls.warnings = []


class FakeAvailableDialog:
    next_choice = "update"
    instances = []

    def __init__(self, result, can_self_update, parent=None):
        self.result = result
        self.can_self_update = can_self_update
        self.choice = FakeAvailableDialog.next_choice
        FakeAvailableDialog.instances.append(self)

    def exec(self):
        return 1


class FakeProgressDialog:
    last = None

    def __init__(self, version, parent=None):
        self.version = version
        self.progress = []
        self.closed = False
        FakeProgressDialog.last = self

    def show(self):
        pass

    def close(self):
        self.closed = True

    def set_progress(self, received, total):
        self.progress.append((received, total))


class FakeDesktopServices:
    opened = []

    @classmethod
    def openUrl(cls, url):
        cls.opened.append(url.toString())


@pytest.fixture(autouse=True)
def patch_ui(monkeypatch):
    FakeMessageBox.reset()
    FakeAvailableDialog.instances = []
    FakeAvailableDialog.next_choice = "update"
    FakeProgressDialog.last = None
    FakeDesktopServices.opened = []
    monkeypatch.setattr(presenter_module, "UpdateCheckWorker", FakeCheckWorker)
    monkeypatch.setattr(presenter_module, "UpdateApplyWorker", FakeApplyWorker)
    monkeypatch.setattr(presenter_module, "QMessageBox", FakeMessageBox)
    monkeypatch.setattr(presenter_module, "UpdateAvailableDialog", FakeAvailableDialog)
    monkeypatch.setattr(presenter_module, "DownloadProgressDialog", FakeProgressDialog)
    monkeypatch.setattr(presenter_module, "QDesktopServices", FakeDesktopServices)


def _release(version="0.0.9", assets=("concat-e3v-linux-x86_64",)):
    return Release(
        version=Version.parse(version),
        tag=f"v{version}",
        notes="更新說明",
        page_url="https://example.test/release",
        assets=tuple(
            Asset(name=name, url=f"https://example.test/{name}", size=8)
            for name in assets
        ),
    )


def _presenter(tmp_path, release=None, error=None, installer=None, downloader=None):
    service = UpdateService(
        current_version=Version.parse("0.0.8"),
        target=parse_target("linux", "x86_64"),
        source=FakeSource(release, error),
        downloader=downloader or FakeDownloader(),
        installer=installer or FakeInstaller(),
        download_dir=tmp_path,
    )
    return UpdatePresenter(service)


def test_up_to_date_manual_check_shows_information(qapp, tmp_path):
    presenter = _presenter(tmp_path, _release("0.0.8"))
    presenter.check(None, manual=True)
    assert "已是最新版本" in FakeMessageBox.infos[-1][1]
    assert presenter.busy is False


def test_up_to_date_auto_check_is_silent(qapp, tmp_path):
    presenter = _presenter(tmp_path, _release("0.0.8"))
    presenter.check(None, manual=False)
    assert FakeMessageBox.infos == []


def test_check_error_is_silent_when_auto(qapp, tmp_path):
    presenter = _presenter(tmp_path, error=ReleaseLookupError("離線"))
    presenter.check(None, manual=False)
    assert FakeMessageBox.warnings == []


def test_check_error_is_reported_when_manual(qapp, tmp_path):
    presenter = _presenter(tmp_path, error=ReleaseLookupError("離線"))
    presenter.check(None, manual=True)
    assert "檢查更新失敗" in FakeMessageBox.warnings[-1][1]


def test_unsupported_platform_opens_release_page(qapp, tmp_path):
    presenter = _presenter(tmp_path, _release("0.0.9", assets=("other",)))
    presenter.check(None, manual=True)
    assert "沒有對應的更新檔" in FakeMessageBox.infos[-1][1]
    assert FakeDesktopServices.opened[-1] == "https://example.test/release"


def test_update_flow_downloads_applies_and_restarts(qapp, tmp_path, monkeypatch):
    installer = FakeInstaller()
    dialog_parent = FakeProgressDialog
    quit_calls = []
    detached = []
    monkeypatch.setattr(qapp, "quit", lambda: quit_calls.append(1))
    monkeypatch.setattr(
        presenter_module.QProcess,
        "startDetached",
        staticmethod(lambda program, args: detached.append((program, args)) or True),
    )

    presenter = _presenter(tmp_path, _release("0.0.9"), installer=installer)
    presenter.check(None, manual=True)

    assert FakeAvailableDialog.instances[-1].can_self_update is True
    assert len(installer.installed) == 1
    assert dialog_parent.last.progress == [(4, 8), (8, 8)]
    assert dialog_parent.last.closed is True
    assert detached == [("/opt/concat-e3v", [])]
    assert quit_calls == [1]
    assert "更新完成" in FakeMessageBox.infos[-1][1]


def test_update_dialog_choice_page_does_not_download(qapp, tmp_path):
    FakeAvailableDialog.next_choice = "page"
    installer = FakeInstaller()
    presenter = _presenter(tmp_path, _release("0.0.9"), installer=installer)
    presenter.check(None, manual=True)
    assert installer.installed == []
    assert FakeDesktopServices.opened[-1] == "https://example.test/release"


def test_manual_fallback_reveals_downloaded_file(qapp, tmp_path):
    outcome = InstallOutcome(
        applied=False,
        manual_fallback=True,
        message="請手動解壓縮",
        artifact_path=str(tmp_path / "downloaded.app.zip"),
    )
    presenter = _presenter(
        tmp_path, _release("0.0.9"), installer=FakeInstaller(outcome=outcome)
    )
    presenter.check(None, manual=True)
    assert "請手動完成更新" in FakeMessageBox.infos[-1][1]
    assert FakeDesktopServices.opened[-1].startswith("file://")


def test_apply_failure_shows_warning(qapp, tmp_path):
    class BrokenInstaller(FakeInstaller):
        def install(self, artifact, plan):
            raise ReleaseLookupError("壞掉了")

    presenter = _presenter(tmp_path, _release("0.0.9"), installer=BrokenInstaller())
    presenter.check(None, manual=True)
    assert "更新失敗" in FakeMessageBox.warnings[-1][1]
    assert presenter.busy is False
