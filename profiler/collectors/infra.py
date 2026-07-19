"""Tiered classification of operational maturity from files & commit messages.

Covers: CI Checks, Deployment Infrastructure, Monitoring & Observability, Test Suite
Presence, Containerized, README Quality, Issue Tracker. Each output uses the exact
enum vocabulary from the data dictionary.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..tools import have, run
from .base import Collector

CI_MARKERS = (
    ".github/workflows", ".circleci", ".travis.yml", "jenkinsfile",
    ".gitlab-ci.yml", "azure-pipelines.yml", ".drone.yml", "bitbucket-pipelines.yml",
)
CONTAINER_MARKERS = (
    "dockerfile", "docker-compose.yml", "docker-compose.yaml", ".dockerignore",
    "deployment.yaml", "deployment.yml", "chart.yaml", "values.yaml",
)
IAC_MARKERS = (".tf", "kustomization.yaml", "chart.yaml", "values.yaml", "helmfile.yaml")
DEPLOY_KEYWORDS = re.compile(
    r"\b(deploy|kubectl|helm|docker push|terraform apply|aws ecs|fly deploy|"
    r"ansible-playbook|argocd|flux)\b",
    re.IGNORECASE,
)

MONITORING_APM = re.compile(
    r"\b(sentry|datadog|ddtrace|newrelic|new_relic|prometheus_client|prometheus|"
    r"pagerduty|opsgenie|honeycomb)\b",
    re.IGNORECASE,
)
MONITORING_TRACING = re.compile(
    r"\b(opentelemetry|opentracing|jaeger|otel|grafana|tempo)\b", re.IGNORECASE
)

TEST_FILE = re.compile(r"(^test_.*\.py$|.*_test\.(py|go)$|.*\.(spec|test)\.[jt]sx?$|.*Test\.java$)")
ISSUE_REF = re.compile(r"(#\d+|[A-Z][A-Z0-9]+-\d+)")

_SCAN_EXTS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".java", ".rb", ".rs",
    ".yml", ".yaml", ".toml", ".cfg", ".ini", ".txt", ".env.example",
}
_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "vendor", "dist", "build",
              "__pycache__", "site-packages", ".mypy_cache", ".pytest_cache"}


class InfraCollector(Collector):
    name = "infra"

    def collect(self) -> dict[str, object]:
        self._index()
        return {
            "ci_checks": "Yes" if self._has_ci else "No",
            "deployment_infra": self._deployment_infra(),
            "monitoring": self._monitoring(),
            "test_suite": self._test_suite(),
            "containerized": "Yes" if self._containerized else "No",
            "readme_quality": self._readme_quality(),
            "issue_tracker": self._issue_tracker(),
        }

    # --- one filesystem walk feeds every classifier ---------------------------
    def _index(self) -> None:
        self._has_ci = False
        self._containerized = False
        self._has_iac = False
        self._deploy_in_ci = False
        self._mon_apm = False
        self._mon_tracing = False
        self._mon_logging = False
        self._test_files = 0
        self._test_kinds: set[str] = set()
        self._readmes: list[Path] = []
        self._has_extra_docs = False
        self._ci_texts: list[str] = []

        for repo in self.repos:
            for path in _walk(repo.path):
                rel = str(path.relative_to(repo.path)).replace("\\", "/").lower()
                base = path.name.lower()
                self._classify_path(path, rel, base)

        self._deploy_in_ci = any(DEPLOY_KEYWORDS.search(t) for t in self._ci_texts)

    def _classify_path(self, path: Path, rel: str, base: str) -> None:
        if any(m in rel for m in CI_MARKERS):
            self._has_ci = True
            self._ci_texts.append(_safe_read(path))
        if base in CONTAINER_MARKERS or base.startswith("dockerfile"):
            self._containerized = True
        if path.suffix.lower() in IAC_MARKERS or base in IAC_MARKERS:
            self._has_iac = True
        if base.startswith("readme"):
            self._readmes.append(path)
        if base in ("contributing.md", "architecture.md") or rel.startswith("docs/") \
                or rel.startswith("rfcs/") or rel.startswith("adr/"):
            self._has_extra_docs = True
        if TEST_FILE.match(base):
            self._test_files += 1
            self._test_kinds.add(_test_kind(rel))
        if path.suffix.lower() in _SCAN_EXTS:
            text = _safe_read(path)
            if MONITORING_APM.search(text):
                self._mon_apm = True
            if MONITORING_TRACING.search(text):
                self._mon_tracing = True
            if re.search(r"\b(logging\.getLogger|structlog|winston|log4j|zap\.)\b", text):
                self._mon_logging = True

    # --- classifiers ----------------------------------------------------------
    def _deployment_infra(self) -> str:
        if not self._has_ci and not self._has_iac:
            return "None"
        if self._deploy_in_ci and self._has_iac:
            return "Enterprise"
        if self._deploy_in_ci:
            return "Full CI-CD"
        return "Basic CI"

    def _monitoring(self) -> str:
        if self._mon_tracing and self._mon_apm:
            return "Full SRE"
        if self._mon_apm:
            return "APM+Alerting"
        if self._mon_logging:
            return "Basic"
        return "None"

    def _test_suite(self) -> str:
        if self._test_files == 0:
            return "None"
        if self._test_files >= 20 and len(self._test_kinds) >= 2:
            return "Comprehensive"
        return "Basic"

    def _readme_quality(self) -> str:
        best = "None"
        for readme in self._readmes:
            best = _max_tier(best, _grade_readme(readme, self._has_extra_docs))
        return best

    def _issue_tracker(self) -> str:
        linked = self._commits_reference_issues()
        has_tracker = any(
            (repo.path / ".github" / "ISSUE_TEMPLATE").exists()
            or (repo.path / ".github" / "ISSUE_TEMPLATE.md").exists()
            for repo in self.repos
        )
        if linked and self._has_extra_docs:
            return "Full+Design Docs"
        if linked:
            return "Linked to Commits"
        if has_tracker:
            return "Basic"
        return "None"

    def _commits_reference_issues(self) -> bool:
        if not have("git"):
            return False
        for repo in self.repos:
            if not (repo.path / ".git").exists():
                continue
            res = run(
                ["git", "log", "--no-merges", "-n", "200", "--format=%s%n%b"],
                cwd=str(repo.path),
            )
            if res.ok and ISSUE_REF.search(res.stdout):
                return True
        return False


# --- helpers ------------------------------------------------------------------
_TIER_ORDER = ["None", "Basic", "Detailed", "Comprehensive"]


def _max_tier(a: str, b: str) -> str:
    return a if _TIER_ORDER.index(a) >= _TIER_ORDER.index(b) else b


def _grade_readme(path: Path, has_extra_docs: bool) -> str:
    text = _safe_read(path)
    if len(text.strip()) < 30:
        return "None"
    low = text.lower()
    has_setup = any(k in low for k in ("## install", "## setup", "## getting started",
                                       "## usage", "installation"))
    has_arch = any(k in low for k in ("## architecture", "## design", "## overview"))
    if has_extra_docs and has_setup:
        return "Comprehensive"
    if has_setup and has_arch:
        return "Detailed"
    if has_setup or len(text) > 1500:
        return "Detailed"
    return "Basic"


def _test_kind(rel: str) -> str:
    if "e2e" in rel or "end2end" in rel:
        return "e2e"
    if "integration" in rel:
        return "integration"
    return "unit"


def _walk(root: Path):
    import os

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d.lower() not in _SKIP_DIRS]
        for fn in filenames:
            yield Path(dirpath) / fn


def _safe_read(path: Path, limit: int = 200_000) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as fh:
            return fh.read(limit)
    except OSError:
        return ""
