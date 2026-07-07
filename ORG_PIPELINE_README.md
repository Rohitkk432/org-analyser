# Org Pipeline

One command runs analysis pipelines for **one GitHub org**, **one GitLab group**, **one GitLab project**, or a **folder of local/downloaded repos** per invocation:

1. **Merged PR counts** — fresh API fetch for every repo *(skipped in local mode)*
2. **PR task-profile report** — rules + LLM classification (`Standard Feature Work %`, `Rich Task %`, `Other %`, `Automated %`)
3. **Codebase profiler** — vendor intake sheet (`codebase_sheet.filled.xlsx`)
4. **Repo analyzer** — LLM-usage detection, training-data-quality scoring, and CI/test analysis per repo (`repo_analyzer.py`, local-clone mode)
5. **Data eval-kit** — full repository evaluation with **mandatory LLM** (quality, taxonomy, PR rubrics)
6. **Repo quality score** *(full kit only)* — sealed 0–100 heuristic scoring per repo + org rollup

Output is a timestamped run folder and a **zip** containing all reports and logs.

| Kit | Entry script |
|-----|----------------|
| **Full** (`org-pipeline-kit-full.zip`) | [`run_org_pipeline.py`](./run_org_pipeline.py) |
| **No sealed JSON** (`org-pipeline-kit-no-quality.zip`) | [`run_org_pipeline_no_quality.py`](./run_org_pipeline_no_quality.py) |

---

## Requirements

### Software

| Tool | Purpose |
|------|---------|
| Python 3.10+ | Orchestrator and child scripts |
| git | Clone repositories |
| scc | Lines-of-code metrics (codebase profiler) |
| Node.js + npx | Duplication metrics via jscpd (codebase profiler) |

### Mac install (Homebrew)

```bash
brew install git scc node
```

### Python packages

From the repo root:

```bash
python3.12 -m venv .venv  # or python3.11 / python3.10
source .venv/bin/activate
python --version           # must be 3.10+
python -m pip install --upgrade pip setuptools wheel hatchling
python -m pip install -r org_pipeline_requirements.txt
python -m pip install -e ./codebase_profiler
```

If you received the **org-pipeline-kit** zip, extract it, `cd org-pipeline-kit`, and use `requirements.txt` instead:

```bash
unzip org-pipeline-kit.zip && cd org-pipeline-kit
python3.12 -m venv .venv && source .venv/bin/activate
python --version           # must be 3.10+
python -m pip install --upgrade pip setuptools wheel hatchling
python -m pip install -r requirements.txt
python -m pip install -e ./codebase_profiler
cp tokens.example tokens   # then edit tokens with real keys
```

If your prompt already shows another virtualenv, for example `(env)`, run
`deactivate` first. `codebase_profiler` requires Python 3.10+, so a Python 3.9
venv will fail even after upgrading `pip`.

If editable install fails with `setup.py or setup.cfg not found`, upgrade `pip`
inside the venv and rerun the profiler install:

```bash
python -m pip install --upgrade pip hatchling
python -m pip install -e ./codebase_profiler
```

---

## Tokens and API keys

Create a `tokens` file in the repo root (or pass `--tokens-file`).

**The script will not start without an OpenAI key.** Set either:

- environment variable `OPENAI_API_KEY`, or
- `openai_key=sk-...` in the tokens file

Required per platform:

| Key in tokens file | When required |
|--------------------|---------------|
| `github-data-token=ghp_...` | `--github-org` runs; optional for local mode if using GitHub manifest/remotes |
| `gitlab_token=glpat-...` | `--gitlab-group` or `--gitlab-project` runs; optional for local mode if using GitLab manifest/remotes |
| `openai_key=sk-...` or `OPENAI_API_KEY` | Always |

Example (use placeholders — never commit real secrets):

```ini
github-data-token=ghp_your_github_token
gitlab_token=glpat_your_gitlab_token
openai_key=sk-your_openai_key
```

---

## Usage

**One org, group, or local folder per run.**

```bash
# GitHub org
python run_org_pipeline.py --github-org data-tech --tokens-file tokens --workers 10

# GitLab group
python run_org_pipeline.py --gitlab-group my-group --tokens-file tokens --workers 10

# Single GitLab project
python run_org_pipeline.py --gitlab-project my-group/my-repo --tokens-file tokens --workers 1

# Multiple GitLab projects (one run, one output zip)
python run_org_pipeline.py \
  --gitlab-project my-group/repo-a \
  --gitlab-project my-group/repo-b \
  --gitlab-project other-group/repo-c \
  --tokens-file tokens \
  --workers 4

# Local/downloaded repos (one subfolder per repo)
python run_org_pipeline.py --local-repos-dir ./my-repos --tokens-file tokens --workers 4

# Local repos with GitHub mapping for PR analysis (optional manifest)
python run_org_pipeline.py --local-repos-dir ./my-repos --repos-manifest repos-manifest.json --tokens-file tokens
```

Example `repos-manifest.json`:

```json
{
  "frontend": "data-tech/frontend",
  "backend": "gitlab:my-group/my-backend"
}
```

If no manifest is provided, the script uses each folder name as the repo id and tries to parse `origin` from git remotes. Pure-local mode (no remote) still runs profiler and eval-kit repo-level LLM; PR task-profile, PR rubrics, and sealed quality score require a remote mapping + token where noted.

