#!/usr/bin/env python3
"""
Bulk GitHub repo evaluator runner with:
- org discovery
- repo inventory across orgs
- legacy/modern classification
- parallel evaluator execution
- CSV + JSON output

Usage examples:
    python bulk_repo_evaluator_parallel.py --dry-run
    python bulk_repo_evaluator_parallel.py --run --workers 6
    python bulk_repo_evaluator_parallel.py --run --org my-org --org another-org
    python bulk_repo_evaluator_parallel.py --run --classification-overrides classification_overrides.json

Env:
    export GITHUB_TOKEN=ghp_xxx

Dependencies:
    pip install requests
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple

import requests

API_BASE = "https://api.github.com"
API_VERSION = "2022-11-28"


@dataclass
class RepoPlan:
    repo: str
    owner: str
    name: str
    private: bool
    archived: bool
    default_branch: Optional[str]
    classification: str
    classification_reason: str
    classification_markers: str
    modern_score: int
    legacy_score: int
    command: str
    exit_code: Optional[int] = None
    status: str = "planned"
    duration_seconds: Optional[float] = None
    error: Optional[str] = None


class GitHubClient:
    def __init__(self, token: str, sleep_on_rate_limit: bool = True) -> None:
        self.token = token
        self.sleep_on_rate_limit = sleep_on_rate_limit
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": "bulk-repo-evaluator",
            }
        )

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        resp = self.session.request(method, url, timeout=60, **kwargs)

        if resp.status_code == 403:
            remaining = resp.headers.get("X-RateLimit-Remaining")
            reset = resp.headers.get("X-RateLimit-Reset")
            if remaining == "0" and reset and self.sleep_on_rate_limit:
                wait_for = max(int(reset) - int(time.time()) + 2, 2)
                print(f"[rate-limit] sleeping {wait_for}s", file=sys.stderr)
                time.sleep(wait_for)
                resp = self.session.request(method, url, timeout=60, **kwargs)

        return resp

    def _get_paginated(self, path: str, params: Optional[dict] = None) -> List[dict]:
        out: List[dict] = []
        page = 1
        while True:
            merged = {"per_page": 100, "page": page}
            if params:
                merged.update(params)
            resp = self._request("GET", f"{API_BASE}{path}", params=merged)
            if resp.status_code >= 400:
                raise RuntimeError(f"GitHub API error {resp.status_code} for {path}: {resp.text}")
            data = resp.json()
            if not isinstance(data, list):
                raise RuntimeError(f"Expected list response for {path}, got {type(data).__name__}")
            out.extend(data)
            if len(data) < 100:
                break
            page += 1
        return out

    def get_authenticated_user(self) -> dict:
        resp = self._request("GET", f"{API_BASE}/user")
        if resp.status_code >= 400:
            raise RuntimeError(f"Failed to fetch authenticated user: {resp.text}")
        return resp.json()

    def list_org_memberships(self, state: str = "active") -> List[dict]:
        return self._get_paginated("/user/memberships/orgs", params={"state": state})

    def list_org_repos(self, org: str, repo_type: str = "all") -> List[dict]:
        return self._get_paginated(f"/orgs/{org}/repos", params={"type": repo_type})

    def list_user_repos(self, affiliation: str = "owner,collaborator,organization_member") -> List[dict]:
        return self._get_paginated("/user/repos", params={"affiliation": affiliation})

    def get_repo_root_contents(self, owner: str, repo: str, branch: Optional[str] = None) -> List[dict]:
        params = {}
        if branch:
            params["ref"] = branch
        resp = self._request("GET", f"{API_BASE}/repos/{owner}/{repo}/contents", params=params)
        if resp.status_code == 404:
            return []
        if resp.status_code >= 400:
            raise RuntimeError(f"Failed reading {owner}/{repo} root: {resp.status_code} {resp.text}")
        data = resp.json()
        return data if isinstance(data, list) else []

    def get_file_content(self, owner: str, repo: str, path: str, branch: Optional[str] = None) -> Optional[str]:
        params = {}
        if branch:
            params["ref"] = branch
        resp = self._request("GET", f"{API_BASE}/repos/{owner}/{repo}/contents/{path}", params=params)
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            return None
        data = resp.json()
        if not isinstance(data, dict):
            return None
        download_url = data.get("download_url")
        if not download_url:
            return None
        raw = self._request("GET", download_url)
        if raw.status_code >= 400:
            return None
        return raw.text


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run repo evaluators across all accessible org repos.")
    p.add_argument("--token", help="GitHub token; falls back to GITHUB_TOKEN / GH_TOKEN")
    p.add_argument("--include-user-repos", action="store_true", help="Include personal/collaborator repos too")
    p.add_argument("--org", action="append", help="Only include these orgs")
    p.add_argument("--exclude-org", action="append", default=[], help="Exclude these orgs")
    p.add_argument("--repo", action="append", help="Only include these full repo names owner/name")
    p.add_argument("--exclude-repo", action="append", default=[], help="Exclude these full repo names owner/name")
    p.add_argument("--visibility", choices=["all", "public", "private"], default="all")
    p.add_argument("--classification-overrides", help="JSON file mapping owner/repo => legacy|modern")
    p.add_argument("--run", action="store_true", help="Actually execute commands")
    p.add_argument("--dry-run", action="store_true", help="Only print plan")
    p.add_argument("--workers", type=int, default=4, help="Parallel workers for evaluator execution")
    p.add_argument("--fail-fast", action="store_true", help="Stop early on first failure")
    p.add_argument("--json-out", default="repos_inventory.json", help="Output JSON path")
    p.add_argument("--csv-out", default="repos_inventory.csv", help="Output CSV path")
    p.add_argument(
        "--legacy-cmd",
        default="python repo_evaluator_legacy.py {repo} --token {token}",
        help="Command template for legacy repos",
    )
    p.add_argument(
        "--modern-cmd",
        default="python repo_evaluator.py {repo} --token {token}",
        help="Command template for modern repos",
    )
    return p.parse_args()


def load_overrides(path: Optional[str]) -> Dict[str, str]:
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    out: Dict[str, str] = {}
    for repo, val in data.items():
        normalized = str(val).strip().lower()
        if normalized not in {"legacy", "modern"}:
            raise ValueError(f"Invalid override for {repo}: {val}")
        out[repo.strip()] = normalized
    return out


def repo_matches_visibility(repo: dict, visibility: str) -> bool:
    if visibility == "all":
        return True
    is_private = bool(repo.get("private", False))
    if visibility == "private":
        return is_private
    return not is_private


def classify_repo(client: GitHubClient, repo: dict, overrides: Dict[str, str]) -> Tuple[str, dict]:
    full_name = repo["full_name"]
    owner = repo["owner"]["login"]
    name = repo["name"]
    default_branch = repo.get("default_branch")

    if full_name in overrides:
        return overrides[full_name], {
            "reason": f"manual override: {overrides[full_name]}",
            "markers": ["override"],
            "scores": {"modern": 0, "legacy": 0},
        }

    contents = client.get_repo_root_contents(owner, name, default_branch)
    root_names = {str(item.get("name", "")) for item in contents}
    lower_names = {x.lower() for x in root_names}

    modern_score = 0
    legacy_score = 0
    markers: List[str] = []

    modern_markers = {
        "pyproject.toml": 3,
        "poetry.lock": 2,
        "uv.lock": 2,
        "pnpm-workspace.yaml": 3,
        "pnpm-lock.yaml": 2,
        "turbo.json": 3,
        "nx.json": 3,
        "docker-compose.yml": 1,
        "docker-compose.yaml": 1,
        "compose.yaml": 1,
        "tsconfig.json": 1,
        ".github": 1,
    }
    legacy_markers = {
        "setup.py": 3,
        "setup.cfg": 2,
        "requirements.txt": 2,
        "pipfile": 1,
        "gulpfile.js": 3,
        "gruntfile.js": 3,
        "bower.json": 3,
        ".travis.yml": 2,
    }

    for marker, score in modern_markers.items():
        if marker in lower_names:
            modern_score += score
            markers.append(f"modern:{marker}")

    for marker, score in legacy_markers.items():
        if marker in lower_names:
            legacy_score += score
            markers.append(f"legacy:{marker}")

    for item in contents:
        item_name = str(item.get("name", "")).lower()
        item_type = item.get("type")
        if item_type == "dir" and item_name in {"k8s", "helm", ".github", ".devcontainer"}:
            modern_score += 2
            markers.append(f"modern-dir:{item_name}")
        if item_type == "dir" and item_name in {"vendor", "third_party"}:
            legacy_score += 1
            markers.append(f"legacy-dir:{item_name}")

    package_json = client.get_file_content(owner, name, "package.json", default_branch)
    if package_json:
        try:
            pkg = json.loads(package_json)
            deps = {}
            deps.update(pkg.get("dependencies", {}))
            deps.update(pkg.get("devDependencies", {}))
            if any(x in deps for x in ["next", "vite", "typescript"]):
                modern_score += 2
                markers.append("modern-package:next/vite/typescript")
            if "react-scripts" in deps:
                legacy_score += 1
                markers.append("legacy-package:react-scripts")
        except Exception:
            pass

    if modern_score == 0 and legacy_score == 0:
        if repo.get("archived"):
            return "legacy", {
                "reason": "archived repo defaulted to legacy",
                "markers": ["archived-default"],
                "scores": {"modern": 0, "legacy": 0},
            }
        return "modern", {
            "reason": "no strong markers found; defaulted to modern",
            "markers": ["default-modern"],
            "scores": {"modern": 0, "legacy": 0},
        }

    kind = "modern" if modern_score >= legacy_score else "legacy"
    return kind, {
        "reason": "auto-classified",
        "markers": markers,
        "scores": {"modern": modern_score, "legacy": legacy_score},
    }


def build_command(template: str, repo_full_name: str, token: str) -> str:
    return template.format(repo=repo_full_name, token=token)


def execute_plan(plan: RepoPlan) -> RepoPlan:
    started = time.time()
    try:
        completed = subprocess.run(plan.command, shell=True)
        plan.exit_code = completed.returncode
        plan.status = "success" if completed.returncode == 0 else "failed"
    except Exception as e:
        plan.exit_code = -1
        plan.status = "failed"
        plan.error = str(e)
    finally:
        plan.duration_seconds = round(time.time() - started, 2)
    return plan


def write_json(plans: List[RepoPlan], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump([asdict(p) for p in plans], f, indent=2)


def write_csv(plans: List[RepoPlan], path: str) -> None:
    if not plans:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "repo", "owner", "name", "private", "archived", "default_branch",
                "classification", "classification_reason", "classification_markers",
                "modern_score", "legacy_score", "command", "exit_code",
                "status", "duration_seconds", "error"
            ])
        return

    fieldnames = list(asdict(plans[0]).keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for p in plans:
            writer.writerow(asdict(p))


def main() -> int:
    args = parse_args()
    token = args.token or os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if not token:
        print("ERROR: Missing token. Set --token or GITHUB_TOKEN / GH_TOKEN", file=sys.stderr)
        return 1

    overrides = load_overrides(args.classification_overrides)
    client = GitHubClient(token)

    me = client.get_authenticated_user()
    print(f"[auth] logged in as {me['login']}")

    memberships = client.list_org_memberships(state="active")
    orgs = sorted({m["organization"]["login"] for m in memberships})

    if args.org:
        wanted = set(args.org)
        orgs = [o for o in orgs if o in wanted]

    if args.exclude_org:
        excluded = set(args.exclude_org)
        orgs = [o for o in orgs if o not in excluded]

    print(f"[orgs] total selected: {len(orgs)}")
    for org in orgs:
        print(f"  - {org}")

    repos: Dict[str, dict] = {}

    for org in orgs:
        org_repos = client.list_org_repos(org, repo_type="all")
        for repo in org_repos:
            if repo_matches_visibility(repo, args.visibility):
                repos[repo["full_name"]] = repo

    if args.include_user_repos:
        user_repos = client.list_user_repos()
        for repo in user_repos:
            if repo_matches_visibility(repo, args.visibility):
                repos[repo["full_name"]] = repo

    if args.repo:
        wanted = set(args.repo)
        repos = {k: v for k, v in repos.items() if k in wanted}

    if args.exclude_repo:
        excluded = set(args.exclude_repo)
        repos = {k: v for k, v in repos.items() if k not in excluded}

    selected_repos = [repos[k] for k in sorted(repos.keys())]
    print(f"[repos] total unique repos selected: {len(selected_repos)}")

    plans: List[RepoPlan] = []

    for repo in selected_repos:
        full_name = repo["full_name"]
        owner = repo["owner"]["login"]
        name = repo["name"]

        try:
            classification, details = classify_repo(client, repo, overrides)
        except Exception as e:
            classification = "modern"
            details = {
                "reason": f"classification failed, defaulted to modern: {e}",
                "markers": ["classification-error"],
                "scores": {"modern": 0, "legacy": 0},
            }

        cmd_template = args.legacy_cmd if classification == "legacy" else args.modern_cmd
        command = build_command(cmd_template, full_name, token)

        plan = RepoPlan(
            repo=full_name,
            owner=owner,
            name=name,
            private=bool(repo.get("private", False)),
            archived=bool(repo.get("archived", False)),
            default_branch=repo.get("default_branch"),
            classification=classification,
            classification_reason=details.get("reason", ""),
            classification_markers=" | ".join(details.get("markers", [])),
            modern_score=int(details.get("scores", {}).get("modern", 0)),
            legacy_score=int(details.get("scores", {}).get("legacy", 0)),
            command=command,
        )
        plans.append(plan)

        print(f"[plan] {full_name} -> {classification}")

    if args.dry_run or not args.run:
        write_json(plans, args.json_out)
        write_csv(plans, args.csv_out)
        print(f"[done] dry-run only")
        print(f"[done] wrote {args.json_out}")
        print(f"[done] wrote {args.csv_out}")
        return 0

    failures = 0
    completed_plans: List[RepoPlan] = []

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        future_map = {executor.submit(execute_plan, plan): plan for plan in plans}

        for future in as_completed(future_map):
            plan = future_map[future]
            try:
                result = future.result()
                completed_plans.append(result)
                print(
                    f"[exec] {result.repo} -> {result.status} "
                    f"(exit={result.exit_code}, {result.duration_seconds}s)"
                )
                if result.status != "success":
                    failures += 1
                    if args.fail_fast:
                        print("[fail-fast] stopping early", file=sys.stderr)
                        break
            except Exception as e:
                plan.status = "failed"
                plan.error = str(e)
                plan.exit_code = -1
                completed_plans.append(plan)
                failures += 1
                print(f"[exec] {plan.repo} -> failed ({e})", file=sys.stderr)
                if args.fail_fast:
                    break

    completed_by_repo = {p.repo: p for p in completed_plans}
    final_plans = [completed_by_repo.get(p.repo, p) for p in plans]

    write_json(final_plans, args.json_out)
    write_csv(final_plans, args.csv_out)

    print(f"[done] wrote {args.json_out}")
    print(f"[done] wrote {args.csv_out}")

    if failures > 0:
        print(f"[done] failures: {failures}", file=sys.stderr)
        return 2

    print("[done] all evaluator runs completed successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())