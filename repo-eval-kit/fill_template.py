#!/usr/bin/env python3
"""
Read all repo_evaluator.py JSON output files and fill the
"Seller - Codebase Input Template" CSV.

Usage
─────
  # Fill template from eval_results/ (default):
  python fill_template.py

  # Custom input/output:
  python fill_template.py --input-dir eval_results --output report.csv

  # Include a company name for all rows:
  python fill_template.py --company "Acme Corp"

  # Only process specific JSON files:
  python fill_template.py --files eval_results/acme-corp__billing-service.json eval_results/acme-corp__web-app.json
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


# ──────────────────────────────────────────────────────────────────────────────
# Template columns (exact match to the shared CSV header)
# ──────────────────────────────────────────────────────────────────────────────

TEMPLATE_COLUMNS = [
    "Project Name",
    "Company Name : Fill intake form",
    "Code Base",
    "Language",
    "Repo Industry",
    "Repo Category",
    "Upload Evaluation Report Screenshot",
    "No of lines of code",
    "No of commits",
    "No of Test Files",
    "No of PRs",
    "Accepted PRs",
    "Ci/CD",
    "Test frameworks",
    "Total files",
    "Test files",
    "Source files",
    "# Commits in last 6 months",
    "Commits spread in days",
    "Has dockerfile",
    "Score",
    "  Repository Link Used for Evaluation ",
    "Recommendation",
    "Dockerfile / Screenshots",
    "Code-Adjacent Data Types (Jira, PRDs, Figma, Asana, Slack)",
    "Code Adjacent Data Links",
]


# ──────────────────────────────────────────────────────────────────────────────
# Score & Recommendation logic
# ──────────────────────────────────────────────────────────────────────────────

def compute_score(d: Dict[str, Any]) -> int:
    """
    Compute a 0-100 quality score from the evaluation JSON.

    Scoring rubric (100 points total):
      - Code volume & structure   : 20 pts
      - Commit quality            : 15 pts
      - Test coverage             : 15 pts
      - PR workflow               : 15 pts
      - CI/CD                     : 10 pts
      - Security                  :  10 pts
      - Production quality        : 10 pts
      - Vibe-coding (AI risk)     :  5 pts
    """
    m = d.get("repo_metrics", {})
    pr = d.get("pr_analysis", {})
    score = 0

    def _int(val, default=0) -> int:
        """Safely convert to int, handling None."""
        if val is None:
            return default
        try:
            return int(val)
        except (TypeError, ValueError):
            return default

    def _float(val, default=0.0) -> float:
        """Safely convert to float, handling None."""
        if val is None:
            return default
        try:
            return float(val)
        except (TypeError, ValueError):
            return default

    # ── Code volume & structure (20 pts) ─────────────────────────────────────
    loc = _int(m.get("total_loc", 0))
    if loc >= 1000:
        score += 5
    if loc >= 5000:
        score += 5
    if _int(m.get("total_files", 0)) >= 10:
        score += 5
    if _int(m.get("readme_length_chars", 0)) >= 200:
        score += 3
    if m.get("readme_has_installation", False):
        score += 2

    # ── Commit quality (15 pts) ──────────────────────────────────────────────
    commits = _int(m.get("total_commits", 0))
    if commits >= 50:
        score += 5
    if commits >= 500:
        score += 3
    spread = _float(m.get("commit_spread_ratio", 0))
    if spread >= 0.3:
        score += 4
    if spread >= 0.6:
        score += 3

    # ── Test coverage (15 pts) ───────────────────────────────────────────────
    test_ratio = _float(m.get("test_to_source_file_ratio", 0))
    if test_ratio > 0:
        score += 5
    if test_ratio >= 0.05:
        score += 5
    if test_ratio >= 0.15:
        score += 5

    # ── PR workflow (15 pts) ─────────────────────────────────────────────────
    total_prs = _int(pr.get("total_prs", 0))
    accepted = _int(pr.get("pass_first_filter", 0))
    if total_prs >= 5:
        score += 5
    if total_prs >= 20:
        score += 5
    if accepted >= 5:
        score += 5

    # ── CI/CD (10 pts) ──────────────────────────────────────────────────────
    if m.get("has_ci_cd", False):
        score += 10

    # ── Security (10 pts) — deduct for critical issues ──────────────────────
    sec_score = 10
    sec_critical = d.get("security_check_critical", "")
    if sec_critical:
        issues = len([l for l in sec_critical.split("\n") if l.strip()])
        sec_score = max(0, 10 - issues * 3)
    score += sec_score

    # ── Production quality (10 pts) — deduct for critical issues ────────────
    pq_score = 10
    pq_critical = d.get("production_quality_critical", "")
    if pq_critical:
        issues = len([l for l in pq_critical.split("\n") if l.strip()])
        pq_score = max(0, 10 - issues * 2)
    score += pq_score

    # ── Vibe-coding / AI risk (5 pts) ──────────────────────────────────────
    ai_risk = _int(m.get("ai_risk_score", 0))
    if ai_risk == 0:
        score += 5
    elif ai_risk <= 2:
        score += 3
    elif ai_risk <= 4:
        score += 1

    return min(score, 100)


def compute_recommendation(score: int, d: Dict[str, Any]) -> str:
    """Generate a recommendation string based on score and findings."""
    m = d.get("repo_metrics", {})
    pr = d.get("pr_analysis", {})
    issues: List[str] = []

    if (pr.get("total_prs") or 0) == 0:
        issues.append("No PRs/MRs found")
    if not m.get("has_ci_cd", False):
        issues.append("No CI/CD")
    if (m.get("test_to_source_file_ratio") or 0) < 0.01:
        issues.append("No tests")
    if (m.get("recent_commits_6mo") or 0) == 0:
        issues.append("No recent commits (6mo)")

    sec = d.get("security_check_critical", "")
    if sec:
        issues.append("Security issues found")

    pq = d.get("production_quality_critical", "")
    if pq:
        # Count critical production issues
        count = len([l for l in pq.split("\n") if l.strip()])
        issues.append(f"{count} production quality issues")

    if score >= 75:
        verdict = "Strong candidate"
    elif score >= 50:
        verdict = "Acceptable with caveats"
    elif score >= 30:
        verdict = "Weak — needs improvement"
    else:
        verdict = "Not recommended"

    if issues:
        return f"{verdict}. Issues: {'; '.join(issues)}"
    return verdict


# ──────────────────────────────────────────────────────────────────────────────
# Dockerfile detection from JSON data
# ──────────────────────────────────────────────────────────────────────────────

def has_dockerfile(d: Dict[str, Any]) -> bool:
    """Check if the repo has a Dockerfile based on available signals."""
    m = d.get("repo_metrics", {})

    # Check ci_files for docker-compose
    ci_files = m.get("ci_files", [])
    for f in ci_files:
        if "docker" in str(f).lower():
            return True

    # Check ecosystem_tags from taxonomy
    eco = d.get("ecosystem_tags", "")
    if "docker" in str(eco).lower():
        return True

    # Check vibe_coding signals/critical for Dockerfile mentions
    for field in ("vibe_coding_critical", "vibe_coding_signals",
                  "production_quality_critical", "production_quality_signals"):
        val = d.get(field, "")
        if "dockerfile" in str(val).lower():
            return True

    # Check languages dict for Dockerfile
    langs = m.get("languages", {})
    for lang_key in langs:
        if "docker" in lang_key.lower():
            return True

    return False


# ──────────────────────────────────────────────────────────────────────────────
# Build repo link
# ──────────────────────────────────────────────────────────────────────────────

def build_repo_link(d: Dict[str, Any], json_filename: str) -> str:
    """Construct the repo URL from available data."""
    full_name = d.get("repo_full_name", "")
    if not full_name:
        # Try to derive from filename: org__repo.json → org/repo
        base = Path(json_filename).stem
        if "__" in base:
            full_name = base.replace("__", "/", 1)

    # Detect platform from filename or data
    platform = "github"
    # GitLab repos often have nested paths (group/subgroup/project)
    if full_name.count("/") >= 2:
        platform = "gitlab"
    # Check if the JSON was produced with gitlab prefix
    for field in ("vibe_coding_critical", "security_check_critical", "production_quality_critical"):
        if "gitlab" in str(d.get(field, "")).lower():
            platform = "gitlab"

    if platform == "gitlab":
        return f"https://gitlab.com/{full_name}"
    return f"https://github.com/{full_name}"


# ──────────────────────────────────────────────────────────────────────────────
# Map JSON → template row
# ──────────────────────────────────────────────────────────────────────────────

def json_to_row(d: Dict[str, Any], json_filename: str,
                company: str = "") -> Dict[str, Any]:
    """Convert a repo_evaluator JSON dict into a template row dict."""
    m = d.get("repo_metrics", {})
    pr = d.get("pr_analysis", {})

    score = compute_score(d)
    recommendation = compute_recommendation(score, d)
    dockerfile = has_dockerfile(d)

    # Language(s)
    langs = m.get("languages", {})
    primary = m.get("primary_language", "")
    if langs:
        lang_str = ", ".join(sorted(langs.keys(), key=lambda k: -langs[k]))
    elif primary:
        lang_str = primary
    else:
        lang_str = ""

    # Test frameworks
    frameworks = m.get("test_frameworks", [])
    fw_str = ", ".join(frameworks) if frameworks else "None detected"

    # CI/CD
    has_ci = m.get("has_ci_cd", False)
    ci_files = m.get("ci_files", [])
    if has_ci and ci_files:
        ci_str = f"Yes ({', '.join(ci_files)})"
    elif has_ci:
        ci_str = "Yes"
    else:
        ci_str = "No"

    # Code base = org/repo full name
    full_name = d.get("repo_full_name", "")
    project_name = d.get("repo_name", "")
    if not full_name:
        base = Path(json_filename).stem
        full_name = base.replace("__", "/", 1) if "__" in base else base
    if not project_name:
        project_name = full_name.split("/")[-1] if "/" in full_name else full_name

    # Industry & category from taxonomy if available
    industry = d.get("domain_primary", "") or d.get("vertical_tags", "")
    category = d.get("archetype", "") or d.get("domain_secondary", "")

    return {
        "Project Name": project_name,
        "Company Name : Fill intake form": company,
        "Code Base": full_name,
        "Language": lang_str,
        "Repo Industry": industry,
        "Repo Category": category,
        "Upload Evaluation Report Screenshot": "",
        "No of lines of code": m.get("total_loc") or 0,
        "No of commits": m.get("total_commits") or 0,
        "No of Test Files": m.get("test_files") or 0,
        "No of PRs": pr.get("total_prs") or 0,
        "Accepted PRs": pr.get("pass_first_filter") or 0,
        "Ci/CD": ci_str,
        "Test frameworks": fw_str,
        "Total files": m.get("total_files") or 0,
        "Test files": m.get("test_files") or 0,
        "Source files": m.get("source_files") or 0,
        "# Commits in last 6 months": m.get("recent_commits_6mo") or 0,
        "Commits spread in days": m.get("distinct_commit_days") or 0,
        "Has dockerfile": "Yes" if dockerfile else "No",
        "Score": score,
        "  Repository Link Used for Evaluation ": build_repo_link(d, json_filename),
        "Recommendation": recommendation,
        "Dockerfile / Screenshots": "",
        "Code-Adjacent Data Types (Jira, PRDs, Figma, Asana, Slack)": "",
        "Code Adjacent Data Links": "",
    }


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def find_json_files(input_dir: str) -> List[str]:
    """Find all repo evaluation JSON files in a directory (flat or nested org/repo structure)."""
    files = []
    input_path = Path(input_dir)

    # Recursively find all JSON files
    for f in sorted(input_path.rglob("*.json")):
        if f.name.startswith("_"):  # skip _summary.json
            continue
        # Skip files that are clearly not repo evaluations
        # (must have repo_name or repo_full_name key)
        try:
            with open(f) as fh:
                data = json.load(fh)
            if "repo_name" in data or "repo_full_name" in data:
                files.append(str(f))
        except (json.JSONDecodeError, KeyError):
            continue
    return files


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fill the repo evaluation template CSV from JSON results.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--input-dir", default="eval_results",
        help="Directory containing repo_evaluator JSON output files (default: eval_results)",
    )
    parser.add_argument(
        "--files", nargs="+", default=None,
        help="Specific JSON files to process (overrides --input-dir)",
    )
    parser.add_argument(
        "--output", default="eval_results/template_report.csv",
        help="Output CSV file path (default: eval_results/template_report.csv)",
    )
    parser.add_argument(
        "--company", default="",
        help="Company name to fill in for all rows",
    )
    parser.add_argument(
        "--format", choices=["csv", "both"], default="both",
        help="Output format: csv only, or both csv + pretty terminal table (default: both)",
    )
    args = parser.parse_args()

    # Gather JSON files
    if args.files:
        json_files = args.files
    else:
        json_files = find_json_files(args.input_dir)

    if not json_files:
        print(f"❌ No JSON files found in {args.input_dir}", file=sys.stderr)
        return 1

    print(f"📂 Found {len(json_files)} evaluation JSON file(s)\n")

    # Process each JSON
    rows: List[Dict[str, Any]] = []
    for json_path in json_files:
        try:
            with open(json_path) as f:
                data = json.load(f)
            row = json_to_row(data, json_path, company=args.company)
            rows.append(row)
            print(f"  ✅ {row['Code Base']:.<50s} score={row['Score']}")
        except Exception as e:
            print(f"  ⚠  Skipped {json_path}: {e}", file=sys.stderr)

    if not rows:
        print("\n❌ No valid JSON files processed.", file=sys.stderr)
        return 1

    # Sort by score descending
    rows.sort(key=lambda r: r["Score"], reverse=True)

    # Write CSV
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TEMPLATE_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n✅ Template CSV written to: {args.output}")
    print(f"   {len(rows)} repos, sorted by score (highest first)\n")

    # Print summary table
    if args.format == "both":
        print(f"{'─' * 100}")
        print(f"  {'Project':<35s} {'Language':<15s} {'LOC':>8s} {'Commits':>8s} "
              f"{'PRs':>5s} {'Tests':>6s} {'CI/CD':<6s} {'Score':>5s}  Recommendation")
        print(f"{'─' * 100}")
        for r in rows:
            rec_short = r["Recommendation"][:40]
            print(f"  {r['Project Name']:<35s} {r['Language'][:14]:<15s} "
                  f"{r['No of lines of code']:>8,} {r['No of commits']:>8,} "
                  f"{r['No of PRs']:>5} {r['Test files']:>6} "
                  f"{'Yes' if 'Yes' in r['Ci/CD'] else 'No':<6s} "
                  f"{r['Score']:>5}  {rec_short}")
        print(f"{'─' * 100}")

        # Quick stats
        scores = [r["Score"] for r in rows]
        avg_score = sum(scores) / len(scores) if scores else 0
        print(f"\n  📊  Total repos: {len(rows)}  |  Avg score: {avg_score:.1f}  |  "
              f"Min: {min(scores)}  |  Max: {max(scores)}")
        strong = sum(1 for s in scores if s >= 75)
        acceptable = sum(1 for s in scores if 50 <= s < 75)
        weak = sum(1 for s in scores if s < 50)
        print(f"       Strong (≥75): {strong}  |  Acceptable (50-74): {acceptable}  |  "
              f"Weak (<50): {weak}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())










