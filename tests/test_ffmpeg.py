import os
import shutil
import sys
import pytest
from app.ffmpeg import resolve_ffmpeg


def test_resolve_from_executable_dir(monkeypatch, tmp_path):
    exe = tmp_path / "concat-e3v"
    (tmp_path / "ffmpeg").write_bytes(b"x")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert resolve_ffmpeg() == str(tmp_path / "ffmpeg")


def test_resolve_from_meipass(monkeypatch, tmp_path):
    exe = tmp_path / "concat-e3v"
    meipass = tmp_path / "_internal"
    meipass.mkdir()
    (meipass / "ffmpeg").write_bytes(b"x")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
    assert resolve_ffmpeg() == str(meipass / "ffmpeg")


def test_resolve_windows_exe_name(monkeypatch, tmp_path):
    exe = tmp_path / "concat-e3v.exe"
    (tmp_path / "ffmpeg.exe").write_bytes(b"x")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(os, "name", "nt")
    assert resolve_ffmpeg() == str(tmp_path / "ffmpeg.exe")


def test_resolve_from_path(monkeypatch, tmp_path):
    fake = tmp_path / "ffmpeg"
    fake.write_bytes(b"x")
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: str(fake))
    assert resolve_ffmpeg() == str(fake)


def test_resolve_none(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert resolve_ffmpeg() is None