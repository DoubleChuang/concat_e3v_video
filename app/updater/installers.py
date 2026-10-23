"""各平台如何把「下載好的新版本」換成「正在跑的版本」。

三個平台的限制不同：

* Linux  ：單檔執行檔可以直接原子替換（舊 inode 還被執行中的行程持有），
           換完由呼叫端重開新檔。
* Windows：執行中的 exe 被鎖住，只能先寫一個 .bat，等行程結束後搬檔並重開。
* macOS  ：本體是 .app bundle，整個 bundle 換掉才不會破壞 code signature；
           同樣靠 shell script 等行程結束後替換並重開。

腳本產生的部分是純函式（``build_*_script``），方便測試路徑跳脫與內容。
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
    """PyInstaller 打包後的執行檔才會是 frozen。"""
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
    """開發模式或沒有對應產物的平台。"""

    def __init__(self, reason: str) -> None:
        self._reason = reason

    def can_install(self) -> bool:
        return False

    def install(self, artifact: Path, plan: UpdatePlan) -> InstallOutcome:
        raise UnsupportedPlatformError(self._reason)


class LinuxInstaller:
    """單檔執行檔：備份 → 原子替換。"""

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
    """等舊行程結束 → 換掉整個 .app → 去除 quarantine → 重開。"""
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
  echo "無法移動舊版 $BUNDLE" >&2
  exit 1
fi
if ! mv "$NEW" "$BUNDLE"; then
  echo "無法放入新版本，還原舊版" >&2
  mv "$BACKUP" "$BUNDLE"
  exit 1
fi
rm -rf "$BACKUP"
xattr -dr com.apple.quarantine "$BUNDLE" 2>/dev/null
open "$BUNDLE"
rm -rf {staging_q}
"""


def _image_name(target: Path) -> str:
    """取執行檔檔名；測試會在 POSIX 上傳入 Windows 路徑，所以兩種分隔符都要處理。"""
    return str(target).replace("\\", "/").rsplit("/", 1)[-1]


def build_windows_update_script(pid: int, target: Path, new_file: Path) -> str:
    """等舊行程結束 → 覆蓋 exe → 重開 → 清掉暫存資料夾。

    等行程的判斷同時比對 PID 與檔名：只比 PID 會誤判（例如 123 對上 5123），
    太早搬檔會因為 exe 還被鎖住而失敗。
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
    """.app bundle 更新：解壓到暫存 → 交给 shell script 換檔。"""

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
    """執行中的 exe 不能覆蓋，交給 .bat 在行程結束後接手。"""

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
    """從 ``.../concat-e3v.app/Contents/MacOS/concat-e3v`` 找出 ``.app``。"""
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
