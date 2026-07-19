"""PR/MR review stats and fork status, from a hosting-platform API.

Two paths:
- **Provider path** (remote mode): a GitHub/GitLab/Bitbucket provider + resolved RemoteRepo are
  supplied, so we query the platform API directly with the user's token.
- **gh fallback** (local mode): no provider, but the local checkout has a GitHub remote
  and the ``gh`` CLI is authenticated.
"""

from __future__ import annotations

from ..providers import GitProvider, ProviderError, RemoteRepo
from ..tools import have, run_json
from .base import Collector

_PR_QUERY = """
query($owner:String!, $name:String!, $cursor:String) {
  repository(owner:$owner, name:$name) {
    pullRequests(states:MERGED, first:100, after:$cursor) {
      pageInfo { hasNextPage endCursor }
      nodes { reviewDecision reviews { totalCount } }
    }
  }
}
"""


class VcsApiCollector(Collector):
    name = "vcs"

    def __init__(
        self,
        repos,
        *,
        enabled: bool = True,
        provider: GitProvider | None = None,
        remote: RemoteRepo | None = None,
    ) -> None:
        super().__init__(repos)
        self.enabled = enabled
        self.provider = provider
        self.remote = remote

    def collect(self) -> dict[str, object]:
        if not self.enabled:
            return {}
        if self.provider is not None and self.remote is not None:
            return self._via_provider()
        return self._via_gh()

    # --- provider path (GitHub, GitLab, or Bitbucket) ------------------------
    def _via_provider(self) -> dict[str, object]:
        out: dict[str, object] = {}
        try:
            total, reviewed = self.provider.pr_stats(self.remote)
            out["total_prs"] = total
            out["reviewed_prs"] = reviewed
        except ProviderError as exc:
            self.warn(f"PR/MR stats failed for {self.remote.full_name}: {exc}")
        try:
            out["fork_pct"] = 1.0 if self.provider.is_fork(self.remote) else 0.0
        except ProviderError as exc:
            self.warn(f"fork lookup failed for {self.remote.full_name}: {exc}")
        return out

    # --- local fallback via the gh CLI ---------------------------------------
    def _via_gh(self) -> dict[str, object]:
        if not have("gh"):
            self.warn("no provider and gh CLI not installed; PR/fork metrics skipped")
            return {}

        total_prs = reviewed_prs = fork_count = repos_with_remote = 0
        for repo in self.repos:
            slug = self._gh_slug(repo.path)
            if slug is None:
                continue
            repos_with_remote += 1
            owner, name = slug
            if self._gh_is_fork(repo.path):
                fork_count += 1
            t, r = self._gh_pr_counts(owner, name, repo.path)
            total_prs += t
            reviewed_prs += r

        if repos_with_remote == 0:
            self.warn("no GitHub remotes resolved; PR/fork metrics skipped")
            return {}
        return {
            "total_prs": total_prs,
            "reviewed_prs": reviewed_prs,
            "fork_pct": round(fork_count / repos_with_remote, 4),
        }

    def _gh_slug(self, path):
        data = run_json(["gh", "repo", "view", "--json", "nameWithOwner"], cwd=str(path))
        if not data or "nameWithOwner" not in data:
            return None
        owner, _, name = data["nameWithOwner"].partition("/")
        return (owner, name) if name else None

    def _gh_is_fork(self, path) -> bool:
        data = run_json(["gh", "repo", "view", "--json", "isFork"], cwd=str(path))
        return bool(data and data.get("isFork"))

    def _gh_pr_counts(self, owner, name, path) -> tuple[int, int]:
        total = reviewed = 0
        cursor = None
        while True:
            cmd = [
                "gh", "api", "graphql",
                "-f", f"query={_PR_QUERY}",
                "-F", f"owner={owner}",
                "-F", f"name={name}",
            ]
            if cursor:
                cmd += ["-F", f"cursor={cursor}"]
            data = run_json(cmd, cwd=str(path))
            if not data:
                self.warn(f"gh PR query failed for {owner}/{name}")
                break
            prs = data["data"]["repository"]["pullRequests"]
            for node in prs["nodes"]:
                total += 1
                decision = node.get("reviewDecision")
                has_reviews = (node.get("reviews") or {}).get("totalCount", 0) > 0
                if decision in ("APPROVED", "CHANGES_REQUESTED") or has_reviews:
                    reviewed += 1
            if not prs["pageInfo"]["hasNextPage"]:
                break
            cursor = prs["pageInfo"]["endCursor"]
        return total, reviewed
