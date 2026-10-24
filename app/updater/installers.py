"""How each platform swaps "the downloaded new version" for "the running one".

The three platforms differ:

* Linux  : a single-file executable can be replaced atomically (the running
           process still holds the old inode); the caller relaunches the new file.
* Windows: the running exe is locked, so write a .bat that waits for the process
           to exit, moves the new file in and starts it again.
* macOS  : the app is a .app bundle; replacing the whole bundle is the only way to
           keep the code signature valid. A shell script waits for the process,
           swaps the bundle and reopens it.

The script bodies are produced by pure functions (``build_*_script``) so escaping
and content can be tested without running anything.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Sequence

from app.updater.errors import InstallError, UnsupportedPlatformError
from app.updater.models import InstallOutcome, UpdatePlan

Spawn = Callable[[Sequence[str]], None]


def is_frozen() -> bool:
    """Only a PyInstaller build sets ``sys.frozen``."""
    return bool(getattr(sys, "frozen", False))


def _spawn_detached(command: Sequence[str]) -> None:
    kwargs: dict = {
        "close_fds": True,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(list(command), **kwargs)


class UnsupportedInstaller:
    """Development mode, or a platform without an artifact."""

    def __init__(self, reason: str) -> None:
        self._reason = reason

    def can_install(self) -> bool:
        return False

    def install(self, artifact: Path, plan: UpdatePlan) -> InstallOutcome:
        raise UnsupportedPlatformError(self._reason)


class LinuxInstaller:
    """Single-file executable: back up, then replace atomically."""

    def __init__(self, executable: Path | None = None) -> None:
        self._executable = Path(executable or sys.executable)

    @property
    def target(self) -> Path:
        return self._executable

    def can_install(self) -> bool:
        exe = self._executable
        if not exe.exists():
            return False
        return os.access(exe, os.W_OK) and os.access(exe.parent, os.W_OK)

    def install(self, artifact: Path, plan: UpdatePlan) -> InstallOutcome:
        target = self._executable
        if not self.can_install():
            raise InstallError(f"沒有寫入權限，無法替換 {target}")

        staged = target.with_name(target.name + ".new")
        backup = target.with_name(target.name + ".old")
        shutil.copy2(artifact, staged)
        staged.chmod(0o755)

        backup.unlink(missing_ok=True)
        os.replace(target, backup)
        try:
            os.replace(staged, target)
        except OSError as exc:
            os.replace(backup, target)
            staged.unlink(missing_ok=True)
            raise InstallError(f"替換執行檔失敗：{exc}") from exc
        return InstallOutcome(
            applied=True,
            restart_required=True,
            message="新版本已就位，重新啟動後生效",
            artifact_path=str(artifact),
            relaunch=(str(target),),
        )


def build_mac_update_script(
    pid: int,
    bundle: Path,
    new_bundle: Path,
    staging: Path,
) -> str:
    """Wait for the old process, swap the whole .app, clear quarantine, reopen."""
    bundle_q = shlex.quote(str(bundle))
    new_q = shlex.quote(str(new_bundle))
    staging_q = shlex.quote(str(staging))
    return f"""#!/bin/bash
set -u
PID={int(pid)}
BUNDLE={bundle_q}
NEW={new_q}
BACKUP="$BUNDLE.old"

while kill -0 "$PID" 2>/dev/null; do
  sleep 0.5
done

rm -rf "$BACKUP"
if ! mv "$BUNDLE" "$BACKUP"; then
  echo "cannot move old bundle $BUNDLE" >&2
  exit 1
fi
if ! mv "$NEW" "$BUNDLE"; then
  echo "cannot install new bundle, restoring the old one" >&2
  mv "$BACKUP" "$BUNDLE"
  exit 1
fi
rm -rf "$BACKUP"
xattr -dr com.apple.quarantine "$BUNDLE" 2>/dev/null
open "$BUNDLE"
rm -rf {staging_q}
"""


def _image_name(target: Path) -> str:
    """Executable file name; POSIX tests pass Windows paths, so handle both separators."""
    return str(target).replace("\\", "/").rsplit("/", 1)[-1]


def build_windows_update_script(pid: int, target: Path, new_file: Path) -> str:
    """Wait for the old process, overwrite the exe, restart, clean up staging.

    The wait compares the PID *and* the image name: PID alone false-matches
    (123 vs 5123) and moving too early fails because the exe is still locked.
    """
    image_name = _image_name(target)
    return f"""@echo off
setlocal
set "TARGET={target}"
set "NEW={new_file}"

:wait
tasklist /FI "PID eq {int(pid)}" /NH 2>NUL | find /I "{image_name}" >NUL
if not errorlevel 1 (
  timeout /t 2 /nobreak >NUL
  goto wait
)

