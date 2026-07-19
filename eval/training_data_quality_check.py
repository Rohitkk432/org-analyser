"""Static, LLM-free training-data-quality signals ported from repo_analyzer.py.

Covers the three fields repo_analyzer.py has that the rest of eval-kit/profiler/
quality don't: heuristic license-risk classification, eval-benchmark
(HumanEval/MBPP) contamination detection, and a composite training-suitability
grade (A-D) combining license risk, syntax validity, duplication, comment
density, function length, and test presence. No network access, no LLM calls.

License classification is heuristic — not legal advice. Secrets/PII detection
is intentionally NOT duplicated here; eval-kit's security_check.py already
covers that ground.
"""

from __future__ import annotations

import ast
import hashlib
import re
from collections import Counter
from pathlib import Path
from typing import Any

LICENSE_CLASSIFIERS = [
    # Order matters: specific ones first (AGPL before GPL, BSD-3 before BSD-2)
    ("AGPL-3.0",     r"gnu affero general public license"),
    ("LGPL",         r"gnu lesser general public license"),
    ("GPL-3.0",      r"gnu general public license[\s\S]{0,80}version 3"),
    ("GPL-2.0",      r"gnu general public license[\s\S]{0,80}version 2"),
    ("Apache-2.0",   r"apache license[,\s]*version 2\.0"),
    ("MPL-2.0",      r"mozilla public license[,\s]*(v(ersion)?\.?\s*)?2\.0"),
    ("MIT",          r"permission is hereby granted, free of charge"),
    ("BSD-3-Clause", r"redistribution and use in source and binary forms"
                     r"[\s\S]{0,600}neither the name"),
    ("BSD-2-Clause", r"redistribution and use in source and binary forms"),
    ("ISC",          r"permission to use, copy, modify, and(/or)? distribute "
                     r"this software"),
    ("Unlicense",    r"this is free and unencumbered software"),
    ("CC0-1.0",      r"cc0|creative commons zero"),
    ("WTFPL",        r"do what the f\w+ you want"),
]

LICENSE_RISK = {
    "MIT": "permissive", "Apache-2.0": "permissive",
    "BSD-2-Clause": "permissive", "BSD-3-Clause": "permissive",
    "ISC": "permissive", "Unlicense": "permissive", "CC0-1.0": "permissive",
    "WTFPL": "permissive", "MPL-2.0": "weak-copyleft", "LGPL": "weak-copyleft",
    "GPL-2.0": "copyleft", "GPL-3.0": "copyleft", "AGPL-3.0": "copyleft",
}

LICENSE_FILE_RE = re.compile(
    r"(^|/)(un)?licen[cs]e(\.(md|txt|rst))?$|(^|/)copying(\.txt)?$",
    re.IGNORECASE)

_SPDX_SHORT = {"mit": "MIT", "apache-2.0": "Apache-2.0", "apache2": "Apache-2.0",
               "gpl-2.0": "GPL-2.0", "gpl-3.0": "GPL-3.0", "gplv2": "GPL-2.0",
               "gplv3": "GPL-3.0", "agpl-3.0": "AGPL-3.0", "lgpl": "LGPL",
               "bsd-2-clause": "BSD-2-Clause", "bsd-3-clause": "BSD-3-Clause",
               "isc": "ISC", "mpl-2.0": "MPL-2.0", "unlicense": "Unlicense",
               "cc0": "CC0-1.0", "wtfpl": "WTFPL"}

# Distinctive HumanEval / MBPP signatures — if these are in training data
# it's benchmark contamination (eval scores become fake).
EVAL_CONTAMINATION_SIGNATURES = [
    "def has_close_elements(", "def separate_paren_groups(",
    "def truncate_number(", "def below_zero(",
    "def mean_absolute_deviation(", "def intersperse(",
    "def parse_nested_parens(", "def similar_elements(",
    "def is_not_prime(", "def heap_queue_largest(",
    "def count_ways(", "def differ_At_One_Bit_Pos(",
]

VENDOR_DIR_HINTS = ("/vendor/", "/node_modules/", "/dist/", "/build/",
                    "/.git/", "/bower_components/", "/storage/framework/",
                    "/__pycache__/", "/.venv/", "/venv/", "/.tox/",
                    "/site-packages/", "/pods/", "/.next/", "/.nuxt/",
                    "/coverage/", "/htmlcov/", "/.gradle/", "/deriveddata/",
                    "/.terraform/", "/target/debug/", "/target/release/")

