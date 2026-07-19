#!/usr/bin/env python3
"""
Run repo_evaluator.py against many Subversion URLs (parallel).

URLs file format (one entry per line):
  - Empty lines and lines starting with # are ignored.
  - URL only:  https://svn.example.com/proj/trunk
  - With revision (any of):
      https://example.com/proj/trunk|12345
      https://example.com/proj/trunk| r12345
      https://example.com/proj/trunk<TAB>12345
      https://example.com/proj/trunk 12345

Global default revision (--default-revision) applies when a line has no per-line rev.

Usage:
  python bulk_svn_evaluator.py --urls-file urls.txt --workers 4 --output-dir eval_results/svn_bulk

  python bulk_svn_evaluator.py --urls-file urls.txt --token \"$SVN_PASS\" --svn-username jdoe \\
 --evaluator-args '--skip-f2p --skip-quality-checks'

Env:
  SVN_USERNAME, TOKEN or pass --token, optional SVN_EVALUATOR_ARGS (split with shlex)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def parse_url_line(line: str) -> Optional[Tuple[str, Optional[int]]]:
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    if "|" in line:
        left, _, right = line.partition("|")
        left, right = left.strip(), right.strip()
        if right:
            r = right.lower()
            if r.startswith("r") and r[1:].isdigit():
                return left, int(r[1:])
            if right.isdigit() or (right.startswith("-") and right[1:].isdigit()):
                return left, int(right)
            # Not a revision suffix — e.g. accidental "|" in text; use full line as URL.
            return line, None
        return left, None

    if "\t" in line:
        left, right = line.split("\t", 1)
        right = right.strip()
        if right.isdigit():
            return left.strip(), int(right)

    parts = line.split()
    if len(parts) >= 2:
        last = parts[-1]
        if last.isdigit():
            return " ".join(parts[:-1]), int(last)
        low = last.lower()
        if low.startswith("r") and low[1:].isdigit():
            return " ".join(parts[:-1]), int(low[1:])

    return line, None


def load_urls(path: Path) -> List[Tuple[str, Optional[int]]]:
    out: List[Tuple[str, Optional[int]]] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        parsed = parse_url_line(line)
        if parsed:
            out.append(parsed)
    return out


def run_dir_key(url: str, revision: Optional[int]) -> str:
    key = f"{url}\0{revision if revision is not None else ''}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]


def one_eval(
    *,
    repo_evaluator: Path,
    url: str,
    revision: Optional[int],
    out_root: Path,
    token: Optional[str],
    svn_username: Optional[str],
    svn_trust_cert: bool,
    svn_checkout_timeout: Optional[int],
    evaluator_extra: List[str],
    timeout_sec: int,
) -> Dict[str, Any]:
    """Run a single repo_evaluator subprocess."""
    sub = out_root / run_dir_key(url, revision)
    sub.mkdir(parents=True, exist_ok=True)
    out_json = sub / "eval.json"

    cmd: List[str] = [
        sys.executable,
        str(repo_evaluator),
        url,
        "--platform",
        "svn",
        "--json",
        "--output",
        str(out_json),
    ]
    if token:
        cmd.extend(["--token", token])
    if svn_username:
        cmd.extend(["--svn-username", svn_username])
    if svn_trust_cert:
        cmd.append("--svn-trust-cert")
    if revision is not None:
        cmd.extend(["--svn-revision", str(revision)])
    if svn_checkout_timeout is not None:
        cmd.extend(["--svn-checkout-timeout", str(svn_checkout_timeout)])
    cmd.extend(evaluator_extra)

    meta_path = sub / "_run.json"
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            cwd=str(repo_evaluator.parent),
        )
        elapsed = round(time.perf_counter() - t0, 3)
        err_tail = (proc.stderr or proc.stdout or "")[-4000:]
        record = {
            "url": url,
            "revision": revision,
            "exit_code": proc.returncode,
            "duration_seconds": elapsed,
            "output_json": str(out_json) if out_json.exists() else None,
            "error": None if proc.returncode == 0 else err_tail,
        }
        meta_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        return record
    except subprocess.TimeoutExpired:
        elapsed = round(time.perf_counter() - t0, 3)
        record = {
            "url": url,
            "revision": revision,
            "exit_code": -1,
            "duration_seconds": elapsed,
            "output_json": str(out_json) if out_json.exists() else None,
            "error": f"timeout after {timeout_sec}s",
        }
        meta_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        return record
    except Exception as e:
        elapsed = round(time.perf_counter() - t0, 3)
        record = {
            "url": url,
            "revision": revision,
            "exit_code": -1,
            "duration_seconds": elapsed,
            "output_json": None,
            "error": str(e),
        }
        meta_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        return record


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bulk-run repo_evaluator.py on SVN URLs from a file.",
    )
    parser.add_argument(
        "--urls-file",
        required=True,
        type=Path,
        help="Text file: one URL per line (optional revision per line; see module doc)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("eval_results/svn_bulk"),
        help="Directory for per-repo outputs (default: eval_results/svn_bulk)",
    )
    parser.add_argument(
        "--evaluator-script",
        type=Path,
        default=Path(__file__).resolve().parent / "repo_evaluator.py",
        help="Path to repo_evaluator.py",
    )
    parser.add_argument("--workers", type=int, default=4, help="Parallel workers")
    parser.add_argument(
        "--default-revision",
        type=int,
        default=None,
        help="SVN revision for checkout when a line does not specify one",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("SVN_PASSWORD") or os.environ.get("TOKEN"),
        help="SVN password (or TOKEN / SVN_PASSWORD env)",
    )
    parser.add_argument(
        "--svn-username",
        default=os.environ.get("SVN_USERNAME"),
        help="SVN username",
    )
    parser.add_argument(
        "--svn-trust-cert",
        action="store_true",
        help="Forward --svn-trust-cert to repo_evaluator",
    )
    parser.add_argument(
        "--svn-checkout-timeout",
        type=int,
        default=None,
        help="Forward --svn-checkout-timeout (sec; 0 = unlimited). Set --timeout >= this for huge repos.",
    )
    parser.add_argument(
        "--evaluator-args",
        default="",
        help="Extra arguments for repo_evaluator.py (quoted string, shell-split)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=3600,
        help="Per-repo subprocess timeout in seconds (default: 3600)",
    )
    args = parser.parse_args()

    if not args.urls_file.is_file():
        print(f"URLs file not found: {args.urls_file}", file=sys.stderr)
        return 1
    if not args.evaluator_script.is_file():
        print(f"repo_evaluator.py not found: {args.evaluator_script}", file=sys.stderr)
        return 1

    raw = load_urls(args.urls_file)
    if not raw:
        print("No URLs loaded from file.", file=sys.stderr)
        return 1

    tasks: List[Tuple[str, Optional[int]]] = []
    for url, rev in raw:
        tasks.append((url, rev if rev is not None else args.default_revision))

    extra = shlex.split(args.evaluator_args or "")
    env_extra = os.environ.get("SVN_EVALUATOR_ARGS", "")
    if env_extra and not extra:
        extra = shlex.split(env_extra)

    out_root = args.output_dir.resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    results: List[Dict[str, Any]] = []
    t_start = time.perf_counter()

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [
            pool.submit(
                one_eval,
                repo_evaluator=args.evaluator_script.resolve(),
                url=u,
                revision=r,
                out_root=out_root,
                token=args.token,
                svn_username=args.svn_username,
                svn_trust_cert=args.svn_trust_cert,
                svn_checkout_timeout=args.svn_checkout_timeout,
                evaluator_extra=extra,
                timeout_sec=args.timeout,
            )
            for u, r in tasks
        ]
        for fut in as_completed(futures):
            results.append(fut.result())

    total_seconds = round(time.perf_counter() - t_start, 3)
    ok = sum(1 for r in results if r.get("exit_code") == 0)
    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total": len(tasks),
        "completed_runs": len(results),
        "succeeded": ok,
        "failed": len(results) - ok,
        "total_seconds": total_seconds,
        "output_dir": str(out_root),
        "results": sorted(results, key=lambda x: (x.get("url") or "", x.get("revision") or -1)),
    }
    summary_path = out_root / "_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(
        f"Done: {ok}/{len(results)} succeeded "
        f"(tasks={len(tasks)}, output={out_root}, summary={summary_path})"
    )
    return 0 if ok == len(results) and len(results) == len(tasks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
