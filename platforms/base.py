"""Shared platform-client primitives: the `PlatformClient` ABC, one retry/
backoff policy for every GitHub/GitLab/Bitbucket HTTP call, and a
case-insensitive header lookup.

`request_with_retry` consolidates six independently-drifted retry
implementations found across this repo (audited in the platforms/
migration) into the single most robust policy among them
(`analysis/repo_analyzer.py`'s `HttpBase`/`GitHubProvider._rate_limit_wait`),
plus one deliberate behavior change: bad auth (401/403 that isn't a rate
limit) raises `PlatformAuthError` instead of `SystemExit`, so a caller
processing many repos can decide for itself whether one repo's bad auth is
fatal, instead of the whole batch dying.

`retry_api_call` and `_is_bot_username` are ported verbatim from
`eval/platform_clients.py` -- they back the per-repo `GitHubClient`/
`GitLabClient`/`BitbucketClient` PR-fetching methods moved largely
unchanged into `platforms/{github,gitlab,bitbucket}.py`, and are kept here
once instead of tripled across those three modules. This is a distinct,
older policy from `request_with_retry`, which backs only the newer
`list_repos`/`list_projects`/`paginate` functions.
"""

from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Callable, Dict, List, Optional

import requests

from .errors import PlatformAuthError, PlatformRateLimitError

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY_BASE = 1


class PlatformClient(ABC):
    def __init__(self, owner: str, repo_name: str, token: Optional[str] = None):
        self.owner = owner
        self.repo_name = repo_name
        self.repo_full_name = f"{owner}/{repo_name}"
        self.token = token

    @abstractmethod
    def fetch_prs(self, cursor: Optional[str] = None, page_size: int = 50, start_date: Optional[datetime] = None) -> dict:
        pass

    @abstractmethod
    def fetch_issue(self, issue_number: int) -> Optional[dict]:
        pass

    @abstractmethod
    def get_repo_url(self, include_token: bool = False) -> str:
        pass

    @abstractmethod
    def extract_issue_number_from_text(self, text: str) -> List[int]:
        pass

    @abstractmethod
    def fetch_repo_languages(self) -> Optional[Dict[str, int]]:
        pass

    @abstractmethod
    def fetch_issue_count(self) -> dict:
        pass

    @abstractmethod
    def fetch_patch(self, base_commit: str, head_commit: str) -> Optional[str]:
        pass


class _CIHeaders(dict):
    """Case-insensitive view of HTTP response headers.

    HTTP/2 lowercases header names, so ``dict(resp.headers).get("X-Next-Page")``
    can miss a header that is actually present as ``x-next-page``. That
    silently capped GitLab pagination (PR/MR counts, group repo lists) at the
    first 100 results in every caller that didn't go through this helper.
    """

    def __init__(self, headers) -> None:
        super().__init__((k.lower(), v) for k, v in headers.items())

    def get(self, key, default=None):  # type: ignore[override]
        return super().get(key.lower(), default)


def ci_headers(headers) -> _CIHeaders:
    """Wrap a response's headers so lookups are case-insensitive."""
    return _CIHeaders(headers)


def _retry_after_seconds(headers, default: int = 60) -> int:
    """Parse Retry-After safely (it may be seconds OR an HTTP date)."""
    value = headers.get("Retry-After", "")
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


def _rate_limit_wait_seconds(response: requests.Response) -> Optional[int]:
    """How long to wait before retrying a rate-limited response, or None."""
    if response.status_code not in (403, 429):
        return None
    headers = ci_headers(response.headers)
    if headers.get("Retry-After"):
        return _retry_after_seconds(headers, default=60)
    if headers.get("X-RateLimit-Remaining") == "0":
        # X-RateLimit-Limit: 0 means the endpoint has zero quota for this
        # caller (e.g. GitHub's GraphQL API for an unauthenticated request) --
        # permanently zero, not temporarily exhausted. Waiting for "reset"
        # would just repeat forever; this needs a token, not a retry.
        if headers.get("X-RateLimit-Limit") == "0":
            return None
        try:
            reset = int(headers.get("X-RateLimit-Reset", 0))
        except (TypeError, ValueError):
            reset = 0
        wait = max(5, reset - int(time.time()) + 2)
        return min(wait, 3600)
    if response.status_code == 403 and "rate limit" in response.text.lower():
        # Secondary/abuse rate limit: no Retry-After or exhausted
        # X-RateLimit-Remaining header, but GitHub still says to back off.
        # Per GitHub's own guidance, wait at least 60s.
        return 60
    if response.status_code == 429:
        # A bare 429 with none of the above signals still unambiguously means
        # "too many requests" per HTTP semantics -- e.g. Bitbucket's burst/
        # secondary limit returns 429 with no Retry-After and a non-zero
        # X-Ratelimit-Remaining (a *different* counter than the one that just
        # tripped). Back off with a conservative default rather than treating
        # the absence of GitHub-shaped headers as "not rate limited."
        return 30
    return None


