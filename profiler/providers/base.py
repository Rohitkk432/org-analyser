"""Git hosting provider abstraction (GitHub, GitLab, Bitbucket).

A provider knows how to list an org/group's repos, resolve a single repo, build an
authenticated clone URL, and fetch PR/MR review stats + fork status via the platform API.
Tokens are passed in at construction and never persisted.
"""

from __future__ import annotations

import json
import logging
import ssl
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass

import certifi

logger = logging.getLogger(__name__)

_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


class ProviderError(RuntimeError):
    """The hosting platform API failed."""


class _CIHeaders(dict):
    """Case-insensitive view of HTTP response headers.

    HTTP/2 lowercases header names, so ``dict(resp.headers).get("X-Next-Page")`` can miss
    a header that is actually present as ``x-next-page``. That silently capped GitLab
    pagination (PR/MR counts, group repo lists) at the first 100 results.
    """

    def __init__(self, headers) -> None:
        super().__init__((k.lower(), v) for k, v in headers.items())

    def get(self, key, default=None):  # type: ignore[override]
        return super().get(key.lower(), default)


@dataclass
class RemoteRepo:
    """A repo on a hosting platform, before it is cloned locally."""

    platform: str          # "github" | "gitlab" | "bitbucket"
    owner: str             # org / group path (used for Originating company)
    name: str              # repo / project slug
    clone_url: str         # https URL without credentials
    default_branch: str | None = None
    is_fork: bool | None = None
    is_private: bool | None = None  # None = unknown (e.g. local mode)
    project_id: int | None = None  # GitLab numeric id, if known

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


class GitProvider(ABC):
    platform: str = "git"

    def __init__(self, token: str | None = None, host: str | None = None) -> None:
        self.token = token
        self.host = host

    # --- API surface used by remote.py and the VCS collector -----------------
    @abstractmethod
    def list_repos(self, org: str) -> list[RemoteRepo]:
        """Every non-archived repo under an org/group."""

    @abstractmethod
    def get_repo(self, owner: str, name: str) -> RemoteRepo:
        """Resolve a single repo's metadata."""

    @abstractmethod
    def pr_stats(self, repo: RemoteRepo) -> tuple[int, int]:
        """(total merged PRs/MRs, reviewed PRs/MRs)."""

    def is_fork(self, repo: RemoteRepo) -> bool:
        if repo.is_fork is None:
            repo.is_fork = self._resolve_fork(repo)
        return bool(repo.is_fork)

    @abstractmethod
    def _resolve_fork(self, repo: RemoteRepo) -> bool: ...

    @abstractmethod
    def auth_clone_url(self, repo: RemoteRepo) -> str:
        """HTTPS clone URL with the token embedded for non-interactive clones."""

    # --- shared HTTP helpers --------------------------------------------------
    def _headers(self) -> dict[str, str]:
        return {}

    def _get_json(self, url: str):
        req = urllib.request.Request(url, headers={"User-Agent": "codebase-profiler",
                                                   **self._headers()})
        try:
            with urllib.request.urlopen(req, timeout=60, context=_SSL_CONTEXT) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body), _CIHeaders(resp.headers)
        except urllib.error.HTTPError as exc:
            raise ProviderError(f"{exc.code} {exc.reason} for {url}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ProviderError(f"network error for {url}: {exc}") from exc

    def _post_json(self, url: str, payload: dict):
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={"User-Agent": "codebase-profiler", "Content-Type": "application/json",
                     **self._headers()},
        )
        try:
            with urllib.request.urlopen(req, timeout=120, context=_SSL_CONTEXT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise ProviderError(f"{exc.code} {exc.reason} for {url}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ProviderError(f"network error for {url}: {exc}") from exc


def parse_repo_target(target: str) -> tuple[str | None, str, str]:
    """Parse ``--repo`` input into (platform_or_None, owner, name).

    Accepts ``owner/name``, full HTTPS/SSH URLs for github.com or gitlab.com, and
    GitLab nested groups (``group/subgroup/project``).
    """
    t = target.strip()
    platform = None
    if t.startswith("http://") or t.startswith("https://"):
        parsed = urllib.parse.urlparse(t)
        platform = _platform_from_host(parsed.netloc)
        path = parsed.path
    elif t.startswith("git@"):
        host, _, path = t[4:].partition(":")
        platform = _platform_from_host(host)
    else:
        path = t
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    parts = path.split("/")
    if len(parts) < 2:
        raise ValueError(f"cannot parse repo target: {target!r}")
    owner = "/".join(parts[:-1])  # keep nested GitLab groups in owner
    name = parts[-1]
    return platform, owner, name


def parse_org_target(target: str) -> tuple[str | None, str, str | None]:
    """Parse ``--organization`` input into (platform_or_None, org_path, host_or_None).

    Accepts a bare org/group name (``your-group``, ``group/subgroup``) or a full URL
    (``https://gitlab.com/your-group``, ``https://github.com/your-org``). For a URL the
    platform (and a self-hosted host) are inferred so ``--platform`` isn't required.
    """
    t = target.strip()
    platform = None
    host = None
    if t.startswith("http://") or t.startswith("https://"):
        parsed = urllib.parse.urlparse(t)
        platform = _platform_from_host(parsed.netloc)
        if platform is None and parsed.netloc:
            host = parsed.netloc  # self-hosted; caller may still need --platform
        path = parsed.path
    elif t.startswith("git@"):
        host_part, _, path = t[4:].partition(":")
        platform = _platform_from_host(host_part)
        if platform is None and host_part:
            host = host_part
    else:
        path = t
    org = path.strip("/")
    if org.endswith(".git"):
        org = org[:-4]
    if not org:
        raise ValueError(f"cannot parse organization target: {target!r}")
    # Bitbucket Cloud project URL: {workspace}/workspace/projects/{project_key}
    if "/workspace/projects/" in org:
        workspace, _, project = org.partition("/workspace/projects/")
        workspace = workspace.split("/")[-1] if workspace else workspace
        project = project.strip("/")
        org = f"{workspace}/{project}" if project else workspace
    return platform, org, host


def _platform_from_host(host: str) -> str | None:
    host = host.lower()
    if "github" in host:
        return "github"
    if "gitlab" in host:
        return "gitlab"
    if "bitbucket" in host:
        return "bitbucket"
    return None
