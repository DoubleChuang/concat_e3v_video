"""Immutable data structures for the update flow.

Deliberately decoupled from the GitHub JSON shape: adapters translate the outside
world into these types, and the application/UI layers only see these objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.updater.version import Version


@dataclass(frozen=True)
class Target:
    """The running platform and the release artifact that belongs to it.

    ``os`` is normalised to ``darwin`` / ``windows`` / ``linux``; ``arch`` to
    ``x86_64`` / ``arm64``.
    """

    os: str
    arch: str

    @property
    def asset_name(self) -> str | None:
        from app.updater.targets import asset_name_for

        return asset_name_for(self.os, self.arch)

    @property
    def supported(self) -> bool:
        return self.asset_name is not None

    @property
    def label(self) -> str:
        return f"{self.os}-{self.arch}"


@dataclass(frozen=True)
class Asset:
    """One downloadable file inside a release."""

    name: str
    url: str
    size: int = 0
    sha256: str | None = None

    def verify(self, received_bytes: int, digest: str) -> None:
        """Called by the downloader; raises :class:`app.updater.errors.DownloadError`."""
        from app.updater.errors import DownloadError

        if self.size and received_bytes != self.size:
            raise DownloadError(
                f"下載大小不符（預期 {self.size} bytes，實際 {received_bytes} bytes）"
            )
        if self.sha256 and digest.lower() != self.sha256.lower():
            raise DownloadError("下載檔案的 sha256 與 release 標示不符")


@dataclass(frozen=True)
class Release:
    """One GitHub release."""

    version: Version
    tag: str
    notes: str = ""
    page_url: str = ""
    assets: tuple[Asset, ...] = field(default_factory=tuple)

    def asset_for(self, target: Target) -> Asset | None:
        name = target.asset_name
        if name is None:
            return None
        for asset in self.assets:
            if asset.name == name:
                return asset
        return None


@dataclass(frozen=True)
class UpdatePlan:
    """A newer release exists *and* this platform has an artifact for it."""

    current: Version
    release: Release
    asset: Asset


@dataclass(frozen=True)
class InstallOutcome:
    """Result of applying an update.

    ``restart_required`` means the caller must exit so the updater can take over.
    ``relaunch`` is the command to start detached before exiting (Linux runs the
    new binary directly; Windows/macOS restart from their helper script, so it is
    ``None`` there). ``manual_fallback`` means the artifact was downloaded but
    could not be swapped automatically and the user has to finish by hand.
    """

    applied: bool
    restart_required: bool = False
    manual_fallback: bool = False
    message: str = ""
    artifact_path: str | None = None
    relaunch: tuple[str, ...] | None = None
