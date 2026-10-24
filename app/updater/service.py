"""Use cases for the update flow: check, download, apply.

This layer only makes decisions and sequences calls; every I/O goes through the
ports, so it can be unit-tested without network or GUI.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from app.updater.models import InstallOutcome, Release, Target, UpdatePlan
from app.updater.ports import Downloader, Installer, ProgressCallback, ReleaseSource
from app.updater.version import Version


class CheckStatus(str, Enum):
    UP_TO_DATE = "up_to_date"
    UPDATE_AVAILABLE = "update_available"
    UNSUPPORTED_PLATFORM = "unsupported_platform"


@dataclass(frozen=True)
class CheckResult:
    status: CheckStatus
    current: Version
    release: Release | None = None
    plan: UpdatePlan | None = None

    @property
    def update_available(self) -> bool:
        return self.status is CheckStatus.UPDATE_AVAILABLE


class UpdateService:
    def __init__(
        self,
        current_version: Version,
        target: Target,
        source: ReleaseSource,
        downloader: Downloader,
        installer: Installer,
        download_dir: Path | None = None,
    ) -> None:
        self._current = current_version
        self._target = target
        self._source = source
        self._downloader = downloader
        self._installer = installer
        self._download_dir = download_dir

    @property
    def current_version(self) -> Version:
        return self._current

    @property
    def target(self) -> Target:
        return self._target

    def can_self_update(self) -> bool:
        return self._installer.can_install()

    def check(self) -> CheckResult:
        release = self._source.latest()
        if release.version <= self._current:
            return CheckResult(CheckStatus.UP_TO_DATE, self._current, release=release)
        asset = release.asset_for(self._target)
        if asset is None:
            return CheckResult(
                CheckStatus.UNSUPPORTED_PLATFORM, self._current, release=release
            )
        plan = UpdatePlan(current=self._current, release=release, asset=asset)
        return CheckResult(
            CheckStatus.UPDATE_AVAILABLE, self._current, release=release, plan=plan
        )

    def download(
        self, plan: UpdatePlan, on_progress: ProgressCallback | None = None
    ) -> Path:
        destination = self._staging_dir() / plan.asset.name
        return self._downloader.download(plan.asset, destination, on_progress)

    def apply(self, plan: UpdatePlan, artifact: Path) -> InstallOutcome:
        return self._installer.install(artifact, plan)

    def _staging_dir(self) -> Path:
        if self._download_dir is None:
            self._download_dir = Path(tempfile.gettempdir()) / "concat-e3v-updates"
        self._download_dir.mkdir(parents=True, exist_ok=True)
        return self._download_dir