GENERATED_FILE_SUFFIXES = (".min.js", ".min.css", ".bundle.js", ".chunk.js",
                           ".map", ".pb.go", "_pb2.py", "_pb2_grpc.py",
                           ".g.dart", ".freezed.dart", ".generated.ts",
                           ".d.ts")

CODE_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".kt", ".go",
                   ".rb", ".rs", ".c", ".h", ".cpp", ".cc", ".cs", ".php",
                   ".swift", ".m", ".scala", ".ex", ".exs", ".dart", ".sh",
                   ".lua", ".r", ".pl", ".vue", ".svelte"}

_COMMENT_PREFIXES = ("#", "//", "/*", "*", "--", "<!--", "%", ";", "'")
_FUNC_DEF_RE = re.compile(
    r"^\s*(?:async\s+)?(?:def|function|func|fn)\s+\w+|"
    r"^\s*(?:public|private|protected|static)[\w<>\[\],\s]*\s\w+\s*\([^;]*\)\s*\{",
    re.MULTILINE)


def classify_license(text: str) -> str:
    """SPDX-like name from license file text. Heuristic — not legal advice."""
    t = (text or "").lower()
    if len(t.strip()) <= 40 and t.strip() in _SPDX_SHORT:
        return _SPDX_SHORT[t.strip()]
    for name, pat in LICENSE_CLASSIFIERS:
        if re.search(pat, t):
            return name
    return ""


def _is_vendor_path(rel_path: str) -> bool:
    p = "/" + rel_path.replace("\\", "/").lower() + "/"
    return any(h in p for h in VENDOR_DIR_HINTS)


def _is_code_file(rel_path: str) -> bool:
    p = rel_path.lower()
    if _is_vendor_path(rel_path):
        return False
    if p.endswith(GENERATED_FILE_SUFFIXES):
        return False
    return any(p.endswith(ext) for ext in CODE_EXTENSIONS)


def _scan_file(content: str, rel_path: str) -> dict[str, Any]:
    """Per-file signals feeding the composite training-suitability grade."""
    lines = content.splitlines()
    n = len(lines) or 1
    stripped = [l.strip() for l in lines]
    nonblank = [s for s in stripped if s]
    comment = sum(1 for s in stripped if s.startswith(_COMMENT_PREFIXES))
    code_lines = max(1, n - (n - len(nonblank)) - comment)
    long_lines = sum(1 for l in lines if len(l) > 120)
    funcs = len(_FUNC_DEF_RE.findall(content))

    syntax_valid = None
    if rel_path.endswith(".py"):
        try:
            ast.parse(content)
            syntax_valid = True
        except (SyntaxError, ValueError, MemoryError, RecursionError):
            syntax_valid = False

    return {
        "lines": n,
        "code_lines": code_lines,
        "avg_len": sum(len(l) for l in lines) / n,
        "long_lines": long_lines,
        "comment_lines": comment,
        "funcs": funcs,
        "syntax_valid": syntax_valid,
        # hash=None for near-empty files so they don't collide and inflate dup %
        "hash": (hashlib.sha1("\n".join(nonblank).encode("utf-8", "ignore")).hexdigest()
                 if len(nonblank) >= 3 else None),
        "eval_contam": any(sig in content for sig in EVAL_CONTAMINATION_SIGNATURES),
    }


