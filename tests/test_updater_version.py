import pytest

from app.updater.version import Version


def test_parse_accepts_v_prefix():
    assert Version.parse("v0.0.8") == Version(0, 0, 8)


def test_parse_rejects_garbage():
    with pytest.raises(ValueError):
        Version.parse("latest")


def test_parse_prerelease_and_build_metadata():
    version = Version.parse("1.2.3-rc.1+build.9")
    assert (version.major, version.minor, version.patch) == (1, 2, 3)
    assert version.prerelease == ("rc", "1")
    assert version.is_prerelease is True
    assert str(version) == "1.2.3-rc.1"


def test_patch_is_optional():
    assert Version.parse("1.2") == Version(1, 2, 0)


def test_ordering_by_number_not_string():
    assert Version.parse("0.0.10") > Version.parse("0.0.9")


def test_release_beats_prerelease():
    assert Version.parse("1.0.0") > Version.parse("1.0.0-rc.1")


def test_prerelease_numeric_segments_compare_as_numbers():
    assert Version.parse("1.0.0-rc.10") > Version.parse("1.0.0-rc.2")


def test_equal_versions():
    assert Version.parse("v0.0.8") >= Version.parse("0.0.8")
    assert not Version.parse("0.0.8") < Version.parse("v0.0.8")


def test_str_roundtrip():
    for text in ("0.0.8", "1.2.3-rc.1", "10.20.30"):
        assert str(Version.parse(text)) == text
