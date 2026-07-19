"""GitLab client: per-project MR/issue fetching (REST v4) plus the shared
project-listing and raw pagination primitives used by every GitLab caller.

`GitLabClient` is moved largely unchanged from `eval/platform_clients.py` --
it keeps that module's own `retry_api_call` policy for its REST calls.
`list_projects`/`list_top_level_groups`/`paginate` are new consolidated
replacements for the ~3 duplicate GitLab listing implementations found
across this repo, built on `request_with_retry` and reading `X-Next-Page`
through `base.ci_headers` -- without that, HTTP/2 lowercasing the header
name silently caps pagination at the first 100 results, a bug that was live
in 6 of 7 GitLab callers found in the audit.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Dict, List, Optional

import requests

from .base import PlatformClient, ci_headers, request_with_retry, retry_api_call, _is_bot_username
from .errors import PlatformError

logger = logging.getLogger(__name__)


class GitLabClient(PlatformClient):
    def __init__(self, owner: str, repo_name: str, token: Optional[str] = None, base_url: str = "https://gitlab.com"):
        super().__init__(owner, repo_name, token)
        self.base_url = base_url.rstrip("/")
        self.api_url = f"{self.base_url}/api/v4"
        self.project_id = requests.utils.quote(self.repo_full_name, safe="")
        self.headers = {"Accept": "application/json"}
        if self.token:
            self.headers["PRIVATE-TOKEN"] = self.token

    def fetch_prs(self, cursor: Optional[str] = None, page_size: int = 50, start_date: Optional[datetime] = None) -> dict:
        params = {"state": "merged", "per_page": page_size, "order_by": "created_at", "sort": "desc"}
        if cursor:
            params["page"] = cursor
        if start_date:
            params["created_after"] = start_date.isoformat()

        url = f"{self.api_url}/projects/{self.project_id}/merge_requests"

        def _make_request():
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            response.raise_for_status()
            return response

        response = retry_api_call(_make_request)
        data = response.json()
        next_page = response.headers.get("X-Next-Page", "")

        pr_nodes = []
        for mr in data:
            mr_iid = mr.get("iid")
            files = self._fetch_mr_changes(mr_iid)
            mr_details = self._fetch_mr_details(mr_iid)

            linked_issues = []
            body = mr.get("description", "") or ""
            issue_numbers = self.extract_issue_number_from_text(body)
            issue_numbers.extend(self._fetch_closing_issues(mr_iid))
            for issue_num in set(issue_numbers):
                issue_data = self.fetch_issue(issue_num)
                if issue_data:
                    linked_issues.append(issue_data)

            author = mr.get("author", {}) or {}
            author_login = author.get("username", "") or ""
            diff_refs = mr.get("diff_refs") or mr_details.get("diff_refs") or {}

            pr_nodes.append(
                {
                    "number": mr_iid,
                    "title": mr.get("title", ""),
                    "body": body,
                    "baseRefOid": diff_refs.get("base_sha", ""),
                    "headRefOid": mr.get("sha", "") or mr_details.get("sha", "") or diff_refs.get("head_sha", ""),
                    "baseRefName": mr.get("target_branch", ""),
                    "headRefName": mr.get("source_branch", ""),
                    "mergedAt": mr.get("merged_at", ""),
                    "createdAt": mr.get("created_at", ""),
                    "url": mr.get("web_url", ""),
                    "author": {"login": author_login, "isBot": _is_bot_username(author_login), "__typename": "User"},
                    "files": {"nodes": files},
                    "closingIssuesReferences": {"nodes": linked_issues},
                    "labels": {"nodes": [{"name": label} for label in (mr.get("labels") or [])]},
                }
            )

        primary_language_name = None
        try:
            languages = self.fetch_repo_languages()
            if languages:
                primary_language_name = max(languages, key=languages.get)
        except Exception:
            pass

        return {
            "data": {
                "repository": {
                    "primaryLanguage": {"name": primary_language_name},
                    "owner": {"login": self.owner},
                    "name": self.repo_name,
                    "pullRequests": {
                        "pageInfo": {"hasNextPage": bool(next_page), "endCursor": next_page or None},
                        "nodes": pr_nodes,
                    },
                }
            }
        }

    def _fetch_mr_details(self, mr_iid: int) -> dict:
        try:
            url = f"{self.api_url}/projects/{self.project_id}/merge_requests/{mr_iid}"

            def _make_request():
                response = requests.get(url, headers=self.headers, timeout=30)
                response.raise_for_status()
                return response.json()

            return retry_api_call(_make_request) or {}
        except Exception:
            return {}

    def _fetch_mr_changes(self, mr_iid: int) -> List[dict]:
        try:
            url = f"{self.api_url}/projects/{self.project_id}/merge_requests/{mr_iid}/changes"

            def _make_request():
                response = requests.get(url, headers=self.headers, timeout=30)
                response.raise_for_status()
                return response.json()

            mr_data = retry_api_call(_make_request)
            files = []
            for change in mr_data.get("changes", []):
                diff_text = change.get("diff", "")
                additions = sum(1 for line in diff_text.split("\n") if line.startswith("+") and not line.startswith("+++"))
                deletions = sum(1 for line in diff_text.split("\n") if line.startswith("-") and not line.startswith("---"))
                if change.get("new_file"):
                    change_type = "ADDED"
                elif change.get("deleted_file"):
                    change_type = "DELETED"
                elif change.get("renamed_file"):
                    change_type = "RENAMED"
                else:
                    change_type = "MODIFIED"
                files.append(
                    {
                        "path": change.get("new_path") or change.get("old_path", ""),
                        "changeType": change_type,
                        "additions": additions,
                        "deletions": deletions,
                    }
                )
            return files
        except Exception:
            return []

    def _fetch_closing_issues(self, mr_iid: int) -> List[int]:
        try:
            url = f"{self.api_url}/projects/{self.project_id}/merge_requests/{mr_iid}/closes_issues"

            def _make_request():
                response = requests.get(url, headers=self.headers, timeout=30)
                response.raise_for_status()
                return response.json()

            issues = retry_api_call(_make_request)
            return [issue.get("iid") for issue in issues if issue.get("iid")]
        except Exception:
            return []

    def fetch_issue(self, issue_number: int) -> Optional[dict]:
        try:
            url = f"{self.api_url}/projects/{self.project_id}/issues/{issue_number}"

            def _make_request():
                response = requests.get(url, headers=self.headers, timeout=30)
                response.raise_for_status()
                return response.json()

            issue = retry_api_call(_make_request)
            return {
                "number": issue.get("iid"),
                "title": issue.get("title", ""),
                "body": issue.get("description", "") or "",
                "state": "CLOSED" if issue.get("state") == "closed" else issue.get("state", "").upper(),
                "__typename": "Issue",
            }
        except Exception:
            return None

    def get_repo_url(self, include_token: bool = False) -> str:
        host = self.base_url.replace("https://", "").replace("http://", "")
        if include_token and self.token:
            return f"https://oauth2:{self.token}@{host}/{self.repo_full_name}.git"
        return f"{self.base_url}/{self.repo_full_name}.git"

    def extract_issue_number_from_text(self, text: str) -> List[int]:
        if not text:
            return []
        issue_numbers = []
        issue_numbers.extend([int(m) for m in re.findall(r"(?<!\!)#(\d+)", text)])
        issue_numbers.extend([int(m) for m in re.findall(r"https?://[^/\s]+/.+?/-/issues/(\d+)", text)])
        issue_numbers.extend(
            [int(m) for m in re.findall(r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)", text, flags=re.IGNORECASE)]
        )
        return list(set(issue_numbers))

    def fetch_repo_languages(self) -> Optional[Dict[str, int]]:
        try:
            url = f"{self.api_url}/projects/{self.project_id}/languages"

            def _make_request():
                response = requests.get(url, headers=self.headers, timeout=30)
                response.raise_for_status()
                return response.json()

            languages = retry_api_call(_make_request)
            if not languages:
                return None
            return {lang: int(float(weight) * 100) for lang, weight in languages.items()}
        except Exception as e:
            logger.debug(f"Failed to fetch repository languages from GitLab API: {e}")
            return None

    def fetch_issue_count(self) -> dict:
        try:
            base_url = f"{self.api_url}/projects/{self.project_id}/issues"

            def _count(state: str) -> int:
                def _make_request():
                    response = requests.get(
                        base_url,
                        headers=self.headers,
                        params={"state": state, "per_page": 1},
                        timeout=30,
                    )
                    response.raise_for_status()
                    return response

                response = retry_api_call(_make_request)
                total_header = response.headers.get("X-Total")
                if total_header is not None:
                    try:
                        return int(total_header)
                    except ValueError:
                        pass
                return len(response.json() or [])

            open_count = _count("opened")
            closed_count = _count("closed")
            return {"open": open_count, "closed": closed_count, "total": open_count + closed_count}
        except Exception:
            return {"open": 0, "closed": 0, "total": 0}

    def fetch_patch(self, base_commit: str, head_commit: str) -> Optional[str]:
        try:
            url = f"{self.api_url}/projects/{self.project_id}/repository/compare"

            def _make_request():
                response = requests.get(
                    url,
                    headers=self.headers,
                    params={"from": base_commit, "to": head_commit},
                    timeout=30,
                )
                response.raise_for_status()
                return response.json()

            data = retry_api_call(_make_request)
            diffs = data.get("diffs", []) or []
            if not diffs:
                return None

            chunks = []
            for item in diffs:
                diff_text = item.get("diff", "")
                if diff_text:
                    old_path = item.get("old_path") or item.get("new_path") or ""
                    new_path = item.get("new_path") or item.get("old_path") or ""

                    if item.get("new_file"):
                        old_marker = "/dev/null"
                        new_marker = f"b/{new_path}"
                    elif item.get("deleted_file"):
                        old_marker = f"a/{old_path}"
                        new_marker = "/dev/null"
                    else:
                        old_marker = f"a/{old_path}"
                        new_marker = f"b/{new_path}"

                    header = (
                        f"diff --git a/{old_path} b/{new_path}\n"
                        f"--- {old_marker}\n"
                        f"+++ {new_marker}\n"
                    )
                    chunks.append(header + diff_text)
            return "\n".join(chunks) if chunks else None
        except Exception:
            return None


def gitlab_api(host: str = "gitlab.com") -> str:
    host = host.rstrip("/")
    base = host if host.startswith(("http://", "https://")) else f"https://{host}"
    return f"{base}/api/v4"


def gitlab_headers(token: str) -> dict[str, str]:
    headers = {"Accept": "application/json", "User-Agent": "org-analyser-platforms"}
    if token:
        headers["PRIVATE-TOKEN"] = token
    return headers


def paginate(session: requests.Session, url: str, params: Optional[dict] = None) -> List[dict]:
    """Raw REST pagination via `X-Next-Page`, read case-insensitively.

    Escape hatch for callers that need raw API dicts rather than a normalized
    project-name list.
    """
    results: List[dict] = []
    query = dict(params or {})
    query.setdefault("per_page", 100)
    while True:
        response = request_with_retry(session, "GET", url, params=query)
        if response is None:
            break
        batch = response.json()
        if not isinstance(batch, list) or not batch:
            break
        results.extend(batch)
        next_page = ci_headers(response.headers).get("X-Next-Page")
        if not next_page:
            break
        query["page"] = next_page
    return results


def list_projects(token: str, group: str, host: str = "gitlab.com") -> list[str]:
    """List non-archived project path_with_namespace values for a GitLab group."""
    session = requests.Session()
    session.headers.update(gitlab_headers(token))
    api = gitlab_api(host)
    encoded = requests.utils.quote(group, safe="")
    items = paginate(
        session,
        f"{api}/groups/{encoded}/projects",
        params={"include_subgroups": "true", "archived": "false"},
    )
    if not items:
        raise PlatformError(f"no projects found for group {group!r} on {host}")
    return [p["path_with_namespace"] for p in items]


def list_top_level_groups(token: str, host: str = "gitlab.com") -> list[str]:
    """Top-level groups a token can see (subgroups already covered by a
    listed parent are excluded)."""
    session = requests.Session()
    session.headers.update(gitlab_headers(token))
    api = gitlab_api(host)
    groups = paginate(session, f"{api}/groups", params={"min_access_level": "10"})
    paths = sorted({g["full_path"] for g in groups if g.get("full_path")})
    top_level: list[str] = []
    for path in paths:
        if any(path.startswith(parent + "/") for parent in top_level):
            continue
        top_level.append(path)
    return top_level
