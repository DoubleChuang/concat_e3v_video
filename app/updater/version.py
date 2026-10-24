"""SemVer parsing, formatting and comparison.

Only the shapes that show up as GitHub release tags are supported: ``v0.0.8``,
``0.0.8``, ``1.2.3-rc.1``, ``1.2.3+build.7``. Ordering follows semver 2.0.0: a
prerelease sorts below the same release number, and prerelease identifiers are
compared numerically when they are digits, lexically otherwise.
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
    """Immutable version number. Use :meth:`parse` instead of the constructor."""

    major: int
    minor: int
    patch: int = 0
    prerelease: tuple[str, ...] = ()

    @classmethod
    def parse(cls, text: str) -> "Version":
        match = _VERSION_RE.match(str(text).strip())
        if match is None:
            raise ValueError(f"invalid version string: {text!r}")
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
        # A final release outranks any prerelease of the same number.
        return (self.major, self.minor, self.patch, 0 if self.prerelease else 1, pre)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self._sort_key() < other._sort_key()
