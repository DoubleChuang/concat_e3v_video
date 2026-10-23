"""應用層依賴的外部能力介面（hexagonal ports）。

實際實作在 ``github`` / ``download`` / ``installers``；測試用假物件替換。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Protocol

from app.updater.models import Asset, InstallOutcome, Release, UpdatePlan

ProgressCallback = Callable[[int, int], None]
"""``(已下載 bytes, 總 bytes)``；總量未知時為 0。"""


class ReleaseSource(Protocol):
    def latest(self) -> Release:
        """取得最新正式版 release。"""
        ...


class Downloader(Protocol):
    def download(
        self,
        asset: Asset,
        destination: Path,
        on_progress: ProgressCallback | None = None,
    ) -> Path:
        """把 asset 下載到 destination 並回傳實際路徑。"""
        ...


class Installer(Protocol):
    def can_install(self) -> bool:
        """目前執行方式是否支援自動替換執行檔。"""
        ...

    def install(self, artifact: Path, plan: UpdatePlan) -> InstallOutcome:
        """把下載好的檔案套用成執行中的版本。"""
        ...