```bash
# Same flags, but skip repo-quality-score / sealed JSON:
python run_org_pipeline_no_quality.py --github-org data-tech --tokens-file tokens --workers 10
python run_org_pipeline_no_quality.py \
  --gitlab-project my-group/repo-a \
  --gitlab-project my-group/repo-b \
  --tokens-file tokens \
  --workers 4
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--github-org` | — | GitHub org to process (mutually exclusive with other targets) |
| `--gitlab-group` | — | GitLab top-level group to process |
| `--gitlab-project` | — | GitLab project path(s). Repeat flag or comma-separate. All repos land in one run zip. |
| `--local-repos-dir` | — | Directory with one repo per subfolder |
| `--repos-manifest` | — | JSON map `folder_name → owner/repo` for local PR API access |
| `--local-batch-name` | `local` | Label used in output paths for local runs |
| `--tokens-file` | `tokens` | Path to key=value tokens file |
| `--workers` | `10` | Parallel repo workers |
| `--retries` | `3` | Retries per repo per phase |
| `--clone-depth` | `0` (full clone) | Git shallow clone depth; `0` = full history |
| `--output-dir` | `outputs/org-pipeline-runs` | Parent folder for run directories |
| `--github-host` | `github.com` | GitHub API host |
| `--gitlab-host` | `gitlab.com` | GitLab host |
| `--github-token-name` | `github-data-token` | Key in tokens file for GitHub API |

There are **no** `--limit`, `--max-repos`, or `--max-prs` options. Every discovered repo is processed.

---

## What each run does

1. **Preflight** — verifies tokens, OpenAI key, git, scc, node
2. **Discover repos** — lists org/group repos via API, or subfolders under `--local-repos-dir`
3. **Merged PR counts** — refetches counts from the API *(skipped for local mode)*
4. **PR task-profile** — org-level `org_summary.csv` / `org_summary.json` under `pr-task-profile/` *(skipped in local mode without remote mapping)*
5. **Per repo (parallel)** — for each repo:
   - **Remote mode:** delete any prior clone and **fresh clone**
   - **Local mode:** use existing checkout in place (no clone, source not deleted)
   - Run codebase profiler → append row to xlsx
   - Run repo analyzer (local-clone mode) → per-repo CSV + detail JSON
   - Run eval-kit with full LLM (no skip flags)
   - Run repo-quality-score collect → classify → seal *(full pipeline only)*
6. **Org quality rollup** — `org.sealed.json` + summary CSV/JSON *(full pipeline only)*
7. **Remove clones** — remote clones deleted before packaging; **local source folders are never deleted**
8. **Zip** — reports and logs only, packaged as `<run-name>.zip`

If one repo fails a phase after retries, the run **continues** with the next repo. Check `manifest.json` and per-repo logs under `logs/`.

---

## Output layout

```
outputs/org-pipeline-runs/
└── org-pipeline-data-tech-20260627T120000Z/
    ├── manifest.json
    ├── org-pipeline-data-tech-20260627T120000Z.zip
    ├── logs/
    │   ├── pipeline.log
    │   └── pr-task-profile.log
    │   └── github/data-tech/<repo>/
    │       ├── clone.log
    │       ├── codebase-profiler.log
    │       ├── repo-analyzer.log
    │       ├── eval-kit.log
    │       └── repo-quality-score.log
    ├── merged-pr-counts/
    │   ├── github_data-tech.csv
    │   ├── summary.csv
    │   └── manifest.json
    ├── pr-task-profile/
    │   └── scan_<timestamp>/
    │       ├── org_summary.csv
    │       └── org_summary.json
    ├── codebase-profiler/
    │   └── codebase_sheet.filled.xlsx
    ├── repo-analyzer/
    │   └── <org>/<repo>/<repo>.csv (+ <repo>_detail.json)
    ├── eval-kit/
    │   └── <org>/<repo>/*.json
    └── repo-quality-score/
        ├── repos/*.sealed.json
        ├── org.sealed.json
        ├── summary.csv
        └── summary.json
```

---

## Runtime and disk

- Large orgs can take **many hours** or days depending on repo count, size, and LLM latency.
- Every repo is **fully cloned** during processing (unless you set `--clone-depth`), then **clones are deleted** before the zip is created.
- Plan for temporary disk space during the run, not in the final deliverable.

---

## Troubleshooting

| Issue | What to check |
|-------|----------------|
| Script exits immediately | OpenAI key missing; required platform token missing |
| Clone failures | Token scopes; repo access; logs in `logs/.../clone.log` |
| Profiler warnings | Install `scc` and Node.js; see profiler log |
| Repo-analyzer failures | Repo log under `repo-analyzer.log`; runs local-only, no token needed |
| Eval-kit failures | `OPENAI_API_KEY` valid; repo log under `eval-kit.log` |
| Partial run | Normal for large orgs — inspect `manifest.json` summary |

---

## Components (not replaced)

This orchestrator calls existing tools in the repo:

- `count_merged_prs.py` / `export_all_merged_prs.py`
- `pr_task_profile_report.py` — see [`PR_TASK_PROFILE_README.md`](./PR_TASK_PROFILE_README.md)
- `codebase_profiler/`
- `repo_analyzer.py` — LLM-usage detection, training-data-quality scoring, CI/test analysis
- `repo-eval-kit/repo_evaluator.py`
- `repo-quality-score/` + `outputs/repo-quality-score-agent/agent_rubric_scorer.py` *(full kit only)*
