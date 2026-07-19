"""Bitbucket Cloud provider — REST 2.0 for repos, pull requests, fork status.

Auth decisions (Basic vs. Bearer, and the git-clone-specific ATATT sentinel) delegate to
`platforms.bitbucket.resolve_bitbucket_auth`/`resolve_bitbucket_git_auth`, the single
source of truth for that 3-branch decision. Username resolution from the environment
(`BITBUCKET_USERNAME`, falling back to `ATLASSIAN_EMAIL`/`BITBUCKET_EMAIL`) stays here --
`platforms.bitbucket`'s functions take username as an explicit parameter, not an env
lookup, since not every caller resolves it from the same place.
"""

from __future__ import annotations

import base64
import logging
import os
import urllib.parse

from platforms.bitbucket import resolve_bitbucket_auth, resolve_bitbucket_git_auth
from platforms.errors import PlatformAuthError

from .base import GitProvider, ProviderError, RemoteRepo

logger = logging.getLogger(__name__)


class BitbucketProvider(GitProvider):
    platform = "bitbucket"

    def __init__(self, token: str | None = None, host: str | None = None) -> None:
        super().__init__(token, host)
        self.web_host = host or "bitbucket.org"
        if self.web_host == "bitbucket.org":
            self.api = "https://api.bitbucket.org/2.0"
        else:
            # Bitbucket Data Center / Server uses the 1.0 REST API on a custom host.
            self.api = f"https://{self.web_host}/rest/api/1.0"
        self.username = os.environ.get("BITBUCKET_USERNAME")

    def _resolved_username(self) -> str:
        """User/email to feed into `platforms.bitbucket`'s auth functions.

        Atlassian API tokens (ATATT…) must use the Atlassian account *email*, so that
        branch skips `BITBUCKET_USERNAME` entirely and looks only at the email vars.
        Bitbucket app passwords (or workspace access tokens) use the Bitbucket
        *username* (not email), preferring `BITBUCKET_USERNAME`.
        """
        if self.token and self.token.startswith("ATATT"):
            for key in ("ATLASSIAN_EMAIL", "BITBUCKET_EMAIL"):
                val = os.environ.get(key)
                if val:
                    return val
            return ""
        if self.username:
            return self.username
        for key in ("ATLASSIAN_EMAIL", "BITBUCKET_EMAIL"):
            val = os.environ.get(key)
            if val:
                return val
        return ""

    def _headers(self) -> dict[str, str]:
        if not self.token:
            return {}
        try:
            scheme, user = resolve_bitbucket_auth(self.token, self._resolved_username())
        except PlatformAuthError as exc:
            # Re-raise as ProviderError -- this module's own exception contract, which
            # every caller in profiler/ already catches instead of platforms/'s types.
            raise ProviderError(str(exc)) from exc
        if scheme == "basic":
            raw = f"{user}:{self.token}".encode()
            return {"Authorization": f"Basic {base64.b64encode(raw).decode()}"}
        return {"Authorization": f"Bearer {self.token}"}

    def list_repos(self, org: str) -> list[RemoteRepo]:
        if self.web_host == "bitbucket.org":
            self._verify_cloud_auth()
        if self.web_host != "bitbucket.org":
            return self._list_server(org)
        workspace, project_key = _split_workspace_project(org)
        return self._list_cloud(workspace, project_key)

    def _verify_cloud_auth(self) -> None:
        if not self.token:
            raise ProviderError(
                "No Bitbucket token found. Set BITBUCKET_TOKEN (or pass --token), "
                "or BITBUCKET_APP_PASSWORD for an app password."
            )
        try:
            self._get_json(f"{self.api}/user")
        except ProviderError as exc:
            if "401" not in str(exc):
                raise
            hint = _auth_hint(self.token)
            raise ProviderError(f"Bitbucket authentication failed (401). {hint}") from exc

    def _list_cloud(self, workspace: str, project_key: str | None) -> list[RemoteRepo]:
        ws = urllib.parse.quote(workspace, safe="")
        url = f"{self.api}/repositories/{ws}"
        if project_key:
            q = urllib.parse.quote(f'project.key="{project_key}"')
            url = f"{url}?q={q}"
        repos = [self._to_repo(r) for r in self._paginate(url)]
        if not repos:
            scope = f"project '{project_key}' in workspace '{workspace}'" if project_key else f"workspace '{workspace}'"
            raise ProviderError(f"no repositories found for {scope} on {self.web_host}")
        return repos

    def _list_server(self, project_key: str) -> list[RemoteRepo]:
        proj = urllib.parse.quote(project_key, safe="")
        url = f"{self.api}/projects/{proj}/repos"
        data, _ = self._get_json(url)
        values = data.get("values", []) if isinstance(data, dict) else data
        repos = [self._to_server_repo(r, project_key) for r in values or []]
        if not repos:
            raise ProviderError(f"no repositories found for project '{project_key}' on {self.web_host}")
        return repos

    def get_repo(self, owner: str, name: str) -> RemoteRepo:
        if self.web_host == "bitbucket.org":
            self._verify_cloud_auth()
        workspace = owner.split("/")[0]
        if self.web_host == "bitbucket.org":
            ws = urllib.parse.quote(workspace, safe="")
            slug = urllib.parse.quote(name, safe="")
            data, _ = self._get_json(f"{self.api}/repositories/{ws}/{slug}")
            return self._to_repo(data)
        proj = urllib.parse.quote(workspace, safe="")
        slug = urllib.parse.quote(name, safe="")
        data, _ = self._get_json(f"{self.api}/projects/{proj}/repos/{slug}")
        return self._to_server_repo(data, workspace)

    def _to_repo(self, r: dict) -> RemoteRepo:
        workspace = (r.get("workspace") or {}).get("slug") or r.get("full_name", "").split("/")[0]
        name = r.get("slug") or r.get("name", "")
        return RemoteRepo(
            platform="bitbucket",
            owner=workspace,
            name=name,
            clone_url=_https_clone(r.get("links", {}), workspace, name),
            default_branch=(r.get("mainbranch") or {}).get("name"),
            is_fork=r.get("parent") is not None,
            is_private=bool(r.get("is_private")),
        )

    def _to_server_repo(self, r: dict, project_key: str) -> RemoteRepo:
        name = r.get("slug") or r.get("name", "")
        return RemoteRepo(
            platform="bitbucket",
            owner=project_key,
            name=name,
            clone_url=_https_clone(r.get("links", {}), project_key, name),
            default_branch=(r.get("mainbranch") or {}).get("name"),
            is_fork=bool(r.get("origin")),
            is_private=not r.get("public", True),
        )

    def pr_stats(self, repo: RemoteRepo) -> tuple[int, int]:
        if self.web_host != "bitbucket.org":
            return self._server_pr_stats(repo)
        ws = urllib.parse.quote(repo.owner, safe="")
        slug = urllib.parse.quote(repo.name, safe="")
        url = f"{self.api}/repositories/{ws}/{slug}/pullrequests?state=MERGED"
        total = reviewed = 0
        for pr in self._paginate(url):
            total += 1
            if _pullrequest_reviewed(pr):
                reviewed += 1
        return total, reviewed

    def _server_pr_stats(self, repo: RemoteRepo) -> tuple[int, int]:
        proj = urllib.parse.quote(repo.owner, safe="")
        slug = urllib.parse.quote(repo.name, safe="")
        url = f"{self.api}/projects/{proj}/repos/{slug}/pull-requests?state=MERGED"
        data, _ = self._get_json(url)
        values = data.get("values", []) if isinstance(data, dict) else []
        total = len(values)
        reviewed = sum(1 for pr in values if pr.get("open") is False and _pullrequest_reviewed(pr))
        return total, reviewed

    def _resolve_fork(self, repo: RemoteRepo) -> bool:
        fresh = self.get_repo(repo.owner, repo.name)
        return bool(fresh.is_fork)

    def auth_clone_url(self, repo: RemoteRepo) -> str:
        if not self.token:
            return repo.clone_url
        # git-clone-over-HTTPS, not the REST API -- resolve_bitbucket_git_auth, not
        # resolve_bitbucket_auth. Git accepts the "x-bitbucket-api-token-auth" sentinel
        # for an Atlassian API token (ATATT...) regardless of any configured username;
        # the REST API has no such allowance and requires the real account email instead.
        user = resolve_bitbucket_git_auth(self.token, self._resolved_username())
        return repo.clone_url.replace(
            "https://",
            f"https://{urllib.parse.quote(user, safe='')}:{urllib.parse.quote(self.token, safe='')}@",
            1,
        )

    def _paginate(self, start_url: str) -> list[dict]:
        items: list[dict] = []
        url: str | None = start_url
        while url:
            data, _ = self._get_json(url)
            if not isinstance(data, dict):
                break
            items.extend(data.get("values") or [])
            url = data.get("next")
        return items