move /y "%NEW%" "%TARGET%" >NUL
if errorlevel 1 (
  echo update-failed > "%~dp0update-error.txt"
  exit /b 1
)
start "" "%TARGET%"
cd /d "%TEMP%"
rmdir /s /q "%~dp0" >NUL 2>&1
"""


class MacInstaller:
    """.app bundle update: extract to staging, let a shell script do the swap."""

    def __init__(self, executable: Path | None = None, spawn: Spawn | None = None) -> None:
        self._executable = Path(executable or sys.executable)
        self._spawn = spawn or _spawn_detached

    @property
    def bundle(self) -> Path | None:
        return bundle_path_for(self._executable)

    def can_install(self) -> bool:
        bundle = self.bundle
        if bundle is None or not bundle.exists():
            return False
        return os.access(bundle.parent, os.W_OK)

    def install(self, artifact: Path, plan: UpdatePlan) -> InstallOutcome:
        bundle = self.bundle
        if bundle is None:
            raise InstallError("找不到 .app bundle，無法自動更新")

        if not self.can_install():
            return InstallOutcome(
                applied=False,
                manual_fallback=True,
                message=(
                    f"沒有寫入權限更新 {bundle}。\n"
                    "已下載新版本，請手動解壓縮後拖進「應用程式」資料夾。"
                ),
                artifact_path=str(artifact),
            )

        staging = Path(tempfile.mkdtemp(prefix="concat-e3v-update-"))
        extract_dir = staging / "extract"
        extract_dir.mkdir()
        result = subprocess.run(
            ["ditto", "-x", "-k", str(artifact), str(extract_dir)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise InstallError(f"解壓縮更新檔失敗：{result.stderr.strip()}")

        new_bundle = next(iter(sorted(extract_dir.glob("*.app"))), None)
        if new_bundle is None:
            raise InstallError("更新檔裡找不到 .app")

        script = staging / "apply-update.sh"
        script.write_text(
            build_mac_update_script(os.getpid(), bundle, new_bundle, staging),
            encoding="utf-8",
        )
        script.chmod(0o755)
        self._spawn(["/bin/bash", str(script)])
        return InstallOutcome(
            applied=True,
            restart_required=True,
            message="新版本已下載，重新啟動後完成更新",
            artifact_path=str(artifact),
        )


class WindowsInstaller:
    """A running exe cannot be overwritten; a .bat takes over after exit."""

    def __init__(self, executable: Path | None = None, spawn: Spawn | None = None) -> None:
        self._executable = Path(executable or sys.executable)
        self._spawn = spawn or _spawn_detached

    @property
    def target(self) -> Path:
        return self._executable

    def can_install(self) -> bool:
        target = self._executable
        if not target.exists():
            return False
        return os.access(target, os.W_OK) and os.access(target.parent, os.W_OK)

    def install(self, artifact: Path, plan: UpdatePlan) -> InstallOutcome:
        target = self._executable
        if not self.can_install():
            raise InstallError(f"沒有寫入權限，無法替換 {target}")

        staging = Path(tempfile.mkdtemp(prefix="concat-e3v-update-"))
        new_file = staging / target.name
        shutil.copy2(artifact, new_file)

        script = staging / "apply-update.bat"
        script.write_text(
            build_windows_update_script(os.getpid(), target, new_file),
            encoding="utf-8",
            newline="\r\n",
        )
        self._spawn(["cmd.exe", "/c", str(script)])
        return InstallOutcome(
            applied=True,
            restart_required=True,
            message="新版本已下載，重新啟動後完成更新",
            artifact_path=str(artifact),
        )


def bundle_path_for(executable: Path) -> Path | None:
    """Find the ``.app`` for ``.../concat-e3v.app/Contents/MacOS/concat-e3v``."""
    for parent in Path(executable).parents:
        if parent.suffix == ".app":
            return parent
    return None


def installer_for(
    os_name: str,
    arch: str,
    executable: Path | None = None,
    frozen: bool | None = None,
    spawn: Spawn | None = None,
):
    if frozen is None:
        frozen = is_frozen()
    if not frozen:
        return UnsupportedInstaller(
            "目前是以原始碼執行，無法自動替換；請下載新版本後手動更新。"
        )
    if os_name == "linux" and arch == "x86_64":
        return LinuxInstaller(executable)
    if os_name == "windows" and arch == "x86_64":
        return WindowsInstaller(executable, spawn)
    if os_name == "darwin" and arch in ("x86_64", "arm64"):
        return MacInstaller(executable, spawn)
    return UnsupportedInstaller(f"這個平台沒有提供自動更新（{os_name}-{arch}）")
