"""Duplication Ratio via jscpd, weighted across repos by logical LOC."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from ..tools import have, run
from .base import Collector


class DuplicationCollector(Collector):
    name = "duplication"

    JSCPD_ARGS = [
        "--min-tokens", "50",
        "--min-lines", "5",
        "--reporters", "json",
        "--ignore", "**/.git/**,**/node_modules/**,**/vendor/**,**/dist/**,**/build/**",
        "--silent",
    ]

    def collect(self) -> dict[str, object]:
        jscpd = self._jscpd_cmd()
        if jscpd is None:
            self.warn("jscpd not available (need jscpd or npx); duplication skipped")
            return {}

        weighted_sum = 0.0
        weight_total = 0
        for repo in self.repos:
            ratio, loc = self._run_one(jscpd, repo.path)
            if ratio is None:
                continue
            weighted_sum += ratio * max(loc, 1)
            weight_total += max(loc, 1)

        if weight_total == 0:
            self.warn("jscpd returned no results")
            return {}
        return {"duplication_ratio": round(weighted_sum / weight_total, 4)}

    def _jscpd_cmd(self) -> list[str] | None:
        if have("jscpd"):
            return ["jscpd"]
        if have("npx"):
            return ["npx", "--yes", "jscpd"]
        return None

    def _run_one(self, jscpd: list[str], path: Path):
        """(ratio, lines) for one repo, or (None, 0).

        A missing/garbled report means jscpd hard-failed (it sometimes does under load —
        OOM, throttling), so we retry once and, if it still fails, surface the real exit
        code/stderr instead of a silent "no results". A report that parses but has no
        ``percentage`` means the repo simply had nothing measurable (e.g. empty branch).
        """
        err = (None, "")
        for _ in range(2):
            with tempfile.TemporaryDirectory() as out:
                # Run jscpd from the repo dir, never the (possibly bind-mounted) caller cwd.
                res = run(
                    [*jscpd, *self.JSCPD_ARGS, "--output", out, str(path)],
                    cwd=str(path),
                    timeout=600,
                )
                data = self._read_report(Path(out) / "jscpd-report.json")
            if data is not None:
                stats = data.get("statistics", {}).get("total", {})
                percentage = stats.get("percentage")
                if percentage is None:
                    return None, 0  # ran cleanly, nothing to measure
                return percentage / 100.0, stats.get("lines", 0)
            err = (res.returncode, (res.stderr or res.stdout).strip()[-200:])
        self.warn(f"jscpd failed for {path.name} (exit {err[0]}): {err[1] or 'no report written'}")
        return None, 0

    @staticmethod
    def _read_report(report: Path):
        if not report.exists():
            return None
        try:
            return json.loads(report.read_text())
        except (json.JSONDecodeError, OSError):
            return None
