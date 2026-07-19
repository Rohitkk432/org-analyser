#!/usr/bin/env python3
"""
Merged pull/merge-request counting across GitHub, GitLab, and Bitbucket.

Two subcommands:
  count   - count merged PRs/MRs for specific repos/orgs/groups/workspaces (ad hoc)
  export  - discover every org/group a token can see and export one CSV per
            org/group plus a summary CSV (batch)

Examples:
  export GITHUB_TOKEN=ghp_...
  export GITLAB_TOKEN=glpat-...

  merged-prs count --github-org my-org --gitlab-group my-group
  merged-prs count --github-repo owner/repo --gitlab-project group/project
  merged-prs count --github-org my-org --since 2025-01-01 --json
  merged-prs count --bitbucket-workspace my-workspace
  merged-prs export --tokens-file tokens --output-dir merged-pr-counts
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CSV_FIELDS = ["platform", "org", "repo", "merged_count", "error"]
SUMMARY_FIELDS = ["platform", "org", "repos_total", "merged_total", "token_name", "error"]


# ---------------------------------------------------------------------------
# HTTP + pagination
# ---------------------------------------------------------------------------

def http_get_json(url: str, headers: dict[str, str]) -> tuple[Any, dict[str, str]]:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read().decode("utf-8")
            hdrs = {k: v for k, v in resp.headers.items()}
            return (json.loads(body) if body else None), hdrs
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} for {url}: {detail}") from exc


def paginate_github(url: str, token: str) -> list[Any]:
    items: list[Any] = []
    page = 1
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "org-analyser-merged-prs",
    }
    while True:
        sep = "&" if "?" in url else "?"
        page_url = f"{url}{sep}page={page}"
        data, resp_headers = http_get_json(page_url, headers)
        if not isinstance(data, list):
            break
        items.extend(data)
        if 'rel="next"' not in resp_headers.get("Link", ""):
            break
        page += 1
    return items


def paginate_gitlab(
    base: str,
    path: str,
    token: str,
    params: dict[str, str] | None = None,
) -> list[Any]:
    items: list[Any] = []
    query = dict(params or {})
    query.setdefault("per_page", "100")
    page = 1
    headers = {"PRIVATE-TOKEN": token, "User-Agent": "org-analyser-merged-prs"}

    while True:
        query["page"] = str(page)
        url = f"{base}{path}?{urllib.parse.urlencode(query)}"
        data, resp_headers = http_get_json(url, headers)
        if not isinstance(data, list):
            return data if data is not None else items
        items.extend(data)
        per_page = int(query.get("per_page", "100"))
        next_page = resp_headers.get("X-Next-Page")
        if next_page:
            page = int(next_page)
            continue
        if len(data) < per_page:
            break
        page += 1
    return items


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Invalid date: {value!r}. Use YYYY-MM-DD or ISO8601.")


def in_range(dt_str: str | None, since: datetime | None, until: datetime | None) -> bool:
    if not dt_str:
        return False
    dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    if since and dt < since:
        return False
    if until and dt > until:
        return False
    return True


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------

def github_api(token: str, host: str = "github.com") -> str:
    return "https://api.github.com" if host == "github.com" else f"https://{host}/api/v3"


def github_headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "org-analyser-merged-prs",
    }


def list_github_repos(token: str, org: str, host: str) -> list[str]:
    api = github_api(token, host)
    repos: list[str] = []
    for kind in (f"orgs/{org}/repos", f"users/{org}/repos"):
        batch = paginate_github(f"{api}/{kind}?per_page=100&type=all", token)
        if batch:
            repos = [r["full_name"] for r in batch if not r.get("archived")]
            break
    if not repos:
        raise RuntimeError(f"No GitHub repos found for {org!r}")
    return repos


def list_github_orgs(token: str, host: str = "github.com") -> list[str]:
    api = github_api(token, host)
    orgs: set[str] = set()

    for org in paginate_github(f"{api}/user/orgs?per_page=100", token):
        orgs.add(org["login"])

    repos = paginate_github(
        f"{api}/user/repos?affiliation=owner,collaborator,organization_member&per_page=100",
        token,
    )
    for repo in repos:
        owner = repo.get("owner") or {}
        if owner.get("type") == "Organization":
            orgs.add(owner["login"])

    return sorted(orgs)


_GITHUB_MERGED_COUNT_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    pullRequests(states: MERGED) {
      totalCount
    }
  }
}
"""


