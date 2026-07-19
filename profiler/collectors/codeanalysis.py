"""Docstring Ratio and Avg Function Length via per-language source analysis.

Python is analysed accurately with the stdlib ``ast`` module. Other common languages
use a lightweight brace/heuristic scan for function boundaries and a preceding
doc-comment check. Results are weighted by function count across all files.
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

from .base import Collector

_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "vendor", "dist", "build",
              "__pycache__", "site-packages", ".mypy_cache", ".pytest_cache", "migrations"}

# language -> (function-declaration regex, doc-comment-above test)
_CSTYLE_FUNC = re.compile(
    r"^\s*(?:export\s+|public\s+|private\s+|protected\s+|static\s+|async\s+|func\s+|"
    r"function\s+|def\s+)?[\w<>\[\]\*&,\s]*?\b\w+\s*\([^;{]*\)\s*(?:->\s*[\w<>\[\]\*&,\. ]+)?\s*\{",
)
_JS_FUNC = re.compile(r"\bfunction\b|\b\w+\s*=\s*\([^)]*\)\s*=>|\b\w+\s*\([^)]*\)\s*\{")
_DOC_BLOCK_ABOVE = re.compile(r"(/\*\*[\s\S]*?\*/|///|//!)\s*$")


class CodeAnalysisCollector(Collector):
    name = "codeanalysis"

    PY_EXT = {".py"}
    CSTYLE_EXT = {".go", ".java", ".cs", ".rs", ".c", ".cpp", ".h", ".hpp", ".kt", ".scala"}
    JS_EXT = {".js", ".jsx", ".ts", ".tsx"}

    def collect(self) -> dict[str, object]:
        total_funcs = 0
        documented = 0
        total_len = 0

        for repo in self.repos:
            for path in _walk(repo.path):
                ext = path.suffix.lower()
                if ext in self.PY_EXT:
                    funcs, docs, length = self._analyze_python(path)
                elif ext in self.CSTYLE_EXT or ext in self.JS_EXT:
                    funcs, docs, length = self._analyze_cstyle(path, ext)
                else:
                    continue
                total_funcs += funcs
                documented += docs
                total_len += length

        if total_funcs == 0:
            self.warn("no functions found for docstring/length analysis")
            return {}
        return {
            "docstring_ratio": round(documented / total_funcs, 4),
            "avg_function_length": round(total_len / total_funcs, 1),
        }

    def _analyze_python(self, path: Path) -> tuple[int, int, int]:
        text = _safe_read(path)
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            return 0, 0, 0
        funcs = docs = length = 0
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                funcs += 1
                if ast.get_docstring(node):
                    docs += 1
                end = getattr(node, "end_lineno", node.lineno) or node.lineno
                length += max(end - node.lineno + 1, 1)
        return funcs, docs, length

    def _analyze_cstyle(self, path: Path, ext: str) -> tuple[int, int, int]:
        lines = _safe_read(path).splitlines()
        pattern = _JS_FUNC if ext in self.JS_EXT else _CSTYLE_FUNC
        funcs = docs = length = 0
        for i, line in enumerate(lines):
            if not pattern.search(line):
                continue
            if "{" not in line:
                continue
            funcs += 1
            above = "\n".join(lines[max(0, i - 3):i]).rstrip()
            if _DOC_BLOCK_ABOVE.search(above):
                docs += 1
            length += _brace_span(lines, i)
        return funcs, docs, length


def _brace_span(lines: list[str], start: int) -> int:
    """Lines from an opening-brace line to its matching close (best-effort)."""
    depth = 0
    for j in range(start, min(len(lines), start + 400)):
        depth += lines[j].count("{") - lines[j].count("}")
        if depth <= 0 and j > start:
            return j - start + 1
        if depth <= 0 and lines[j].count("}") and j == start:
            return 1
    return 1


def _walk(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d.lower() not in _SKIP_DIRS]
        for fn in filenames:
            yield Path(dirpath) / fn


def _safe_read(path: Path, limit: int = 1_000_000) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as fh:
            return fh.read(limit)
    except OSError:
        return ""
