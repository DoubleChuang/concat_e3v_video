"""更新流程用到的錯誤型別。

全部繼承 :class:`UpdateError`，UI 只要攔這一種就能顯示友善訊息，
不需要知道底層是 HTTP、解壓縮還是檔案權限的問題。
"""

from __future__ import annotations


class UpdateError(Exception):
    """更新流程中所有可預期錯誤的基底類別。"""


class ReleaseLookupError(UpdateError):
    """查不到 release（離線、API 限流、repo 沒有 release…）。"""


class DownloadError(UpdateError):
    """下載失敗、大小或雜湊不符。"""


class InstallError(UpdateError):
    """下載完了但無法套用（權限不足、架構不支援…）。"""


class UnsupportedPlatformError(InstallError):
    """目前平台沒有對應的更新檔，或此執行方式（原始碼）不支援自動更新。"""
