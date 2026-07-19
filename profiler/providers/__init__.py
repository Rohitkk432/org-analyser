"""Git hosting providers (GitHub, GitLab, Bitbucket) and a factory to build them."""

from __future__ import annotations

from .base import (
    GitProvider,
    ProviderError,
    RemoteRepo,
    parse_org_target,
    parse_repo_target,
)
from .bitbucket import BitbucketProvider
from .github import GitHubProvider
from .gitlab import GitLabProvider

__all__ = [
    "BitbucketProvider",
    "GitProvider",
    "ProviderError",
    "RemoteRepo",
    "GitHubProvider",
    "GitLabProvider",
    "make_provider",
    "parse_repo_target",
    "parse_org_target",
]


def make_provider(
    platform: str, token: str | None = None, host: str | None = None
) -> GitProvider:
    platform = platform.lower()
    if platform == "github":
        return GitHubProvider(token=token, host=host)
    if platform == "gitlab":
        return GitLabProvider(token=token, host=host)
    if platform == "bitbucket":
        return BitbucketProvider(token=token, host=host)
    raise ValueError(
        f"unknown platform: {platform!r} (expected 'github', 'gitlab', or 'bitbucket')"
    )