def _auth_hint(token: str | None) -> str:
    if token and token.startswith("ATATT"):
        return (
            "Atlassian API tokens (ATATT…) need ATLASSIAN_EMAIL=your_atlassian_login_email "
            "and a token created at id.atlassian.com with Bitbucket read scopes. "
            "If that still fails, use a Bitbucket App password instead: unset ATLASSIAN_EMAIL, "
            "set BITBUCKET_USERNAME to your Bitbucket username, and BITBUCKET_TOKEN to the app password."
        )
    return (
        "For app passwords: unset ATLASSIAN_EMAIL, set BITBUCKET_USERNAME to your Bitbucket "
        "username (not email), and BITBUCKET_TOKEN to the app password. "
        "For workspace access tokens: set BITBUCKET_TOKEN only (no username/email)."
    )


def _split_workspace_project(org: str) -> tuple[str, str | None]:
    """``workspace`` or ``workspace/project_key`` (Bitbucket Cloud project filter)."""
    org = org.strip().strip("/")
    if "/workspace/projects/" in org:
        workspace, _, project = org.partition("/workspace/projects/")
        workspace = workspace.split("/")[-1]
        return workspace, project.strip("/") or None
    if "/" in org:
        workspace, project = org.split("/", 1)
        return workspace, project or None
    return org, None


def _https_clone(links: dict, workspace: str, name: str) -> str:
    for link in links.get("clone") or []:
        if link.get("name") == "https":
            return link["href"]
    return f"https://bitbucket.org/{workspace}/{name}.git"


def _pullrequest_reviewed(pr: dict) -> bool:
    if pr.get("comment_count", 0) > 0:
        return True
    for participant in pr.get("participants") or []:
        if participant.get("approved"):
            return True
        if participant.get("state") in ("approved", "changes_requested"):
            return True
    for reviewer in pr.get("reviewers") or []:
        if reviewer.get("approved"):
            return True
    return False