def github_graphql(token: str, host: str = "github.com") -> str:
    return "https://api.github.com/graphql" if host == "github.com" else f"https://{host}/api/graphql"


def http_post_json(url: str, headers: dict[str, str], payload: dict[str, Any]) -> Any:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} for {url}: {detail}") from exc


def count_github_merged(
    token: str,
    repo: str,
    host: str,
    since: datetime | None,
    until: datetime | None,
) -> int:
    owner, name = repo.split("/", 1)

    if since is None and until is None:
        data = http_post_json(
            github_graphql(token, host),
            github_headers(token),
            {
                "query": _GITHUB_MERGED_COUNT_QUERY,
                "variables": {"owner": owner, "name": name},
            },
        )
        if data.get("errors"):
            raise RuntimeError(str(data["errors"])[:500])
        repository = (data.get("data") or {}).get("repository")
        if not repository:
            raise RuntimeError(f"Repository not found: {repo}")
        return int(repository["pullRequests"]["totalCount"])

    api = github_api(token, host)
    pulls = paginate_github(
        f"{api}/repos/{owner}/{name}/pulls?state=closed&sort=updated&direction=desc&per_page=100",
        token,
    )
    return sum(
        1 for pr in pulls if pr.get("merged_at") and in_range(pr["merged_at"], since, until)
    )


def github_merged_counts(
    token: str,
    repos: list[str],
    host: str,
    since: datetime | None,
    until: datetime | None,
) -> dict[str, int]:
    return {
        repo: count_github_merged(token, repo, host, since, until)
        for repo in repos
    }


# ---------------------------------------------------------------------------
# GitLab
# ---------------------------------------------------------------------------

def gitlab_api(host: str = "gitlab.com") -> str:
    host = host.rstrip("/")
    if host.startswith("http://") or host.startswith("https://"):
        base = host
    else:
        base = f"https://{host}"
    return f"{base}/api/v4"


def list_gitlab_projects(token: str, group: str, host: str) -> list[str]:
    api = gitlab_api(host)
    encoded = urllib.parse.quote(group, safe="")
    projects = paginate_gitlab(
        api,
        f"/groups/{encoded}/projects",
        token,
        {"include_subgroups": "true", "archived": "false"},
    )
    if not projects:
        raise RuntimeError(f"No GitLab projects found for group {group!r}")
    return [p["path_with_namespace"] for p in projects]


def list_gitlab_top_level_groups(token: str, host: str = "gitlab.com") -> list[str]:
    api = gitlab_api(host)
    groups = paginate_gitlab(api, "/groups", token, {"min_access_level": "10"})
    paths = sorted({g["full_path"] for g in groups if g.get("full_path")})
    top_level: list[str] = []
    for path in paths:
        if any(path.startswith(parent + "/") for parent in top_level):
            continue
        top_level.append(path)
    return top_level


def count_gitlab_merged(
    token: str,
    project: str,
    host: str,
    since: datetime | None,
    until: datetime | None,
) -> int:
    api = gitlab_api(host)
    encoded = urllib.parse.quote(project, safe="")
    params: dict[str, str] = {"state": "merged", "per_page": "100"}

    if since:
        params["updated_after"] = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    if until:
        params["updated_before"] = until.strftime("%Y-%m-%dT%H:%M:%SZ")

    probe_params = {**params, "per_page": "1"}
    url = f"{api}/projects/{encoded}/merge_requests?{urllib.parse.urlencode(probe_params)}"
    _, headers = http_get_json(url, {"PRIVATE-TOKEN": token, "User-Agent": "org-analyser-merged-prs"})
    total = headers.get("X-Total")
    if total is not None:
        return int(total)

    mrs = paginate_gitlab(api, f"/projects/{encoded}/merge_requests", token, params)
    return len(mrs)


