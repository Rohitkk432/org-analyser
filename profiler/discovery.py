"""Discover the git repositories that make up a dataset.

A dataset is one or more repos. Pointing at a single repo yields that repo; pointing
at a directory that contains several repos (a "bundle") yields all of them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Repo:
    path: Path

    @property
    def name(self) -> str:
        return self.path.name


def discover_repos(root: str | Path) -> list[Repo]:
    """Return every git repo at or beneath ``root`` (a repo == a directory with .git)."""
    root = Path(root).resolve()
    if not root.is_dir():
        raise NotADirectoryError(root)

    # The root itself is a repo.
    if (root / ".git").exists():
        return [Repo(root)]

    repos: list[Repo] = []
    skip = {"node_modules", ".venv", "venv", "vendor", "dist", "build", "__pycache__"}
    for dirpath, dirnames, _ in os.walk(root):
        if ".git" in os.listdir(dirpath):
            repos.append(Repo(Path(dirpath)))
            dirnames[:] = []  # don't descend into a repo's submodules
            continue
        dirnames[:] = [d for d in dirnames if d not in skip and not d.startswith(".")]

    # Fallback: treat the directory as a single (non-git) source tree.
    return repos or [Repo(root)]
