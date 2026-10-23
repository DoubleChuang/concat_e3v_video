from types import SimpleNamespace

import pytest

import app.main as app_main
from app.updater.errors import ReleaseLookupError
from app.updater.models import Asset, Release
from app.updater.service import CheckResult, CheckStatus
from app.updater.targets import parse_target
from app.updater.version import Version


class FakeService:
    current_version = Version.parse("0.0.9")
    target = parse_target("darwin", "x86_64")

    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error

    def check(self):
        if self._error is not None:
            raise self._error
        return self._result


def _use(monkeypatch, service):
    monkeypatch.setattr(app_main, "build_update_service", lambda: service)


def test_probe_reports_up_to_date(monkeypatch, capsys):
    release = Release(version=Version.parse("0.0.9"), tag="v0.0.9")
    _use(
        monkeypatch,
        FakeService(CheckResult(CheckStatus.UP_TO_DATE, Version.parse("0.0.9"), release)),
    )
    assert app_main._run_update_probe() == 0
    out = capsys.readouterr().out
    assert "已是最新版本" in out
    assert "darwin-x86_64" in out


def test_probe_reports_available_update(monkeypatch, capsys):
    release = Release(
        version=Version.parse("0.1.0"),
        tag="v0.1.0",
        assets=(Asset(name="concat-e3v-macos-x86_64.app.zip", url="https://x"),),
    )
    plan = SimpleNamespace(asset=release.assets[0])
    _use(
        monkeypatch,
        FakeService(
            CheckResult(
                CheckStatus.UPDATE_AVAILABLE, Version.parse("0.0.9"), release, plan
            )
        ),
    )
    assert app_main._run_update_probe() == 0
    assert "concat-e3v-macos-x86_64.app.zip" in capsys.readouterr().out


def test_probe_reports_unsupported_platform(monkeypatch, capsys):
    release = Release(version=Version.parse("0.1.0"), tag="v0.1.0")
    _use(
        monkeypatch,
        FakeService(
            CheckResult(CheckStatus.UNSUPPORTED_PLATFORM, Version.parse("0.0.9"), release)
        ),
    )
    assert app_main._run_update_probe() == 2
    assert "沒有提供更新檔" in capsys.readouterr().out


def test_probe_returns_error_code_and_prints_reason(monkeypatch, capsys):
    _use(monkeypatch, FakeService(error=ReleaseLookupError("TLS 憑證有問題")))
    assert app_main._run_update_probe() == 1
    assert "TLS 憑證有問題" in capsys.readouterr().out


@pytest.mark.parametrize("flag", ["--check-updates"])
def test_main_routes_flag_to_probe(monkeypatch, flag):
    import sys

    called = []
    monkeypatch.setattr(app_main, "_run_update_probe", lambda: called.append(1) or 0)
    monkeypatch.setattr(sys, "argv", ["concat-e3v", flag])
    assert app_main.main() == 0
    assert called == [1]