def gitlab_merged_counts(
    token: str,
    projects: list[str],
    host: str,
    since: datetime | None,
    until: datetime | None,
) -> dict[str, int]:
    return {
        project: count_gitlab_merged(token, project, host, since, until)
        for project in projects
    }


# ---------------------------------------------------------------------------
# Bitbucket
# ---------------------------------------------------------------------------

def bitbucket_headers(token: str, username: str = "") -> dict[str, str]:
    headers = {"Accept": "application/json", "User-Agent": "org-analyser-merged-prs"}
    if not token:
        return headers  # anonymous: fine for public repos (lower rate limit)
    user = username.strip()
    if user:
        # App password (Bitbucket username) or Atlassian API token (email) → Basic.
        creds = base64.b64encode(f"{user}:{token}".encode()).decode()
        headers["Authorization"] = f"Basic {creds}"
    elif token.startswith("ATATT"):
        # The static "x-bitbucket-api-token-auth" user works for git but NOT the
        # REST API — it returns a misleading "Token is invalid" / empty results.
        raise RuntimeError(
            "Atlassian API token (ATATT…) needs your Atlassian account email. "
            "Set bitbucket_username to that email in the tokens file."
        )
    else:
        # Workspace/Repository/Project access token → Bearer.
        headers["Authorization"] = f"Bearer {token}"
    return headers


def paginate_bitbucket(url: str, token: str, username: str = "") -> list[Any]:
    """Follow Bitbucket's `next` cursor links, collecting every `values` item."""
    items: list[Any] = []
    headers = bitbucket_headers(token, username)
    while url:
        data, _ = http_get_json(url, headers)
        if not isinstance(data, dict):
            break
        items.extend(data.get("values", []))
        url = data.get("next", "")
    return items


def list_bitbucket_repos(token: str, workspace: str, username: str = "") -> list[str]:
    repos = paginate_bitbucket(
        f"https://api.bitbucket.org/2.0/repositories/{workspace}?pagelen=100",
        token, username,
    )
    names = [r["full_name"] for r in repos if r.get("full_name")]
    if not names:
        raise RuntimeError(f"No Bitbucket repos found for {workspace!r}")
    return names


def count_bitbucket_merged(
    token: str,
    repo: str,
    username: str,
    since: datetime | None,
    until: datetime | None,
) -> int:
    workspace, name = repo.split("/", 1)
    base = f"https://api.bitbucket.org/2.0/repositories/{workspace}/{name}/pullrequests?state=MERGED"
    headers = bitbucket_headers(token, username)
    if since is None and until is None:
        # Bitbucket returns the total in `size` on the first page.
        data, _ = http_get_json(f"{base}&pagelen=1", headers)
        if isinstance(data, dict) and "size" in data:
            return int(data["size"])
        # Fallback: full pagination if `size` is absent.
        return len(paginate_bitbucket(f"{base}&pagelen=50", token, username))
    prs = paginate_bitbucket(f"{base}&pagelen=50", token, username)
    return sum(
        1 for pr in prs if in_range(pr.get("updated_on"), since, until)
    )


def bitbucket_merged_counts(
    token: str,
    repos: list[str],
    username: str,
    since: datetime | None,
    until: datetime | None,
) -> dict[str, int]:
    return {
        repo: count_bitbucket_merged(token, repo, username, since, until)
        for repo in repos
    }


# ---------------------------------------------------------------------------
# `count` subcommand — ad hoc counting for explicit repos/orgs/groups
# ---------------------------------------------------------------------------

