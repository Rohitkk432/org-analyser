"""Git-history metrics: non-merge commit count and unique contributors."""

from __future__ import annotations

from ..tools import have, run
from .base import Collector


class GitHistoryCollector(Collector):
    name = "git"

    def collect(self) -> dict[str, object]:
        if not have("git"):
            self.warn("git not installed")
            return {}

        commits = 0
        contributors: set[str] = set()
        any_git = False

        for repo in self.repos:
            if not (repo.path / ".git").exists():
                continue
            any_git = True
            commits += self._non_merge_commits(repo.path)
            contributors |= self._contributors(repo.path)

        if not any_git:
            self.warn("no git history found")
            return {}
        return {
            "non_merge_commits": commits,
            "unique_contributors": len(contributors),
        }

    def _non_merge_commits(self, path) -> int:
        res = run(["git", "log", "--no-merges", "--format=%s"], cwd=str(path))
        if not res.ok:
            return 0
        return sum(1 for _ in res.stdout.splitlines())

    def _contributors(self, path) -> set[str]:
        # Deduplicate across repos by lowercased email, falling back to name.
        res = run(
            ["git", "log", "--no-merges", "--format=%ae\t%an"], cwd=str(path)
        )
        if not res.ok:
            return set()
        people: set[str] = set()
        for line in res.stdout.splitlines():
            email, _, name = line.partition("\t")
            key = email.strip().lower() or name.strip().lower()
            if key:
                people.add(key)
        return people
