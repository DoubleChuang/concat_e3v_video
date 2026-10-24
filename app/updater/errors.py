"""Error types for the update flow.

Everything derives from :class:`UpdateError` so the UI can catch one type and
show a friendly message without knowing whether the cause was HTTP, extraction
or file permissions.
"""

from __future__ import annotations


class UpdateError(Exception):
    """Base class for every expected error in the update flow."""


class ReleaseLookupError(UpdateError):
    """No release available (offline, API rate limit, repo has no release...)."""


class DownloadError(UpdateError):
    """Download failed, or size/hash did not match."""


class InstallError(UpdateError):
    """Downloaded fine but cannot be applied (permissions, unsupported arch...)."""


class UnsupportedPlatformError(InstallError):
    """No artifact for this platform, or a source checkout cannot self-update."""
