"""Interfaces for the capabilities the application layer needs (hexagonal ports).

Real implementations live in ``github`` / ``download`` / ``installers``; tests
substitute fakes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Protocol

from app.updater.models import Asset, InstallOutcome, Release, UpdatePlan

ProgressCallback = Callable[[int, int], None]
"""``(bytes downloaded, total bytes)``; total is 0 while unknown."""


class ReleaseSource(Protocol):
    def latest(self) -> Release:
        """Return the newest stable release."""
        ...


class Downloader(Protocol):
    def download(
        self,
        asset: Asset,
        destination: Path,
        on_progress: ProgressCallback | None = None,
    ) -> Path:
        """Download ``asset`` to ``destination`` and return the real path."""
        ...


class Installer(Protocol):
    def can_install(self) -> bool:
        """Whether this run mode can replace its own executable."""
        ...

    def install(self, artifact: Path, plan: UpdatePlan) -> InstallOutcome:
        """Apply the downloaded artifact as the running version."""
        ...
