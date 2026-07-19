"""GitLab provider — REST v4 for projects, merge requests, fork status."""

from __future__ import annotations

import logging
import urllib.parse

from .base import GitProvider, ProviderError, RemoteRepo

logger = logging.getLogger(__name__)


class GitLabProvider(GitProvider):
    platform = "gitlab"

    def __init__(self, token: str | None = None, host: str | None = None) -> None:
        super().__init__(token, host)
        self.web_host = host or "gitlab.com"
        self.api = f"https://{self.web_host}/api/v4"

    def _headers(self) -> dict[str, str]:
        return {"PRIVATE-TOKEN": self.token} if self.token else {}

    def list_repos(self, org: str) -> list[RemoteRepo]:
        group = urllib.parse.quote(org, safe="")
        repos: list[RemoteRepo] = []
        page = 1
        while True:
            url = (
                f"{self.api}/groups/{group}/projects"
                f"?per_page=100&page={page}&include_subgroups=true&archived=false"
            )
            data, headers = self._get_json(url)
            if not data:
                break
            for p in data:
                repos.append(self._to_repo(p))
            if not headers.get("X-Next-Page"):
                break
            page += 1
        if not repos:
            raise ProviderError(f"no projects found for group '{org}' on {self.web_host}")
        return repos

    def get_repo(self, owner: str, name: str) -> RemoteRepo:
        pid = urllib.parse.quote(f"{owner}/{name}", safe="")
        data, _ = self._get_json(f"{self.api}/projects/{pid}")
        return self._to_repo(data)

    def _to_repo(self, p: dict) -> RemoteRepo:
        namespace = (p.get("namespace") or {}).get("full_path") or \
            p["path_with_namespace"].rsplit("/", 1)[0]
        return RemoteRepo(
            platform="gitlab",
            owner=namespace,
            name=p["path"],
            clone_url=p["http_url_to_repo"],
            default_branch=p.get("default_branch"),
            is_fork=bool(p.get("forked_from_project")),
            # GitLab visibility is public / internal / private; only "public" is
            # openly crawlable for public training corpora.
            is_private=(p.get("visibility") not in (None, "public")),
            project_id=p.get("id"),
        )

    def _project_id(self, repo: RemoteRepo) -> str:
        if repo.project_id is not None:
            return str(repo.project_id)
        return urllib.parse.quote(repo.full_name, safe="")

    def pr_stats(self, repo: RemoteRepo) -> tuple[int, int]:
        pid = self._project_id(repo)
        total = reviewed = 0
        page = 1
        while True:
            url = (
                f"{self.api}/projects/{pid}/merge_requests"
                f"?state=merged&per_page=100&page={page}"
            )
            data, headers = self._get_json(url)
            if not data:
                break
            for mr in data:
                total += 1
                # A merged MR counts as reviewed if it carries human discussion or
                # approvals. user_notes_count excludes system notes.
                if mr.get("user_notes_count", 0) > 0:
                    reviewed += 1
            if not headers.get("X-Next-Page"):
                break
            page += 1
        return total, reviewed

    def _resolve_fork(self, repo: RemoteRepo) -> bool:
        data, _ = self._get_json(f"{self.api}/projects/{self._project_id(repo)}")
        return bool(data.get("forked_from_project"))

    def auth_clone_url(self, repo: RemoteRepo) -> str:
        if not self.token:
            return repo.clone_url
        return repo.clone_url.replace("https://", f"https://oauth2:{self.token}@", 1)
