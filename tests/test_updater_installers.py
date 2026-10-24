import subprocess
import sys
from pathlib import Path

import pytest

from app.updater.errors import InstallError, UnsupportedPlatformError
from app.updater.installers import (
    LinuxInstaller,
    MacInstaller,
    WindowsInstaller,
    bundle_path_for,
    build_mac_update_script,
    build_windows_update_script,
    installer_for,
)
from app.updater.models import UpdatePlan
from app.updater.version import Version


def _plan() -> UpdatePlan:
    from app.updater.models import Asset, Release

    release = Release(version=Version.parse("0.0.9"), tag="v0.0.9")
    asset = Asset(name="concat-e3v-linux-x86_64", url="https://example.test/x")
    return UpdatePlan(current=Version.parse("0.0.8"), release=release, asset=asset)


# --------------------------------------------------------------------- Linux
def test_linux_installer_replaces_binary_and_keeps_backup(tmp_path):
    target = tmp_path / "concat-e3v"
    target.write_bytes(b"old")
    artifact = tmp_path / "download"
    artifact.write_bytes(b"new")

    outcome = LinuxInstaller(target).install(artifact, _plan())

    assert target.read_bytes() == b"new"
    assert (tmp_path / "concat-e3v.old").read_bytes() == b"old"
    assert not (tmp_path / "concat-e3v.new").exists()
    assert outcome.restart_required is True
    assert outcome.relaunch == (str(target),)


def test_linux_installer_requires_writable_target(tmp_path):
    readonly = tmp_path / "ro"
    readonly.mkdir()
    target = readonly / "concat-e3v"
    target.write_bytes(b"old")
    target.chmod(0o400)
    readonly.chmod(0o500)
    artifact = tmp_path / "download"
    artifact.write_bytes(b"new")
    try:
        installer = LinuxInstaller(target)
        assert installer.can_install() is False
        with pytest.raises(InstallError):
            installer.install(artifact, _plan())
    finally:
        readonly.chmod(0o700)
        target.chmod(0o600)


def test_linux_installer_restores_target_when_replace_fails(tmp_path, monkeypatch):
    target = tmp_path / "concat-e3v"
    target.write_bytes(b"old")
    artifact = tmp_path / "download"
    artifact.write_bytes(b"new")

    real_replace = __import__("os").replace

    def flaky_replace(src, dst):
        if Path(src).name.endswith(".new"):
            raise OSError("disk full")
        return real_replace(src, dst)

    monkeypatch.setattr("app.updater.installers.os.replace", flaky_replace)
    with pytest.raises(InstallError):
        LinuxInstaller(target).install(artifact, _plan())
    assert target.read_bytes() == b"old"


# ------------------------------------------------------------------- Windows
def test_windows_script_waits_for_exit_then_replaces_and_starts():
    script = build_windows_update_script(
        pid=4321,
        target=Path(r"C:\Apps\concat-e3v.exe"),
        new_file=Path(r"C:\Temp\upd\concat-e3v.exe"),
    )
    assert 'PID eq 4321' in script
    assert "/NH" in script
    assert 'find /I "concat-e3v.exe"' in script
    assert "move /y" in script
    assert 'start ""' in script
    assert r"C:\Apps\concat-e3v.exe" in script


def test_windows_installer_writes_script_and_spawns(tmp_path, monkeypatch):
    target = tmp_path / "concat-e3v.exe"
    target.write_bytes(b"old")
    artifact = tmp_path / "download"
    artifact.write_bytes(b"new")
    spawned = []

    outcome = WindowsInstaller(target, spawn=spawned.append).install(artifact, _plan())

    assert outcome.applied is True
    assert spawned and spawned[0][0] == "cmd.exe"
    script = Path(spawned[0][2])
    assert script.exists()
    content = script.read_text(encoding="utf-8")
    assert "tasklist" in content
    assert str(target) in content


