"""TLS 憑證設定。

PyInstaller 打包後的執行檔沒有「原開發機」的 OpenSSL 憑證路徑：``ssl`` 是在
build 時把 OPENSSLDIR 燒進去的，到了使用者機器上那個資料夾不存在，於是
``ssl.create_default_context()`` 載到 0 張憑證，任何 HTTPS 連線都會得到::

    <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed:
     unable to get local issuer certificate (_ssl.c:1006)>

所以我們自己帶一份 CA 憑證包（``certifi``），並且：
- 在程式啟動時設定 ``SSL_CERT_FILE``，讓整個行程（urllib / httplib2 / requests）
  都用同一份憑證；
- 更新器建立 SSLContext 時明確指定 cafile，不依賴環境變數是否生效。
"""

from __future__ import annotations

import os
import ssl
from pathlib import Path

CERT_ERROR_HINT = (
    "無法驗證 GitHub 的 TLS 憑證（找不到可用的 CA 憑證包）。\n"
    "請改用最新版本的執行檔；若為自行打包，確認已安裝 certifi 且打包時有帶入。"
)


def cert_bundle_path() -> str | None:
    """回傳 certifi 的 cacert.pem 路徑；沒有 certifi 或檔案不存在就回 None。"""
    try:
        import certifi
    except ImportError:  # pragma: no cover - 正常打包一定會帶
        return None
    path = Path(certifi.where())
    return str(path) if path.is_file() else None


def create_ssl_context() -> ssl.SSLContext:
    bundle = cert_bundle_path()
    if bundle is None:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=bundle)


def configure_ssl_certificates() -> str | None:
    """把 certifi 的憑證包設成行程預設，回傳實際路徑。

    用 ``setdefault``：使用者若自己設了 ``SSL_CERT_FILE`` 就尊重他。
    """
    bundle = cert_bundle_path()
    if bundle is None:
        return None
    os.environ.setdefault("SSL_CERT_FILE", bundle)
    return bundle


def is_certificate_error(exc: BaseException) -> bool:
    """urllib 會把 SSL 錯誤包在 URLError.reason 裡，兩種都要認。"""
    if isinstance(exc, ssl.SSLCertVerificationError):
        return True
    reason = getattr(exc, "reason", None)
    return isinstance(reason, ssl.SSLCertVerificationError)