def _run_count(args: argparse.Namespace) -> int:
    since = parse_date(args.since)
    until = parse_date(args.until)

    github_repos = list(args.github_repo)
    gitlab_projects = list(args.gitlab_project)
    bitbucket_repos = list(args.bitbucket_repo)

    if args.github_token:
        for org in args.github_org:
            github_repos.extend(list_github_repos(args.github_token, org, args.github_host))
    elif args.github_repo or args.github_org:
        print("Error: GITHUB_TOKEN (or --github-token) required for GitHub.", file=sys.stderr)
        return 1

    if args.gitlab_token:
        for group in args.gitlab_group:
            gitlab_projects.extend(list_gitlab_projects(args.gitlab_token, group, args.gitlab_host))
    elif args.gitlab_project or args.gitlab_group:
        print("Error: GITLAB_TOKEN (or --gitlab-token) required for GitLab.", file=sys.stderr)
        return 1

    if args.bitbucket_workspace:
        for workspace in args.bitbucket_workspace:
            bitbucket_repos.extend(
                list_bitbucket_repos(args.bitbucket_token, workspace, args.bitbucket_username)
            )
    elif args.bitbucket_repo and not args.bitbucket_token and not args.bitbucket_username:
        print(
            "Warning: no BITBUCKET_TOKEN/--bitbucket-token set; querying Bitbucket anonymously.",
            file=sys.stderr,
        )

    if not github_repos and not gitlab_projects and not bitbucket_repos:
        print(
            "Provide at least one of --github-repo, --github-org, --gitlab-project, "
            "--gitlab-group, --bitbucket-repo, --bitbucket-workspace",
            file=sys.stderr,
        )
        return 1

    github_repos = sorted(set(github_repos))
    gitlab_projects = sorted(set(gitlab_projects))
    bitbucket_repos = sorted(set(bitbucket_repos))

    github_counts = (
        github_merged_counts(args.github_token, github_repos, args.github_host, since, until)
        if github_repos
        else {}
    )
    gitlab_counts = (
        gitlab_merged_counts(args.gitlab_token, gitlab_projects, args.gitlab_host, since, until)
        if gitlab_projects
        else {}
    )
    bitbucket_counts = (
        bitbucket_merged_counts(args.bitbucket_token, bitbucket_repos, args.bitbucket_username, since, until)
        if bitbucket_repos
        else {}
    )

    github_total = sum(github_counts.values())
    gitlab_total = sum(gitlab_counts.values())
    bitbucket_total = sum(bitbucket_counts.values())
    grand_total = github_total + gitlab_total + bitbucket_total

    result = {
        "github": {"repos": github_counts, "total": github_total},
        "gitlab": {"projects": gitlab_counts, "total": gitlab_total},
        "bitbucket": {"repos": bitbucket_counts, "total": bitbucket_total},
        "grand_total": grand_total,
        "since": args.since,
        "until": args.until,
    }

    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    print("\nMerged PR/MR counts\n" + "=" * 40)
    if github_counts:
        print("\nGitHub:")
        for repo, count in github_counts.items():
            print(f"  {repo}: {count}")
        print(f"  GitHub subtotal: {github_total}")

    if gitlab_counts:
        print("\nGitLab:")
        for project, count in gitlab_counts.items():
            print(f"  {project}: {count}")
        print(f"  GitLab subtotal: {gitlab_total}")

    if bitbucket_counts:
        print("\nBitbucket:")
        for repo, count in bitbucket_counts.items():
            print(f"  {repo}: {count}")
        print(f"  Bitbucket subtotal: {bitbucket_total}")

    print(f"\nGrand total: {grand_total}")
    return 0


# ---------------------------------------------------------------------------
# `export` subcommand — batch export for every org/group a token can see
# ---------------------------------------------------------------------------

def safe_filename(name: str) -> str:
    return re.sub(r"[^\w.\-]+", "_", name)


def parse_tokens_file(path: Path) -> dict[str, str]:
    tokens: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        tokens[key.strip()] = value.strip()
    return tokens