def request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    max_retries: int = 6,
    **kwargs,
) -> Optional[requests.Response]:
    """One shared retry/backoff policy for every platform client.

    - Network errors (ConnectionError/Timeout): retry with exponential
      backoff, capped at 30s, up to max_retries times.
    - Rate limiting, checked in order: Retry-After header: sleep that many
      seconds and retry. X-RateLimit-Remaining == "0" + X-RateLimit-Reset:
      sleep until reset (+ small buffer), capped at 3600s, and retry.
      GitHub's secondary/abuse limit (403 with "rate limit" in the response
      text but no Retry-After/X-RateLimit-Remaining signal): sleep 60s and
      retry.
    - 404: return None (not found, not an error -- callers check for this).
    - Any other 4xx (chiefly 401/403 that isn't a rate limit): raise
      PlatformAuthError immediately, no retry -- this is deliberately a
      *change* from repo_analyzer.py's current `raise SystemExit(...)` on
      401/403, which kills the whole process over one repo's bad auth; the
      shared client raises a catchable exception instead so each caller can
      decide whether that's fatal for its own run.
    - 5xx: retry with the same exponential backoff as network errors.
    - Anything else: return the response as-is (2xx, or unhandled status
      the caller should check itself).
    """
    timeout = kwargs.pop("timeout", 60)
    for attempt in range(max_retries):
        try:
            response = session.request(method, url, timeout=timeout, **kwargs)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            if attempt == max_retries - 1:
                logger.warning("network error, giving up on %s: %s", url, exc)
                return None
            time.sleep(min(2 ** attempt, 30))
            continue

        wait = _rate_limit_wait_seconds(response)
        if wait is not None:
            if attempt == max_retries - 1:
                raise PlatformRateLimitError(
                    f"still rate limited on {url} after {max_retries} attempts"
                )
            logger.warning("rate limited on %s -- sleeping %ds", url, wait)
            time.sleep(wait)
            continue

        if response.status_code == 404:
            return None

        if 500 <= response.status_code < 600:
            if attempt == max_retries - 1:
                return response
            time.sleep(min(2 ** attempt, 30))
            continue

        if 400 <= response.status_code < 500:
            raise PlatformAuthError(
                f"{response.status_code} {response.reason} for {url}: {response.text[:300]}"
            )

        return response
    return None


def retry_api_call(func: Callable, max_retries: int = MAX_RETRIES, *args, **kwargs):
    retries = 0
    last_exception = None

    while retries <= max_retries:
        try:
            return func(*args, **kwargs)
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response else 0
            if status_code == 429:
                retry_after = e.response.headers.get(
                    "X-RateLimit-Reset",
                    e.response.headers.get("Retry-After", 60),
                )
                try:
                    wait_time = int(retry_after)
                except ValueError:
                    wait_time = 60
                logger.warning(f"Rate limit hit. Waiting {wait_time} seconds...")
                time.sleep(wait_time)
                retries += 1
                last_exception = e
                continue
            if 500 <= status_code < 600 and retries < max_retries:
                wait_time = RETRY_DELAY_BASE * (2 ** retries)
                logger.warning(f"Server error {status_code}. Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
                retries += 1
                last_exception = e
                continue
            raise
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            if retries < max_retries:
                wait_time = RETRY_DELAY_BASE * (2 ** retries)
                logger.warning(f"Connection error. Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
                retries += 1
                last_exception = e
                continue
            raise
        except Exception as e:
            if retries < max_retries:
                wait_time = RETRY_DELAY_BASE * (2 ** retries)
                logger.warning(f"Unexpected error: {str(e)}. Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
                retries += 1
                last_exception = e
                continue
            raise

    if last_exception:
        raise last_exception


def _is_bot_username(username: str) -> bool:
    if not username:
        return False
    username_lower = username.lower()
    if username.endswith("[bot]"):
        return True
    common_bots = [
        "dependabot",
        "renovate",
        "codecov",
        "greenkeeper",
        "snyk-bot",
        "pyup-bot",
        "whitesource",
        "mergify",
        "stale",
        "github-actions",
        "allcontributors",
        "imgbot",
        "k8s-ci-robot",
        "k8s-bot",
        "k8s-mergebot",
    ]
    return username_lower in common_bots


def _looks_like_local_path(s: str) -> bool:
    """Heuristic: is this a filesystem path rather than a remote repo spec?"""
    if s in (".", "..") or s.startswith("/") or s.startswith("~"):
        return True
    if s.startswith("./") or s.startswith("../"):
        return True
    if len(s) >= 2 and s[1] == ":":
        return True
    return os.path.isdir(s)


def detect_platform(repo_string: str, explicit_platform: Optional[str] = "auto") -> str:
    """Guess which platform a repo spec refers to (github/gitlab/bitbucket/svn/local)."""
    if explicit_platform:
        explicit_platform = explicit_platform.lower()
        if explicit_platform in ["github", "bitbucket", "gitlab", "svn", "local"]:
            return explicit_platform
        if explicit_platform != "auto":
            raise ValueError(
                f"Invalid platform: {explicit_platform}. "
                "Must be 'github', 'bitbucket', 'gitlab', 'svn', 'local', or 'auto'"
            )

    repo_string = repo_string.strip()
    repo_lower = repo_string.lower()

    if _looks_like_local_path(repo_string):
        return "local"

    if repo_lower.startswith("svn:") or repo_lower.startswith("svn+"):
        return "svn"
    if repo_lower.startswith("bitbucket:"):
        return "bitbucket"
    if repo_lower.startswith("github:"):
        return "github"
    if repo_lower.startswith("gitlab:"):
        return "gitlab"

    if "bitbucket.org" in repo_lower:
        return "bitbucket"
    if "gitlab." in repo_lower or "gitlab/" in repo_lower:
        return "gitlab"
    if "github.com" in repo_lower:
        return "github"
    if repo_lower.startswith("svn://"):
        return "svn"
    return "github"
