"""更新檢查與自動更新的核心（domain 層）。

這個套件刻意不 import PySide6，也不做任何 I/O，方便單獨測試：

- ``version``  SemVer 版本號與比較規則
- ``models``   Release / Asset / Target / UpdatePlan 等不可變資料結構
- ``targets``  目前平台對應的 release 檔名
- ``ports``    對外依賴的介面（Protocol）
- ``service``  用例（檢查、下載、套用更新）
- ``github``   GitHub Releases 轉接器
- ``download`` HTTP 下載轉接器（含 sha256 驗證）
- ``installers``各平台套用更新的轉接器
- ``factory``  依目前平台組裝 service
"""

from app.updater.models import Asset, Release, Target, UpdatePlan
from app.updater.service import CheckResult, CheckStatus, UpdateService
from app.updater.version import Version

__all__ = [
    "Asset",
    "CheckResult",
    "CheckStatus",
    "Release",
    "Target",
    "UpdatePlan",
    "UpdateService",
    "Version",
]
