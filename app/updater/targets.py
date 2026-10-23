"""平台正規化與 release 檔名對照表。

release 上的檔名是固定的（見 .github/workflows/build.yml），
換檔名就要同步改這裡，並補測試。
"""

from __future__ import annotations

import platform as platform_module
import sys

from app.updater.models import Target

# (os, arch) -> release 上的 asset 名稱
ASSET_NAMES: dict[tuple[str, str], str] = {
    ("darwin", "arm64"): "concat-e3v-macos-arm64.app.zip",
    ("darwin", "x86_64"): "concat-e3v-macos-x86_64.app.zip",
    ("windows", "x86_64"): "concat-e3v-windows.exe",
    ("linux", "x86_64"): "concat-e3v-linux-x86_64",
}

_OS_ALIASES = {
    "darwin": "darwin",
    "mac": "darwin",
    "macos": "darwin",
    "win32": "windows",
    "windows": "windows",
    "cygwin": "windows",
    "msys": "windows",
    "linux": "linux",
    "linux2": "linux",
}

_ARCH_ALIASES = {
    "x86_64": "x86_64",
    "amd64": "x86_64",
    "x64": "x86_64",
    "arm64": "arm64",
    "aarch64": "arm64",
}


def normalize_os(value: str) -> str:
    return _OS_ALIASES.get(value.strip().lower(), value.strip().lower())


def normalize_arch(value: str) -> str:
    return _ARCH_ALIASES.get(value.strip().lower(), value.strip().lower())


def asset_name_for(os_name: str, arch: str) -> str | None:
    return ASSET_NAMES.get((normalize_os(os_name), normalize_arch(arch)))


def parse_target(os_name: str, machine: str) -> Target:
    return Target(os=normalize_os(os_name), arch=normalize_arch(machine))


def current_target() -> Target:
    return parse_target(sys.platform, platform_module.machine())
