"""Subprocess helpers and external-tool discovery (scc, jscpd, gh, git)."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class ToolError(RuntimeError):
    """A required external tool is missing or failed."""


def have(tool: str) -> bool:
    return shutil.which(tool) is not None


@dataclass
class RunResult:
    ok: bool
    stdout: str
    stderr: str
    returncode: int


def run(
    cmd: list[str],
    *,
    cwd: str | None = None,
    timeout: int = 600,
    check: bool = False,
) -> RunResult:
    """Run a command, capturing output. Never raises on non-zero unless ``check``."""
    logger.debug("run: %s (cwd=%s)", " ".join(cmd), cwd)
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            timeout=timeout,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired as exc:
        if check:
            raise ToolError(f"{cmd[0]} timed out after {timeout}s") from exc
        return RunResult(False, "", f"timeout after {timeout}s", -1)
    except FileNotFoundError as exc:
        if check:
            raise ToolError(f"{cmd[0]} not found on PATH") from exc
        return RunResult(False, "", f"{cmd[0]} not found", -1)

    result = RunResult(proc.returncode == 0, proc.stdout, proc.stderr, proc.returncode)
    if check and not result.ok:
        raise ToolError(f"{' '.join(cmd)} failed ({proc.returncode}): {proc.stderr[:500]}")
    return result


def run_json(cmd: list[str], *, cwd: str | None = None, timeout: int = 600):
    """Run a command and parse stdout as JSON, or None on any failure."""
    res = run(cmd, cwd=cwd, timeout=timeout)
    if not res.ok or not res.stdout.strip():
        return None
    try:
        return json.loads(res.stdout)
    except json.JSONDecodeError:
        logger.warning("could not parse JSON from %s", cmd[0])
        return None
