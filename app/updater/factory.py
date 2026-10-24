"""Composition root for the update feature: wire the service for this platform."""

from __future__ import annotations

from pathlib import Path

from app.updater.download import HttpDownloader
from app.updater.github import DEFAULT_REPOSITORY, GitHubReleaseSource
from app.updater.installers import installer_for
from app.updater.models import Target
from app.updater.service import UpdateService
from app.updater.targets import current_target
from app.updater.version import Version
from app.version import __version__


def build_update_service(
    repository: str = DEFAULT_REPOSITORY,
    current_version: Version | None = None,
    target: Target | None = None,
    frozen: bool | None = None,
    executable: Path | None = None,
) -> UpdateService:
    current = current_version or Version.parse(__version__)
    platform_target = target or current_target()
    installer = installer_for(
        platform_target.os,
        platform_target.arch,
        executable=executable,
        frozen=frozen,
    )
    return UpdateService(
        current_version=current,
        target=platform_target,
        source=GitHubReleaseSource(repository),
        downloader=HttpDownloader(),
        installer=installer,
    )
