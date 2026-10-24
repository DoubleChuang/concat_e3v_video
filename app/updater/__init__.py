"""Update checking and self-update core (domain layer).

Deliberately free of PySide6 imports and of any I/O so it can be tested on its own:

- ``version``    SemVer parsing and comparison
- ``models``     immutable Release / Asset / Target / UpdatePlan structures
- ``targets``    maps (os, arch) to the release asset name
- ``ports``      interfaces (Protocols) for the outside world
- ``service``    use cases: check, download, apply
- ``github``     GitHub Releases adapter
- ``download``   HTTP download adapter (with sha256 verification)
- ``installers`` per-platform adapters that swap the running executable
- ``factory``    assembles the service for the current platform
"""

from app.updater.models import Asset, Release, Target, UpdatePlan
from app.updater.service import CheckResult, CheckStatus, UpdateService
from app.updater.version import Version

__all__ = [
    "Asset",
    "CheckResult",
    "CheckStatus",
    "Release",
    "Target",
    "UpdatePlan",
    "UpdateService",
    "Version",
]
