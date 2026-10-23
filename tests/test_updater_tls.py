import os
import ssl
import urllib.error
from pathlib import Path

from app.updater import tls


def test_cert_bundle_comes_from_certifi():
    path = tls.cert_bundle_path()
    assert path is not None
    assert Path(path).is_file()
    assert "cacert" in Path(path).name


def test_context_actually_loads_certificates():
    context = tls.create_ssl_context()
    # 這正是打包後壞掉的地方：沒有 cafile 時這裡會是 0
    assert len(context.get_ca_certs()) > 10


def test_configure_sets_env_when_unset(monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    path = tls.configure_ssl_certificates()
    assert path is not None
    assert os.environ["SSL_CERT_FILE"] == path


def test_configure_respects_existing_env(monkeypatch, tmp_path):
    custom = tmp_path / "custom.pem"
    custom.write_text("dummy")
    monkeypatch.setenv("SSL_CERT_FILE", str(custom))
    tls.configure_ssl_certificates()
    assert os.environ["SSL_CERT_FILE"] == str(custom)


def test_is_certificate_error_detects_direct_and_wrapped():
    inner = ssl.SSLCertVerificationError(1, "certificate verify failed")
    assert tls.is_certificate_error(inner) is True
    assert tls.is_certificate_error(urllib.error.URLError(inner)) is True
    assert tls.is_certificate_error(urllib.error.URLError("timed out")) is False
    assert tls.is_certificate_error(TimeoutError("slow")) is False
