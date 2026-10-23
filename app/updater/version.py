"""SemVer 版本號：解析、格式化與比較。

只支援 GitHub release tag 會出現的樣式：``v0.0.8``、``0.0.8``、``1.2.3-rc.1``、
``1.2.3+build.7``。比較規則遵循 semver 2.0.0：有 prerelease 的版本小於同號的正式版，
prerelease 內以「數字段落視為數字、其餘視為字串」比較。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import total_ordering

_VERSION_RE = re.compile(
    r"^[vV]?(?P<major>\d+)\.(?P<minor>\d+)(?:\.(?P<patch>\d+))?"
    r"(?:-(?P<pre>[0-9A-Za-z.-]+))?(?:\+(?P<build>[0-9A-Za-z.-]+))?$"
)


@total_ordering
@dataclass(frozen=True)
class Version:
    """不可變的版本號。建構子請用 :meth:`parse` 以避免格式錯誤。"""

    major: int
    minor: int
    patch: int = 0
    prerelease: tuple[str, ...] = ()

    @classmethod
    def parse(cls, text: str) -> "Version":
        match = _VERSION_RE.match(str(text).strip())
        if match is None:
            raise ValueError(f"無法解析版本號: {text!r}")
        pre = match.group("pre")
        return cls(
            major=int(match.group("major")),
            minor=int(match.group("minor")),
            patch=int(match.group("patch") or 0),
            prerelease=tuple(pre.split(".")) if pre else (),
        )

    @property
    def is_prerelease(self) -> bool:
        return bool(self.prerelease)

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        if not self.prerelease:
            return base
        return f"{base}-{'.'.join(self.prerelease)}"

    def _sort_key(self) -> tuple:
        pre = tuple(
            (0, int(part), "") if part.isdigit() else (1, 0, part)
            for part in self.prerelease
        )
        # 正式版（沒有 prerelease）要比任何 prerelease 大
        return (self.major, self.minor, self.patch, 0 if self.prerelease else 1, pre)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self._sort_key() < other._sort_key()
