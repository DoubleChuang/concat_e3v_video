import os
import shutil
import sys


def _candidate_dirs() -> list[str]:
    dirs: list[str] = []
    if getattr(sys, "frozen", False):
        dirs.append(os.path.dirname(sys.executable))
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            dirs.append(meipass)
    return dirs


def resolve_ffmpeg() -> str | None:
    name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    for base in _candidate_dirs():
        candidate = os.path.join(base, name)
        if os.path.isfile(candidate):
            return candidate
    return shutil.which("ffmpeg")