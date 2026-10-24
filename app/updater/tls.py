"""TLS certificate setup.

A PyInstaller binary has no OpenSSL trust path from the machine that built it:
``ssl`` bakes OPENSSLDIR in at build time, that directory does not exist on the
user's machine, so ``ssl.create_default_context()`` loads zero certificates and
every HTTPS call fails with::

    <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed:
     unable to get local issuer certificate (_ssl.c:1006)>

So we ship our own CA bundle (``certifi``) and:

- set ``SSL_CERT_FILE`` at startup so the whole process (urllib / httplib2 /
  requests) uses the same bundle;
- pass ``cafile`` explicitly when the updater builds an SSLContext, instead of
  relying on the environment variable having been picked up.
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
    """Return certifi's cacert.pem path, or None when unavailable."""
    try:
        import certifi
    except ImportError:  # pragma: no cover - a real build always bundles it
        return None
    path = Path(certifi.where())
    return str(path) if path.is_file() else None


def create_ssl_context() -> ssl.SSLContext:
    bundle = cert_bundle_path()
    if bundle is None:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=bundle)


def configure_ssl_certificates() -> str | None:
    """Point the process at certifi's bundle and return its path.

    Uses ``setdefault``: an ``SSL_CERT_FILE`` the user set themselves wins.
    """
    bundle = cert_bundle_path()
    if bundle is None:
        return None
    os.environ.setdefault("SSL_CERT_FILE", bundle)
    return bundle


def is_certificate_error(exc: BaseException) -> bool:
    """urllib wraps SSL errors in ``URLError.reason``; accept both shapes."""
    if isinstance(exc, ssl.SSLCertVerificationError):
        return True
    reason = getattr(exc, "reason", None)
    return isinstance(reason, ssl.SSLCertVerificationError)
