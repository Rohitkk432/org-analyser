"""Fetch repos from a hosting platform into a local working dir for profiling.

Clones (or pulls, if already present) into ``workdir`` so repeated runs reuse history.
Full clones are used deliberately — commit counts, contributors and PR review stats need
the entire history, not a shallow copy.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .providers import GitProvider, RemoteRepo
from .tools import run

logger = logging.getLogger(__name__)

DEFAULT_WORKDIR = Path.home() / ".cache" / "codebase_profiler" / "clones"

# Long-lived integration branches whose tip is a fair snapshot of the codebase. We never
# measure short-lived feature/topic branches; we pick the most recently active of these so
# an abandoned default branch (e.g. a `master` left behind years ago) can't skew metrics.
_LONG_LIVED = {
    "main", "master", "develop", "development", "dev", "devel",
    "staging", "stage", "trunk", "production", "prod", "default",
}
_LONG_LIVED_PREFIXES = ("release/", "release-", "releases/", "stable/")


def ensure_clone(repo: RemoteRepo, provider: GitProvider, workdir: Path) -> Path | None:
    """Clone ``repo`` into ``workdir`` (or git-pull if already there). Returns the path.

    After fetching, checks out the most recently active long-lived branch so metrics never
    reflect a stale default branch.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    dest = workdir / repo.platform / repo.owner.replace("/", "__") / repo.name
    auth_url = provider.auth_clone_url(repo)

    if (dest / ".git").exists():
        logger.info("fetching %s", repo.full_name)
        res = run(["git", "-C", str(dest), "fetch", "--prune", "origin"], timeout=900)
        if not res.ok:
            logger.warning("fetch failed for %s: %s",
                           repo.full_name, _redact(res.stderr, auth_url)[:200])
    else:
        logger.info("cloning %s", repo.full_name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        res = run(["git", "clone", auth_url, str(dest)], timeout=1800)
        if not res.ok:
            # Never leak the token in logs/output.
            logger.error("clone failed for %s: %s", repo.full_name, _redact(res.stderr, auth_url))
            return None

    _checkout_active_branch(dest, repo.full_name)
    return dest


def _checkout_active_branch(dest: Path, label: str) -> None:
    """Check out the most recently committed long-lived branch (fall back to default)."""
    branch = _select_branch(dest)
    if not branch:
        return
    res = run(["git", "-C", str(dest), "checkout", "-B", branch, f"origin/{branch}"])
    if res.ok:
        logger.info("%s: measuring branch '%s'", label, branch)
    else:
        logger.warning("%s: could not check out '%s': %s",
                       label, branch, res.stderr.strip()[:200])


def _select_branch(dest: Path) -> str | None:
    """Pick the most recently active long-lived branch among the origin refs.

    Returns the short branch name (e.g. ``develop``), or None to keep the current HEAD
    (no remote branch matched the long-lived patterns).
    """
    res = run([
        "git", "-C", str(dest), "for-each-ref", "--sort=-committerdate",
        "--format=%(refname:short)", "refs/remotes/origin",
    ])
    if not res.ok:
        return None
    for ref in res.stdout.splitlines():
        ref = ref.strip()
        if not ref or ref.endswith("/HEAD"):
            continue
        name = ref.split("/", 1)[1] if "/" in ref else ref  # strip the 'origin/' prefix
        if _is_long_lived(name):
            return name
    return None  # no long-lived branch found; leave the default checkout alone


def _is_long_lived(name: str) -> bool:
    lname = name.lower()
    return lname in _LONG_LIVED or lname.startswith(_LONG_LIVED_PREFIXES)


def _redact(text: str, *secrets: str) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "<redacted>")
    return text
