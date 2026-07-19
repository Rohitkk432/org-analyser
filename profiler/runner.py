"""Orchestrate collectors concurrently and assemble the final row."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from .collectors.base import Collector
from .collectors.codeanalysis import CodeAnalysisCollector
from .collectors.coverage import CoverageCollector
from .collectors.duplication import DuplicationCollector
from .collectors.llm_attribution import LlmAttributionCollector
from .collectors.git_history import GitHistoryCollector
from .collectors.infra import InfraCollector
from .collectors.loc import LocCollector
from .collectors.vcs_api import VcsApiCollector
from .discovery import Repo, discover_repos
from .models import ProfileResult
from .providers import GitProvider, RemoteRepo

logger = logging.getLogger(__name__)

# Vendor-provided columns (e.g. holdout_verification) are left empty for a human to
# fill; there's no reliable repo signal for them, so we don't guess.
_VENDOR_DEFAULTS: dict[str, object] = {}


def profile_dataset(
    root: str,
    *,
    use_github: bool = True,
    meta: dict[str, object] | None = None,
    provider: GitProvider | None = None,
    remote: RemoteRepo | None = None,
    originating_company: str | None = None,
    repo_name: str | None = None,
    max_workers: int = 6,
) -> ProfileResult:
    """Profile the dataset at ``root``.

    When ``provider`` + ``remote`` are given (remote mode), PR/fork stats come from the
    platform API; otherwise the gh CLI is used as a local fallback.
    """
    repos: list[Repo] = discover_repos(root)
    logger.info("discovered %d repo(s): %s", len(repos), [r.name for r in repos])

    result = ProfileResult()
    result.merge(dict(_VENDOR_DEFAULTS))
    result.merge({
        "num_repos": len(repos),
        "repo_name": repo_name
        or (repos[0].name if len(repos) == 1 else f"{root.rstrip('/').split('/')[-1]} bundle"),
    })
    if originating_company:
        result.merge({"originating_company": originating_company})

    collectors: list[Collector] = [
        LocCollector(repos),
        DuplicationCollector(repos),
        GitHistoryCollector(repos),
        InfraCollector(repos),
        CoverageCollector(repos),
        CodeAnalysisCollector(repos),
        LlmAttributionCollector(repos),
        VcsApiCollector(repos, enabled=use_github, provider=provider, remote=remote),
    ]

    # Collectors are independent; scc/jscpd/API calls dominate wall-time, so run in parallel.
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_safe_collect, c): c for c in collectors}
        for fut in as_completed(futures):
            collector = futures[fut]
            values, warnings = fut.result()
            result.merge(values)
            result.warnings.extend(warnings)
            logger.info("%s done (%d fields)", collector.name, len(values))

    # Public LOC: if the platform tells us the repo is public, its code is openly
    # crawlable, so all the logical LOC is "available in public training corpora";
    # if private, none is. Left blank when visibility is unknown (local mode).
    if remote is not None and remote.is_private is not None:
        logical = result.values.get("logical_loc")
        if isinstance(logical, int):
            result.merge({"public_loc": 0 if remote.is_private else logical})

    # User-supplied vendor metadata wins over defaults.
    if meta:
        result.merge({k: v for k, v in meta.items() if v is not None})

    return result


def _safe_collect(collector: Collector) -> tuple[dict[str, object], list[str]]:
    try:
        values = collector.collect()
    except Exception as exc:  # never let one collector sink the run
        logger.exception("collector %s crashed", collector.name)
        return {}, [f"[{collector.name}] crashed: {exc}"]
    return values, collector.warnings
