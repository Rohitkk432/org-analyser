"""Command-line entrypoint: profile a local path, a remote repo, or a whole org/group."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from .models import COLUMNS
from .providers import (
    GitProvider,
    ProviderError,
    RemoteRepo,
    make_provider,
    parse_org_target,
    parse_repo_target,
)
from .remote import DEFAULT_WORKDIR, ensure_clone
from .runner import profile_dataset
from .tools import have, run
from .writer import append_row, count_data_rows

def _default_template() -> Path:
    """Prefer the template bundled with the project; fall back to ~/Downloads."""
    bundled = Path(__file__).resolve().parent.parent / "codebase_sheet.xlsx"
    if bundled.exists():
        return bundled
    return Path.home() / "Downloads" / "codebase_sheet.xlsx"


DEFAULT_TEMPLATE = _default_template()


@dataclass
class Job:
    """One repository to profile and the context needed to fill its row.

    For remote jobs ``path`` starts as ``None`` and the repo is cloned lazily in the main
    loop (so progress is shown repo-by-repo); local jobs carry the path directly.
    """

    path: Path | None = None
    provider: GitProvider | None = None
    remote: RemoteRepo | None = None
    originating_company: str | None = None
    repo_name: str | None = None
    workdir: Path | None = None


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    meta = json.loads(Path(args.meta).read_text()) if args.meta else None
    out = (Path(args.out) if args.out else Path.cwd() / "codebase_sheet.filled.xlsx").resolve()
    rows_before = count_data_rows(out)

    try:
        jobs = _resolve_jobs(args)
    except (ProviderError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not jobs:
        print("error: nothing to profile", file=sys.stderr)
        return 2

    action = "appending to" if rows_before else "creating"
    print(f"Profiling {len(jobs)} repo(s); {action} {out}"
          + (f" (already has {rows_before} row(s))" if rows_before else ""))
    done = 0
    for i, job in enumerate(jobs, 1):
        label = job.repo_name or (job.path.name if job.path else "?")
        print(f"\n[{i}/{len(jobs)}] {label}", flush=True)

        # Remote jobs are cloned here, one at a time, so progress is visible per repo.
        if job.path is None and job.remote is not None:
            print("  ↪ cloning/fetching…", flush=True)
            job.path = ensure_clone(job.remote, job.provider, job.workdir)
            if job.path is None:
                print("  ! clone failed — skipping", file=sys.stderr, flush=True)
                continue

        result = profile_dataset(
            str(job.path),
            use_github=not args.no_github,
            meta=meta,
            provider=job.provider,
            remote=job.remote,
            originating_company=job.originating_company,
            repo_name=job.repo_name,
        )
        saved = append_row(result, template=args.template, out=out)
        _summarize(result, saved, verbose=args.verbose)
        done += 1
        if args.print:
            named = {c.header or c.key: result.values.get(c.key, "") for c in COLUMNS}
            print(json.dumps(named, indent=2, ensure_ascii=False))

    total_rows = count_data_rows(out)
    print("\n" + "=" * 60)
    print(f"✓ Done. Added {done} row(s) this run; the sheet now has {total_rows} total.")
    print(f"📄 Output file: {out}")
    print("=" * 60)
    return 0


def _parse_args(argv):
    p = argparse.ArgumentParser(
        prog="codebase-profiler",
        description="Auto-fill the vendor codebase intake sheet from a local path, "
                    "a remote repo, or an entire GitHub/GitLab org / Bitbucket workspace.",
    )
    target = p.add_mutually_exclusive_group(required=True)
    target.add_argument("path", nargs="?", help="Local path to a repo or bundle directory")
    target.add_argument("--repo", help="Remote repo: owner/name or full URL")
    target.add_argument("--organization", "--org", dest="organization",
                        help="Profile every repo under a GitHub org / GitLab group / "
                             "Bitbucket workspace or project (name or full URL)")

    p.add_argument("--platform", choices=["github", "gitlab", "bitbucket"], default=None,
                   help="Hosting platform for --repo/--organization (default: github, "
                        "or inferred from a --repo URL)")
    p.add_argument("--host", default=None,
                   help="Custom host for self-managed GitHub Enterprise / GitLab")
    p.add_argument("--token", default=None,
                   help="API token (else GITHUB_TOKEN / GITLAB_TOKEN / GIT_TOKEN env)")
    p.add_argument("--workdir", default=str(DEFAULT_WORKDIR),
                   help=f"Where to clone/pull remote repos (default: {DEFAULT_WORKDIR})")
    p.add_argument("--limit", type=int, default=None,
                   help="Org mode: profile at most N repos (handy for testing/partial runs)")

    p.add_argument("--template", default=str(DEFAULT_TEMPLATE),
                   help="Source xlsx with Sheet1/Sheet2 (default: the bundled "
                        "codebase_sheet.xlsx)")
    p.add_argument("--out", default=None,
                   help="Output xlsx (default: ./codebase_sheet.filled.xlsx); "
                        "created if absent, appended if present")
    p.add_argument("--no-github", action="store_true", help="Skip all PR/MR & fork API calls")
    p.add_argument("--meta", default=None, help="JSON file of vendor fields")
    p.add_argument("--print", action="store_true", help="Print each row as JSON")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def _resolve_token(args, platform: str) -> str | None:
    if args.token:
        return args.token
    env_names = {
        "github": ["GITHUB_TOKEN", "GH_TOKEN", "GIT_TOKEN"],
        "gitlab": ["GITLAB_TOKEN", "GIT_TOKEN"],
        "bitbucket": ["BITBUCKET_TOKEN", "BITBUCKET_APP_PASSWORD", "GIT_TOKEN"],
    }[platform]
    for name in env_names:
        if os.environ.get(name):
            return os.environ[name]
    # Convenience: reuse an existing `gh` CLI login for github.com when nothing else is set.
    if platform == "github" and not args.host and have("gh"):
        res = run(["gh", "auth", "token"])
        if res.ok and res.stdout.strip():
            logging.getLogger(__name__).info("using token from `gh auth` login")
            return res.stdout.strip()
    return None


def _resolve_jobs(args) -> list[Job]:
    # Local mode: profile the path as-is, no provider.
    if args.path:
        return [Job(path=Path(args.path).resolve())]

    workdir = Path(args.workdir)

    # Remote jobs defer cloning to the main loop so progress is shown repo-by-repo.
    if args.repo:
        inferred, owner, name = parse_repo_target(args.repo)
        platform = args.platform or inferred or "github"
        token = _resolve_token(args, platform)
        provider = make_provider(platform, token=token, host=args.host)
        repo = provider.get_repo(owner, name)
        return [Job(provider=provider, remote=repo, workdir=workdir,
                    originating_company=repo.owner, repo_name=repo.name)]

    # Organization / group mode. Accept a bare name or a full URL (platform inferred).
    inferred, org, inferred_host = parse_org_target(args.organization)
    platform = args.platform or inferred or "github"
    host = args.host or inferred_host
    token = _resolve_token(args, platform)
    provider = make_provider(platform, token=token, host=host)
    repos = provider.list_repos(org)
    print(f"Found {len(repos)} repo(s) under '{org}' on {platform}")
    if args.limit:
        repos = repos[: args.limit]
        print(f"Limiting to first {len(repos)} repo(s)")

    return [Job(provider=provider, remote=repo, workdir=workdir,
                originating_company=org, repo_name=repo.name)
            for repo in repos]


def _summarize(result, saved: Path, *, verbose: bool) -> None:
    filled = sum(1 for c in COLUMNS if result.values.get(c.key) not in (None, ""))
    print(f"  ✓ {filled}/{len(COLUMNS)} columns populated -> {saved.name}")
    if verbose:
        for c in COLUMNS:
            val = result.values.get(c.key, "")
            if val not in (None, ""):
                print(f"    {(c.header or '(row marker)'):<42} {val}")
    if result.warnings:
        for w in result.warnings:
            print(f"    - {w}")


if __name__ == "__main__":
    sys.exit(main())