def list_github_users(token: str, host: str = "github.com") -> list[str]:
    api = github_api(token, host)
    users: set[str] = set()
    repos = paginate_github(
        f"{api}/user/repos?affiliation=owner,collaborator,organization_member&per_page=100",
        token,
    )
    for repo in repos:
        owner = repo.get("owner") or {}
        if owner.get("type") == "User":
            users.add(owner["login"])
    return sorted(users)


def write_org_csv(
    path: Path,
    platform: str,
    org: str,
    rows: list[dict[str, Any]],
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return sum(int(r["merged_count"]) for r in rows if r.get("merged_count"))


def export_github_org(
    token: str,
    org: str,
    token_name: str,
    output_dir: Path,
    host: str = "github.com",
) -> dict[str, Any]:
    filename = safe_filename(f"github_{org}.csv")
    out_path = output_dir / filename
    rows: list[dict[str, Any]] = []
    org_error = ""

    try:
        repos = list_github_repos(token, org, host)
    except Exception as exc:
        org_error = str(exc)
        rows.append(
            {"platform": "github", "org": org, "repo": "", "merged_count": 0, "error": org_error}
        )
        write_org_csv(out_path, "github", org, rows)
        return {
            "platform": "github",
            "org": org,
            "repos_total": 0,
            "merged_total": 0,
            "token_name": token_name,
            "error": org_error,
            "csv_path": str(out_path),
        }

    print(f"  GitHub {org}: {len(repos)} repos", flush=True)
    for idx, repo in enumerate(repos, start=1):
        error = ""
        count = 0
        try:
            count = count_github_merged(token, repo, host, None, None)
        except Exception as exc:
            error = str(exc)
        rows.append(
            {"platform": "github", "org": org, "repo": repo, "merged_count": count, "error": error}
        )
        if idx % 10 == 0 or idx == len(repos):
            print(f"    [{idx}/{len(repos)}] latest={repo} count={count}", flush=True)

    merged_total = write_org_csv(out_path, "github", org, rows)
    return {
        "platform": "github",
        "org": org,
        "repos_total": len(repos),
        "merged_total": merged_total,
        "token_name": token_name,
        "error": org_error,
        "csv_path": str(out_path),
    }


def export_gitlab_project(
    token: str,
    project: str,
    token_name: str,
    output_dir: Path,
    host: str = "gitlab.com",
) -> dict[str, Any]:
    """Export merged MR count for a single GitLab project (group/subgroup/project)."""
    project = project.strip().strip("/")
    namespace = "/".join(project.split("/")[:-1]) or project
    filename = safe_filename(f"gitlab_{project.replace('/', '_')}.csv")
    out_path = output_dir / filename
    error = ""
    count = 0
    try:
        count = count_gitlab_merged(token, project, host, None, None)
    except Exception as exc:
        error = str(exc)

    rows = [
        {"platform": "gitlab", "org": namespace, "repo": project, "merged_count": count, "error": error}
    ]
    merged_total = write_org_csv(out_path, "gitlab", namespace, rows)
    print(f"  GitLab project {project}: merged_count={count}", flush=True)
    return {
        "platform": "gitlab",
        "org": namespace,
        "project": project,
        "repos_total": 1,
        "merged_total": merged_total,
        "token_name": token_name,
        "error": error,
        "csv_path": str(out_path),
    }


def export_github_repos(
    token: str,
    repos: list[str],
    token_name: str,
    output_dir: Path,
    host: str = "github.com",
) -> dict[str, Any]:
    """Export merged PR counts for one or more specific GitHub repos (owner/repo)."""
    normalized: list[str] = []
    seen: set[str] = set()
    for repo in repos:
        r = repo.strip().strip("/")
        if not r or r in seen:
            continue
        if "/" not in r:
            raise ValueError(f"GitHub repo must be owner/repo (got {r!r})")
        seen.add(r)
        normalized.append(r)
    if not normalized:
        raise ValueError("At least one GitHub repo path is required")

    label = normalized[0].replace("/", "_") if len(normalized) == 1 else f"github_repos_{len(normalized)}"
    filename = safe_filename(f"{label}.csv")
    out_path = output_dir / filename
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    org_error = ""

    print(f"  GitHub repos: {len(normalized)} repo(s)", flush=True)
    for idx, repo in enumerate(normalized, start=1):
        owner = repo.split("/")[0]
        error = ""
        count = 0
        try:
            count = count_github_merged(token, repo, host, None, None)
        except Exception as exc:
            error = str(exc)
            org_error = org_error or error
        rows.append(
            {"platform": "github", "org": owner, "repo": repo, "merged_count": count, "error": error}
        )
        print(f"    [{idx}/{len(normalized)}] {repo} count={count}", flush=True)

    merged_total = write_org_csv(out_path, "github", normalized[0].split("/")[0], rows)
    return {
        "platform": "github",
        "repos": normalized,
        "repos_total": len(normalized),
        "merged_total": merged_total,
        "token_name": token_name,
        "error": org_error,
        "csv_path": str(out_path),
    }


def _export_bitbucket(
    token: str,
    repos: list[str],
    workspace_label: str,
    token_name: str,
    output_dir: Path,
    username: str = "",
) -> dict[str, Any]:
    """Shared merged-PR-count export for Bitbucket repos (workspace/repo)."""
    filename = safe_filename(f"{workspace_label}.csv")
    out_path = output_dir / filename
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    org_error = ""

    print(f"  Bitbucket repos: {len(repos)} repo(s)", flush=True)
    for idx, repo in enumerate(repos, start=1):
        workspace = repo.split("/")[0]
        error = ""
        count = 0
        try:
            count = count_bitbucket_merged(token, repo, username, None, None)
        except Exception as exc:
            error = str(exc)
            org_error = org_error or error
        rows.append(
            {"platform": "bitbucket", "org": workspace, "repo": repo, "merged_count": count, "error": error}
        )
        print(f"    [{idx}/{len(repos)}] {repo} count={count}", flush=True)

    merged_total = write_org_csv(out_path, "bitbucket", repos[0].split("/")[0], rows)
    return {
        "platform": "bitbucket",
        "repos": repos,
        "repos_total": len(repos),
        "merged_total": merged_total,
        "token_name": token_name,
        "error": org_error,
        "csv_path": str(out_path),
    }


def export_bitbucket_workspace(
    token: str,
    workspace: str,
    token_name: str,
    output_dir: Path,
    username: str = "",
) -> dict[str, Any]:
    """Export merged PR counts for every repo in a Bitbucket workspace."""
    repos = list_bitbucket_repos(token, workspace, username)
    return _export_bitbucket(token, repos, workspace, token_name, output_dir, username)


def export_bitbucket_repos(
    token: str,
    repos: list[str],
    token_name: str,
    output_dir: Path,
    username: str = "",
) -> dict[str, Any]:
    """Export merged PR counts for one or more specific Bitbucket repos."""
    normalized: list[str] = []
    seen: set[str] = set()
    for repo in repos:
        r = repo.strip().strip("/")
        if not r or r in seen:
            continue
        if "/" not in r:
            raise ValueError(f"Bitbucket repo must be workspace/repo (got {r!r})")
        seen.add(r)
        normalized.append(r)
    if not normalized:
        raise ValueError("At least one Bitbucket repo path is required")
    label = normalized[0].replace("/", "_") if len(normalized) == 1 else f"bitbucket_repos_{len(normalized)}"
    return _export_bitbucket(token, normalized, label, token_name, output_dir, username)


def export_gitlab_projects(
    token: str,
    projects: list[str],
    token_name: str,
    output_dir: Path,
    host: str = "gitlab.com",
) -> dict[str, Any]:
    """Export merged MR counts for one or more GitLab projects into a single CSV."""
    normalized = []
    seen: set[str] = set()
    for project in projects:
        path = project.strip().strip("/")
        if not path or path in seen:
            continue
        seen.add(path)
        normalized.append(path)
    if not normalized:
        raise ValueError("At least one GitLab project path is required")
    if len(normalized) == 1:
        return export_gitlab_project(token, normalized[0], token_name, output_dir, host)

    filename = safe_filename(f"gitlab_projects_{len(normalized)}.csv")
    out_path = output_dir / filename
    rows: list[dict[str, Any]] = []
    org_error = ""

    print(f"  GitLab projects batch: {len(normalized)} projects", flush=True)
    for idx, project in enumerate(normalized, start=1):
        namespace = "/".join(project.split("/")[:-1]) or project
        error = ""
        count = 0
        try:
            count = count_gitlab_merged(token, project, host, None, None)
        except Exception as exc:
            error = str(exc)
            if not org_error:
                org_error = error
        rows.append(
            {"platform": "gitlab", "org": namespace, "repo": project, "merged_count": count, "error": error}
        )
        if idx % 10 == 0 or idx == len(normalized):
            print(f"    [{idx}/{len(normalized)}] latest={project} count={count}", flush=True)

    merged_total = write_org_csv(out_path, "gitlab", "gitlab-projects", rows)
    return {
        "platform": "gitlab",
        "org": "gitlab-projects",
        "projects": normalized,
        "repos_total": len(normalized),
        "merged_total": merged_total,
        "token_name": token_name,
        "error": org_error,
        "csv_path": str(out_path),
    }


def export_gitlab_group(
    token: str,
    group: str,
    token_name: str,
    output_dir: Path,
    host: str = "gitlab.com",
) -> dict[str, Any]:
    filename = safe_filename(f"gitlab_{group.replace('/', '_')}.csv")
    out_path = output_dir / filename
    rows: list[dict[str, Any]] = []
    org_error = ""

    try:
        projects = list_gitlab_projects(token, group, host)
    except Exception as exc:
        org_error = str(exc)
        rows.append(
            {"platform": "gitlab", "org": group, "repo": "", "merged_count": 0, "error": org_error}
        )
        write_org_csv(out_path, "gitlab", group, rows)
        return {
            "platform": "gitlab",
            "org": group,
            "repos_total": 0,
            "merged_total": 0,
            "token_name": token_name,
            "error": org_error,
            "csv_path": str(out_path),
        }

    print(f"  GitLab {group}: {len(projects)} projects", flush=True)
    for idx, project in enumerate(projects, start=1):
        error = ""
        count = 0
        try:
            count = count_gitlab_merged(token, project, host, None, None)
        except Exception as exc:
            error = str(exc)
        rows.append(
            {"platform": "gitlab", "org": group, "repo": project, "merged_count": count, "error": error}
        )
        if idx % 10 == 0 or idx == len(projects):
            print(f"    [{idx}/{len(projects)}] latest={project} count={count}", flush=True)

    merged_total = write_org_csv(out_path, "gitlab", group, rows)
    return {
        "platform": "gitlab",
        "org": group,
        "repos_total": len(projects),
        "merged_total": merged_total,
        "token_name": token_name,
        "error": org_error,
        "csv_path": str(out_path),
    }


def _run_export(args: argparse.Namespace) -> int:
    tokens_path = Path(args.tokens_file)
    if not tokens_path.is_file():
        print(f"Tokens file not found: {tokens_path}", file=sys.stderr)
        return 1

    tokens = parse_tokens_file(tokens_path)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    github_token_name = "github-data-token"
    gitlab_token_name = "gitlab_token"
    github_token = tokens.get(github_token_name)
    gitlab_token = tokens.get(gitlab_token_name)

    if not github_token:
        print(f"Missing {github_token_name} in {tokens_path}", file=sys.stderr)
        return 1
    if not gitlab_token:
        print(f"Missing {gitlab_token_name} in {tokens_path}", file=sys.stderr)
        return 1

    started = datetime.now(timezone.utc).isoformat()
    summary_rows: list[dict[str, Any]] = []

    print("Discovering GitHub orgs...", flush=True)
    github_orgs = list_github_orgs(github_token, args.github_host)
    print(f"Found {len(github_orgs)} GitHub orgs: {', '.join(github_orgs)}", flush=True)

    for org in github_orgs:
        print(f"Exporting GitHub org: {org}", flush=True)
        summary_rows.append(
            export_github_org(github_token, org, github_token_name, output_dir, args.github_host)
        )

    print("Discovering GitLab groups...", flush=True)
    gitlab_groups = list_gitlab_top_level_groups(gitlab_token, args.gitlab_host)
    print(f"Found {len(gitlab_groups)} GitLab top-level groups: {', '.join(gitlab_groups)}", flush=True)

    for group in gitlab_groups:
        print(f"Exporting GitLab group: {group}", flush=True)
        summary_rows.append(
            export_gitlab_group(gitlab_token, group, gitlab_token_name, output_dir, args.gitlab_host)
        )

    summary_path = output_dir / "summary.csv"
    with summary_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        for row in summary_rows:
            writer.writerow({k: row.get(k, "") for k in SUMMARY_FIELDS})

    manifest = {
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "github_token": github_token_name,
        "gitlab_token": gitlab_token_name,
        "github_orgs": github_orgs,
        "gitlab_groups": gitlab_groups,
        "summary": summary_rows,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    grand_total = sum(int(r["merged_total"]) for r in summary_rows)
    print(f"\nDone. Wrote {len(summary_rows)} org CSVs to {output_dir}", flush=True)
    print(f"Grand total merged PRs/MRs: {grand_total}", flush=True)
    print(f"Summary: {summary_path}", flush=True)
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Count/export merged PRs/MRs on GitHub, GitLab, and Bitbucket")
    sub = parser.add_subparsers(dest="command", required=True)

    count_p = sub.add_parser("count", help="Count merged PRs/MRs for specific repos/orgs/groups/workspaces")
    count_p.add_argument(
        "--github-token",
        default=os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"),
    )
    count_p.add_argument(
        "--gitlab-token",
        default=os.environ.get("GITLAB_TOKEN") or os.environ.get("GLAB_TOKEN"),
    )
    count_p.add_argument(
        "--bitbucket-token",
        default=os.environ.get("BITBUCKET_TOKEN") or os.environ.get("BITBUCKET_APP_PASSWORD"),
    )
    count_p.add_argument(
        "--bitbucket-username",
        default=os.environ.get("BITBUCKET_USERNAME") or os.environ.get("ATLASSIAN_EMAIL") or os.environ.get("BITBUCKET_EMAIL", ""),
    )
    count_p.add_argument("--github-host", default=os.environ.get("GITHUB_HOST", "github.com"))
    count_p.add_argument("--gitlab-host", default=os.environ.get("GITLAB_HOST", "gitlab.com"))
    count_p.add_argument("--github-repo", action="append", default=[], help="owner/repo")
    count_p.add_argument("--github-org", action="append", default=[], help="GitHub org or user")
    count_p.add_argument("--gitlab-project", action="append", default=[], help="group/project")
    count_p.add_argument("--gitlab-group", action="append", default=[], help="GitLab group")
    count_p.add_argument("--bitbucket-repo", action="append", default=[], help="workspace/repo")
    count_p.add_argument("--bitbucket-workspace", action="append", default=[], help="Bitbucket workspace")
    count_p.add_argument("--since", help="Only count merges on/after YYYY-MM-DD")
    count_p.add_argument("--until", help="Only count merges on/before YYYY-MM-DD")
    count_p.add_argument("--json", action="store_true", help="Print JSON output")

    export_p = sub.add_parser("export", help="Batch-export merged PR/MR counts for every accessible org/group")
    export_p.add_argument("--tokens-file", default="tokens", help="Path to tokens file")
    export_p.add_argument("--output-dir", default="merged-pr-counts", help="Folder to write per-org CSV files")
    export_p.add_argument("--github-host", default="github.com")
    export_p.add_argument("--gitlab-host", default="gitlab.com")

    args = parser.parse_args()
    if args.command == "count":
        return _run_count(args)
    return _run_export(args)


if __name__ == "__main__":
    raise SystemExit(main())
