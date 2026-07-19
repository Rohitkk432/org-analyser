"""Shared exception types for every platform client (GitHub/GitLab/Bitbucket).

Replaces the inconsistent mix of RuntimeError/ValueError/ProviderError/
SystemExit that different callers used to raise for the same failure modes.
"""

from __future__ import annotations


class PlatformError(Exception):
    """Base class for all platform-client errors."""


class PlatformAuthError(PlatformError):
    """Authentication/authorization failed (bad token, wrong scope, 401/403).

    Catchable and non-fatal by design: callers decide for themselves whether
    one repo's bad auth should abort a whole batch run.
    """


class PlatformRateLimitError(PlatformError):
    """Rate limit exhausted and retries were also exhausted."""
