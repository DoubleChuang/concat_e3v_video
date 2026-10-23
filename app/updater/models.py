"""更新流程的資料結構（不可變）。

刻意與 GitHub API 的 JSON 形狀解耦：轉接器負責把外部格式轉成這些型別，
應用層與 UI 只看得到這裡的物件。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.updater.version import Version


@dataclass(frozen=True)
class Target:
    """目前執行平台的識別與對應的 release 檔案。

    ``os`` 使用標準化的 ``darwin`` / ``windows`` / ``linux``；
    ``arch`` 使用 ``x86_64`` / ``arm64``。
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
    """release 內的一個可下載檔案。"""

    name: str
    url: str
    size: int = 0
    sha256: str | None = None

    def verify(self, received_bytes: int, digest: str) -> None:
        """由下載器呼叫；違反時丟 :class:`app.updater.errors.DownloadError`。"""
        from app.updater.errors import DownloadError

        if self.size and received_bytes != self.size:
            raise DownloadError(
                f"下載大小不符（預期 {self.size} bytes，實際 {received_bytes} bytes）"
            )
        if self.sha256 and digest.lower() != self.sha256.lower():
            raise DownloadError("下載檔案的 sha256 與 release 標示不符")


@dataclass(frozen=True)
class Release:
    """一筆 GitHub release。"""

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
    """「有新版本、而且這個平台抓得到對應檔案」的結果。"""

    current: Version
    release: Release
    asset: Asset


@dataclass(frozen=True)
class InstallOutcome:
    """套用更新的結果。

    ``restart_required`` 為真時，呼叫端應結束目前行程，讓更新程式接手。
    ``relaunch`` 是要在結束前用分離行程啟動的指令（Linux 直接跑新檔；
    Windows/macOS 由更新腳本負責重開，因此為 ``None``）。
    ``manual_fallback`` 為真代表檔案已下載但無法自動替換，需使用者手動完成。
    """

    applied: bool
    restart_required: bool = False
    manual_fallback: bool = False
    message: str = ""
    artifact_path: str | None = None
    relaunch: tuple[str, ...] | None = None
