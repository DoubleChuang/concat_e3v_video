import pytest

from app.updater.models import Asset, InstallOutcome, Release, UpdatePlan
from app.updater.service import CheckStatus, UpdateService
from app.updater.targets import parse_target
from app.updater.version import Version


class FakeSource:
    def __init__(self, release: Release):
        self._release = release
        self.calls = 0

    def latest(self) -> Release:
        self.calls += 1
        return self._release


class FakeDownloader:
    def __init__(self):
        self.calls = []

    def download(self, asset, destination, on_progress=None):
        self.calls.append((asset, destination))
        destination.write_bytes(b"payload")
        if on_progress is not None:
            on_progress(len(b"payload"), len(b"payload"))
        return destination


class FakeInstaller:
    def __init__(self, can_install: bool = True):
        self._can_install = can_install
        self.installed = []

    def can_install(self) -> bool:
        return self._can_install

    def install(self, artifact, plan):
        self.installed.append((artifact, plan))
        return InstallOutcome(applied=True, restart_required=True)


def _release(version: str, assets=("concat-e3v-linux-x86_64",)) -> Release:
    return Release(
        version=Version.parse(version),
        tag=f"v{version}",
        notes="notes",
        page_url="https://example.test/release",
        assets=tuple(
            Asset(name=name, url=f"https://example.test/{name}", size=7)
            for name in assets
        ),
    )


def _service(tmp_path, release, target=None, installer=None, downloader=None):
    return UpdateService(
        current_version=Version.parse("0.0.8"),
        target=target or parse_target("linux", "x86_64"),
        source=FakeSource(release),
        downloader=downloader or FakeDownloader(),
        installer=installer or FakeInstaller(),
        download_dir=tmp_path,
    )


def test_check_reports_up_to_date_for_same_version(tmp_path):
    result = _service(tmp_path, _release("0.0.8")).check()
    assert result.status is CheckStatus.UP_TO_DATE
    assert result.update_available is False
    assert result.plan is None


def test_check_reports_up_to_date_for_older_release(tmp_path):
    result = _service(tmp_path, _release("0.0.7")).check()
    assert result.status is CheckStatus.UP_TO_DATE


def test_check_builds_plan_for_newer_release(tmp_path):
    result = _service(tmp_path, _release("0.0.9")).check()
    assert result.status is CheckStatus.UPDATE_AVAILABLE
    assert result.plan is not None
    assert result.plan.asset.name == "concat-e3v-linux-x86_64"
    assert str(result.plan.current) == "0.0.8"
    assert str(result.plan.release.version) == "0.0.9"


def test_check_reports_unsupported_platform_when_asset_missing(tmp_path):
    result = _service(
        tmp_path,
        _release("0.0.9"),
        target=parse_target("linux", "aarch64"),
    ).check()
    assert result.status is CheckStatus.UNSUPPORTED_PLATFORM
    assert result.plan is None


def test_download_uses_staging_dir_and_reports_progress(tmp_path):
    service = _service(tmp_path, _release("0.0.9"))
    plan = service.check().plan
    seen = []
    artifact = service.download(plan, lambda r, t: seen.append((r, t)))
    assert artifact.parent == tmp_path
    assert artifact.name == "concat-e3v-linux-x86_64"
    assert artifact.read_bytes() == b"payload"
    assert seen == [(7, 7)]


def test_apply_delegates_to_installer(tmp_path):
    installer = FakeInstaller()
    service = _service(tmp_path, _release("0.0.9"), installer=installer)
    plan = service.check().plan
    outcome = service.apply(plan, tmp_path / "artifact")
    assert outcome.applied is True
    assert installer.installed[0][1] == plan


def test_can_self_update_follows_installer(tmp_path):
    assert _service(tmp_path, _release("0.0.9")).can_self_update() is True
    service = _service(tmp_path, _release("0.0.9"), installer=FakeInstaller(False))
    assert service.can_self_update() is False
