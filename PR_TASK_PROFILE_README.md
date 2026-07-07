# PR Task-Profile Report

Classify every **merged** pull request / merge request into task profiles using two independent methods:

1. **Rules** — deterministic rulebook (fast, consistent, transparent)
2. **LLM** — language model judging the same extracted signals (better at nuance)

Supports **GitHub** (GraphQL) and **GitLab** (REST).

Script: [`pr_task_profile_report.py`](./pr_task_profile_report.py)

---

## Task profiles

| Profile | Definition |
|---------|------------|
| `simple_fix` | 1–2 files, no meaningful human discussion (config, deps, typos). |
| `standard_feature_work` | 3–10 files, typically touches tests, normal review. |
| `rich_task` | Linked issue **and** substantive human review. |
| `other` | Does not cleanly fit the above. |
| `automated` | Bot-authored PRs (Dependabot, Renovate, etc.). |

---

## Requirements

- Python 3.9+
- Dependencies:

```bash
pip install requests openai python-dotenv
```

---

## Setup

Set credentials as environment variables or in a `.env` file (loaded automatically):

```dotenv
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx          # only for GitLab targets
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

| Variable | Required | Notes |
|----------|----------|-------|
| `GITHUB_TOKEN` | GitHub targets | Read access to target repos. |
| `GITLAB_TOKEN` | GitLab targets | Read access to target groups/projects. |
| `OPENAI_API_KEY` | Always | LLM pass is mandatory. |

---

## Usage

### GitHub targets

| Goal | Command |
|------|---------|
| One repo | `--repo owner/name` |
| Several repos | `--repo owner/a,owner/b` |
| All repos of an owner | `--repo owner` |
| Whole org | `--org my-org` |
| User's repos | `--user my-handle` |

### GitLab targets

| Goal | Command |
|------|---------|
| Whole group (incl. subgroups) | `--gitlab-group my-group` |
| Single project | `--gitlab-project group/project` |

### Examples

```bash
# GitHub org — all merged PRs, org-level summary + zip
python3 pr_task_profile_report.py --org data-tech

# GitHub repo with tuning for large orgs
python3 pr_task_profile_report.py --org acme-corp --page-size 50 --max-workers 16 --sleep 0.5

# GitLab group
python3 pr_task_profile_report.py --gitlab-group my-group --max-workers 16 --sleep 0.3

# Mixed targets in one run
python3 pr_task_profile_report.py --org acme-corp --repo acme-corp/mobile-app
```

---

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--repo` | — | GitHub `owner/name` or bare owner. Repeatable / comma-separated. |
| `--org` | — | GitHub org login. Repeatable / comma-separated. |
| `--user` | — | GitHub user login. Repeatable / comma-separated. |
| `--gitlab-group` | — | GitLab group path. Repeatable / comma-separated. |
| `--gitlab-project` | — | GitLab project path. Repeatable / comma-separated. |
| `--include-archived` | off | Include archived repos/projects. |
| `--no-forks` / `--include-forks` | forks excluded | Fork handling for GitHub expansion. |
| `--output-dir` | `outputs` | Base directory for run output. |
| `--model` | `gpt-4o-mini` | OpenAI model for LLM pass. |
| `--max-workers` | `6` | Parallel LLM calls. |
| `--page-size` | `50` | GitHub GraphQL page size (lower if 502 errors). |
| `--sleep` | `0.2` | Seconds between API pages. |
| `--verbose` | off | DEBUG console output. |

Every run always scans **all** resolved repos and **all** merged PRs/MRs in each repo, and always creates a zip archive of the org-level deliverables.

---

## Output

Each run creates a timestamped directory: `outputs/scan_<YYYYMMDD_HHMMSS>/`

### Primary deliverables (org-level, repo rows)

| File | Description |
|------|-------------|
| **`org_summary.csv`** | One row per repository with PR counts and task-profile percentages (rules + LLM). Final row is weighted org total. |
| **`org_summary.json`** | Same repo-level data as structured JSON, plus metadata, org total, combined summary, and failures. |
| **`scan_<timestamp>.log`** | Full run log — repos scanned, API pages, retries, per-repo summaries, failures. |
| **`failures.json`** | Written only when repos fail (fetch or classification errors). |
| **`scan_<timestamp>.zip`** | Archive containing `org_summary.csv`, `org_summary.json`, the log, and `failures.json` (if any). |

### Additional detail files

| File | Description |
|------|-------------|
| `combined_report.json` | Full metadata + all PR-level results. |
| `combined_per_pr.csv` | Every PR/MR with both labels and extracted signals. |
| `repos/<slug>.json` / `.csv` | Per-repo reports. |

### `org_summary.csv` columns

`repository`, `platform`, `total_prs`, `agreement_rate_pct`, `llm_error_count`,
`rules_simple_fix_pct`, `rules_standard_feature_work_pct`, `rules_rich_task_pct`, `rules_other_pct`, `rules_automated_pct`,
`llm_simple_fix_pct`, `llm_standard_feature_work_pct`, `llm_rich_task_pct`, `llm_other_pct`, `llm_automated_pct`

### `org_summary.json` structure

```jsonc
{
  "metadata": { "run_id": "...", "targets": {...}, "repositories_failed": {...} },
  "org_total": { "repository": "org total", "total_prs": 1234, ... },
  "combined_summary": { "rules": {...}, "llm": {...}, "agreement": {...} },
  "repositories": [ /* one object per repo, same fields as CSV rows */ ],
  "failures": { "owner/repo": "fetch failed: ..." }
}
```

---

## How it works

1. **Resolve targets** → de-duplicated list of GitHub repos or GitLab projects.
2. **Fetch merged PRs/MRs** via GitHub GraphQL or GitLab REST (with checkpoint/resume support).
3. **Extract signals** — file count, tests, linked issues, discussion, reviewers, bots.
4. **Classify twice** — rules and LLM on the same signals.
5. **Write outputs** — org-level repo summary (CSV + JSON), per-PR detail, log, and zip archive.

Checkpoints are stored under `<output-dir>/checkpoints/` so interrupted runs can resume.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Token not set | Export `GITHUB_TOKEN`, `GITLAB_TOKEN`, or `OPENAI_API_KEY`. |
| GraphQL 502/503/504 | Lower `--page-size`, raise `--sleep`; script retries automatically. |
| Rate limits | Lower `--max-workers`, raise `--sleep`. |
| Slow GitLab scan | 2 API calls per MR; expect hours for large groups. |
| `llm_category = error` | Transient API failure; re-run affected repos. |

---

## Interpreting results

- **High agreement rate** → rules and LLM concur; labels are more trustworthy.
- **`top_disagreements`** → best PRs to spot-check manually.
- **Neither label is ground truth** — agreement means consistency, not correctness.
