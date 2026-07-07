"""Unit test coverage % from committed coverage reports (branch > line > function)."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from .base import Collector

# Common committed / CI-uploaded coverage artifact paths (relative to repo root).
_COVERAGE_CANDIDATES = (
    "coverage.xml",
    "coverage/coverage.xml",
    "coverage/cobertura.xml",
    "htmlcov/coverage.xml",
    ".coverage.xml",
    "lcov.info",
    "coverage/lcov.info",
    "coverage-final.json",
    "coverage/coverage-final.json",
    ".nyc_output/coverage-final.json",
)

_SKIP_PATH_PARTS = ("node_modules", "vendor", "dist", "build", ".git")


@dataclass
class CoverageRates:
    branch: float | None = None
    line: float | None = None
    function: float | None = None
    weight: int = 1

    def pick(self) -> tuple[float, str] | None:
        """Return (rate 0..1, metric name) using branch > line > function."""
        if self.branch is not None:
            return self.branch, "branch"
        if self.line is not None:
            return self.line, "line"
        if self.function is not None:
            return self.function, "function"
        return None


class CoverageCollector(Collector):
    name = "coverage"

    def collect(self) -> dict[str, object]:
        weighted_sum = 0.0
        weight_total = 0
        metric_used: str | None = None

        for repo in self.repos:
            rates = self._find_rates(repo.path)
            if rates is None:
                continue
            picked = rates.pick()
            if picked is None:
                continue
            rate, metric = picked
            metric_used = metric
            w = max(rates.weight, 1)
            weighted_sum += rate * w
            weight_total += w

        if weight_total == 0:
            self.warn("no coverage reports found; reporting 0%")
            return {"unit_test_coverage_pct": 0.0}

        if metric_used:
            self.warn(f"used {metric_used}-rate from coverage report(s)")
        return {"unit_test_coverage_pct": round(weighted_sum / weight_total, 4)}

    def _find_rates(self, root: Path) -> CoverageRates | None:
        for rel in _COVERAGE_CANDIDATES:
            path = root / rel
            if not path.is_file():
                continue
            rates = _parse_report(path)
            if rates is not None and rates.pick() is not None:
                return rates
        return None


def _parse_report(path: Path) -> CoverageRates | None:
    try:
        if path.suffix == ".xml":
            return _parse_cobertura_xml(path)
        if path.name == "lcov.info":
            return _parse_lcov(path)
        if path.name == "coverage-final.json":
            return _parse_istanbul_json(path)
    except (OSError, ET.ParseError, json.JSONDecodeError, ValueError):
        return None
    return None


def _parse_cobertura_xml(path: Path) -> CoverageRates | None:
    root = ET.parse(path).getroot()
    branch = _float_attr(root, "branch-rate")
    line = _float_attr(root, "line-rate")
    weight = _cobertura_line_weight(root) or 1
    if branch is None and line is None:
        line = _cobertura_line_rate_from_lines(root)
    return CoverageRates(branch=branch, line=line, weight=weight)


def _float_attr(elem, name: str) -> float | None:
    raw = elem.get(name)
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _cobertura_line_weight(root) -> int:
    total = 0
    for line in root.findall(".//class/line"):
        total += 1
    return total or 0


def _cobertura_line_rate_from_lines(root) -> float | None:
    total = covered = 0
    for line in root.findall(".//class/line"):
        total += 1
        try:
            if int(line.get("hits", 0)) > 0:
                covered += 1
        except ValueError:
            pass
    return _rate(covered, total)


def _parse_lcov(path: Path) -> CoverageRates | None:
    branch_found = branch_hit = 0
    fn_found = fn_hit = 0
    line_found = line_hit = 0

    with path.open("r", encoding="utf-8", errors="ignore") as fh:
        for raw in fh:
            line = raw.strip()
            if line.startswith("BRF:"):
                branch_found += _int_suffix(line)
            elif line.startswith("BRH:"):
                branch_hit += _int_suffix(line)
            elif line.startswith("FNF:"):
                fn_found += _int_suffix(line)
            elif line.startswith("FNH:"):
                fn_hit += _int_suffix(line)
            elif line.startswith("LF:"):
                line_found += _int_suffix(line)
            elif line.startswith("LH:"):
                line_hit += _int_suffix(line)

    weight = line_found or branch_found or fn_found or 1
    return CoverageRates(
        branch=_rate(branch_hit, branch_found),
        line=_rate(line_hit, line_found),
        function=_rate(fn_hit, fn_found),
        weight=weight,
    )


def _parse_istanbul_json(path: Path) -> CoverageRates | None:
    data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    if not isinstance(data, dict):
        return None

    branch_total = branch_hit = 0
    fn_total = fn_hit = 0
    stmt_total = stmt_hit = 0

    for file_path, file_data in data.items():
        if not isinstance(file_data, dict) or _skip_path(str(file_path)):
            continue
        for hits in file_data.get("b", {}).values():
            if not isinstance(hits, list):
                continue
            for h in hits:
                branch_total += 1
                if h:
                    branch_hit += 1
        for count in file_data.get("f", {}).values():
            fn_total += 1
            if count:
                fn_hit += 1
        for count in file_data.get("s", {}).values():
            stmt_total += 1
            if count:
                stmt_hit += 1

    weight = stmt_total or branch_total or fn_total or 1
    return CoverageRates(
        branch=_rate(branch_hit, branch_total),
        line=_rate(stmt_hit, stmt_total),
        function=_rate(fn_hit, fn_total),
        weight=weight,
    )


def _int_suffix(line: str) -> int:
    try:
        return int(line.split(":", 1)[1])
    except (IndexError, ValueError):
        return 0


def _rate(hit: int, total: int) -> float | None:
    if total <= 0:
        return None
    return hit / total


def _skip_path(path: str) -> bool:
    low = path.lower()
    return any(part in low for part in _SKIP_PATH_PARTS) or "/test" in low or low.startswith("test")
