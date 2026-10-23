from app.updater.targets import asset_name_for, current_target, normalize_arch, normalize_os, parse_target


def test_normalize_os_aliases():
    assert normalize_os("Darwin") == "darwin"
    assert normalize_os("win32") == "windows"
    assert normalize_os("linux2") == "linux"


def test_normalize_arch_aliases():
    assert normalize_arch("AMD64") == "x86_64"
    assert normalize_arch("aarch64") == "arm64"


def test_parse_target_for_windows_runner_values():
    target = parse_target("win32", "AMD64")
    assert (target.os, target.arch) == ("windows", "x86_64")
    assert target.asset_name == "concat-e3v-windows.exe"
    assert target.supported is True


def test_parse_target_for_mac_arm():
    target = parse_target("darwin", "arm64")
    assert target.asset_name == "concat-e3v-macos-arm64.app.zip"


def test_parse_target_for_mac_intel():
    target = parse_target("darwin", "x86_64")
    assert target.asset_name == "concat-e3v-macos-x86_64.app.zip"


def test_linux_x86_64_asset():
    assert asset_name_for("linux", "x86_64") == "concat-e3v-linux-x86_64"


def test_unsupported_platform_has_no_asset():
    target = parse_target("linux", "aarch64")
    assert target.supported is False
    assert target.asset_name is None


def test_current_target_matches_runtime():
    target = current_target()
    assert target.os in ("darwin", "windows", "linux")
    assert target.label == f"{target.os}-{target.arch}"
