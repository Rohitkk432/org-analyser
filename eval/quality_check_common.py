"""Shared clone/file/LLM-sampling helpers for the three quality-check engines:
eval/production_quality_check.py, eval/vibecode_check.py, eval/security_check.py
(wired together via eval/quality_checks.py).

Each check keeps its own criteria/scan functions, LLM prompt, and severity
split -- only the identical clone/file-walk plumbing and the "accumulate
snippets under a token budget" loop live here.
"""

from __future__ import annotations

import os
import subprocess
from typing import Callable, Iterable, Optional


def read_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except Exception:
        return ""


def rel_path(path: str, root: str) -> str:
    return os.path.relpath(path, root)


def run_git(args: list[str], cwd: str, timeout: int = 30) -> str:
    try:
        r = subprocess.run(
            ["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
        return r.stdout.strip()
    except Exception:
        return ""


def clone_repo(owner: str, repo: str, dest: str, token: str) -> tuple[bool, str]:
    url = (
        f"https://{token}@github.com/{owner}/{repo}.git"
        if token
        else f"https://github.com/{owner}/{repo}.git"
    )
    r = subprocess.run(
        ["git", "clone", "--depth", "200", url, dest],
        capture_output=True,
        text=True,
        timeout=300,
    )
    return r.returncode == 0, r.stderr.strip() if r.returncode != 0 else ""


def is_test_file(path: str, root: str, keywords: Iterable[str]) -> bool:
    rel = rel_path(path, root).lower()
    return any(k in rel for k in keywords)


def detect_language(files: list[str], python_exts, js_exts) -> str:
    """Return 'python' or 'js' based on dominant file extension count."""
    py = sum(1 for f in files if os.path.splitext(f)[1] in python_exts)
    js = sum(1 for f in files if os.path.splitext(f)[1] in js_exts)
    return "python" if py >= js else "js"


def find_files(
    root: str,
    extensions,
    exclude_dirs,
    skip_toolgen_fn: Optional[Callable[[str], bool]] = None,
    max_file_size: Optional[int] = None,
) -> list[str]:
    results = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in exclude_dirs]
        for f in filenames:
            if os.path.splitext(f)[1] not in extensions:
                continue
            full = os.path.join(dirpath, f)
            if skip_toolgen_fn and skip_toolgen_fn(os.path.relpath(full, root)):
                continue
            if max_file_size is not None:
                try:
                    if os.path.getsize(full) > max_file_size:
                        continue
                except OSError:
                    continue
            results.append(full)
    return results


def budget_fill_samples(
    ordered_files: list[str],
    snippet_fn: Callable[[str], str],
    char_budget: int,
    break_on_overflow: bool = True,
) -> tuple[str, int, list[str]]:
    """Accumulate snippet_fn(f) for f in ordered_files until char_budget is hit.

    break_on_overflow=True stops at the first snippet that would overflow the
    budget (assumes ordered_files is priority-sorted, so later files matter
    less). False instead skips just that one file and keeps trying smaller
    ones further down the list -- vibecode_check's flagged-files pass wants
    every flagged file attempted rather than stopping early.

    Returns (joined_text, total_chars_used, files_actually_included) -- the
    third value matters when a caller needs to know which files from
    ordered_files were skipped for not fitting, not just skipped for being
    empty.
    """
    snippets: list[str] = []
    included: list[str] = []
    total_chars = 0
    for f in ordered_files:
        chunk = snippet_fn(f)
        if not chunk:
            continue
        if total_chars + len(chunk) > char_budget:
            if break_on_overflow:
                break
            continue
        snippets.append(chunk)
        included.append(f)
        total_chars += len(chunk)
    return "".join(snippets), total_chars, included