def test_windows_installer_requires_existing_target(tmp_path):
    installer = WindowsInstaller(tmp_path / "missing.exe", spawn=lambda c: None)
    assert installer.can_install() is False
    with pytest.raises(InstallError):
        installer.install(tmp_path / "download", _plan())


# ----------------------------------------------------------------------- Mac
def test_bundle_path_detection():
    exe = Path("/Applications/concat-e3v.app/Contents/MacOS/concat-e3v")
    assert bundle_path_for(exe) == Path("/Applications/concat-e3v.app")
    assert bundle_path_for(Path("/usr/local/bin/concat-e3v")) is None


def test_mac_script_waits_then_swaps_bundle_and_reopens(tmp_path):
    script = build_mac_update_script(
        pid=99,
        bundle=Path("/Applications/My App.app"),
        new_bundle=tmp_path / "staging" / "concat-e3v.app",
        staging=tmp_path / "staging",
    )
    assert "kill -0" in script
    assert "mv " in script
    assert 'open "$BUNDLE"' in script
    assert "xattr -dr com.apple.quarantine" in script
    # a path containing spaces must stay quoted
    assert "BUNDLE='/Applications/My App.app'" in script


def test_mac_installer_extracts_and_spawns_helper(tmp_path, monkeypatch):
    bundle = tmp_path / "Applications" / "concat-e3v.app"
    (bundle / "Contents" / "MacOS").mkdir(parents=True)
    exe = bundle / "Contents" / "MacOS" / "concat-e3v"
    exe.write_text("binary")
    artifact = tmp_path / "update.app.zip"
    artifact.write_text("zip")

    def fake_run(cmd, **kwargs):
        extract_dir = Path(cmd[4])
        (extract_dir / "concat-e3v.app").mkdir(parents=True)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("app.updater.installers.subprocess.run", fake_run)
    spawned = []
    outcome = MacInstaller(exe, spawn=spawned.append).install(artifact, _plan())

    assert outcome.applied is True
    assert outcome.restart_required is True
    assert spawned[0][0] == "/bin/bash"
    helper = Path(spawned[0][1])
    assert helper.exists()
    assert str(bundle) in helper.read_text(encoding="utf-8")


def test_mac_installer_falls_back_when_bundle_not_writable(tmp_path, monkeypatch):
    bundle = tmp_path / "RO" / "concat-e3v.app"
    exe = bundle / "Contents" / "MacOS" / "concat-e3v"
    exe.parent.mkdir(parents=True)
    exe.write_text("binary")
    artifact = tmp_path / "update.app.zip"
    artifact.write_text("zip")

    monkeypatch.setattr("app.updater.installers.os.access", lambda *a, **k: False)
    outcome = MacInstaller(exe, spawn=lambda c: None).install(artifact, _plan())
    assert outcome.applied is False
    assert outcome.manual_fallback is True
    assert outcome.artifact_path == str(artifact)


# -------------------------------------------------------------------- factory
def test_factory_refuses_dev_mode():
    installer = installer_for("linux", "x86_64", frozen=False)
    assert installer.can_install() is False
    with pytest.raises(UnsupportedPlatformError):
        installer.install(Path("/tmp/x"), _plan())


def test_factory_picks_platform_installer(tmp_path):
    exe = tmp_path / "concat-e3v"
    exe.write_text("x")
    assert isinstance(installer_for("linux", "x86_64", exe, frozen=True), LinuxInstaller)
    assert isinstance(installer_for("windows", "x86_64", exe, frozen=True), WindowsInstaller)
    assert isinstance(installer_for("darwin", "arm64", exe, frozen=True), MacInstaller)


def test_factory_rejects_unknown_platform():
    installer = installer_for("linux", "aarch64", frozen=True)
    assert installer.can_install() is False


def test_linux_installer_uses_sys_executable_by_default():
    assert LinuxInstaller().target == Path(sys.executable)
