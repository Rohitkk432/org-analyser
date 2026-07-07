#!/usr/bin/env python3
"""
Org pipeline without repo-quality-score (no sealed JSON).

Same as run_org_pipeline.py but skips the repo-quality-score phase and org rollup.

Usage:
    python run_org_pipeline_no_quality.py --github-org data-tech --tokens-file tokens --workers 10
    python run_org_pipeline_no_quality.py --github-repo data-tech/frontend --tokens-file tokens --workers 1
    python run_org_pipeline_no_quality.py --gitlab-project my-group/repo-a --gitlab-project my-group/repo-b --tokens-file tokens --workers 4
"""

from run_org_pipeline import run_pipeline

if __name__ == "__main__":
    raise SystemExit(run_pipeline(include_quality_score=False))