def analyze_training_data_quality(
    repo_path: str | Path,
    max_scan: int = 2000,
    has_tests: bool = True,
) -> dict[str, Any]:
    """Walk a local repo checkout and return license/contamination/training-
    suitability signals. Cheap, deterministic, no network access."""
    repo_path = Path(repo_path)
    all_files: list[tuple[Path, str]] = []
    for p in repo_path.rglob("*"):
        if not p.is_file():
            continue
        rel = str(p.relative_to(repo_path)).replace("\\", "/")
        if _is_vendor_path(rel):
            continue
        all_files.append((p, rel))

    # --- License detection ---
    license_name = ""
    lic_files = [(p, rel) for p, rel in all_files
                 if LICENSE_FILE_RE.search(rel) and "/" not in rel]
    for p, _ in lic_files[:2]:
        try:
            license_name = classify_license(p.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
        if license_name:
            break
    if not license_name:
        manifests = {rel: p for p, rel in all_files
                     if rel in ("package.json", "pyproject.toml", "Cargo.toml",
                                "composer.json", "setup.py")}
        for name in ("package.json", "pyproject.toml", "Cargo.toml", "composer.json", "setup.py"):
            p = manifests.get(name)
            if not p:
                continue
            try:
                c = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            m = re.search(r"""["']?license["']?\s*[:=]\s*["']([^"']{2,40})["']""",
                          c, re.IGNORECASE)
            if m:
                license_name = m.group(1).strip()
                break

    if license_name:
        risk = LICENSE_RISK.get(license_name, "unknown")
    elif lic_files:
        license_name, risk = "custom/unclassified", "unknown"
    else:
        license_name, risk = "NONE", "no-license (all rights reserved)"

    # --- Sampled scan: syntax validity, dedup, long lines, comments, contamination ---
    code_files = [(p, rel) for p, rel in all_files if _is_code_file(rel)]
    step = max(1, len(code_files) // max_scan) if code_files else 1
    sample = code_files[::step][:max_scan]

    tot: Counter = Counter()
    hashes: Counter = Counter()
    contam_files: list[str] = []
    syntax_valid = syntax_checked = files_scanned = 0

    for p, rel in sample:
        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        info = _scan_file(content, rel)
        files_scanned += 1
        tot["lines"] += info["lines"]
        tot["code_lines"] += info["code_lines"]
        tot["long_lines"] += info["long_lines"]
        tot["comment_lines"] += info["comment_lines"]
        tot["funcs"] += info["funcs"]
        if info["hash"]:
            hashes[info["hash"]] += 1
        if info["syntax_valid"] is not None:
            syntax_checked += 1
            syntax_valid += 1 if info["syntax_valid"] else 0
        if info["eval_contam"]:
            contam_files.append(rel)

    dup_files = sum(c - 1 for c in hashes.values() if c > 1)
    dup_pct = round(100 * dup_files / files_scanned, 1) if files_scanned else None
    comment_ratio = round(100 * tot["comment_lines"] / tot["lines"], 1) if tot["lines"] else None
    pct_long = round(100 * tot["long_lines"] / tot["lines"], 1) if tot["lines"] else None
    avg_func_len = round(tot["code_lines"] / tot["funcs"], 1) if tot["funcs"] else None
    syntax_pct = round(100 * syntax_valid / syntax_checked, 1) if syntax_checked else None

    # --- Composite score + training-suitability grade ---
    score = 100.0
    reasons: list[str] = []
    if syntax_checked and syntax_valid < syntax_checked:
        bad = 100 * (1 - syntax_valid / syntax_checked)
        score -= min(40, bad * 0.5)
        reasons.append(f"{round(bad)}% Python files syntax-invalid")
    if pct_long is not None and pct_long > 30:
        score -= 10
        reasons.append("very long lines (generated/obfuscated pattern)")
    if comment_ratio is not None:
        if comment_ratio < 2:
            score -= 10
            reasons.append("almost zero comments")
        elif comment_ratio > 60:
            score -= 5
            reasons.append("comment-heavy (auto-doc/generated pattern)")
    if dup_pct:
        score -= min(30, dup_pct)
        reasons.append(f"{dup_pct}% duplicate files")
    if avg_func_len is not None and avg_func_len > 80:
        score -= 10
        reasons.append("very long functions (avg >80 lines)")
    if not has_tests:
        score -= 10
        reasons.append("no tests")
    if contam_files:
        score -= 20
        reasons.append(f"eval-benchmark code in {len(contam_files)} files")
    score = max(0.0, round(score, 1))

    grade = "A" if score >= 80 else "B" if score >= 60 else "C" if score >= 40 else "D"
    if risk.startswith("no-license"):
        if grade in ("A", "B"):
            grade = "C"
        reasons.append("no license — training use is risky")
    elif risk == "copyleft":
        if grade == "A":
            grade = "B"
        reasons.append(f"copyleft license ({license_name})")

    return {
        "license": license_name,
        "license_risk": risk,
        "quality_files_scanned": files_scanned,
        "syntax_valid_pct": syntax_pct,
        "duplicate_pct": dup_pct,
        "eval_contamination_files": len(contam_files),
        "eval_contamination_detail": contam_files[:20],
        "training_quality_score": score,
        "training_suitability": grade,
        "training_quality_reasons": reasons,
    }
