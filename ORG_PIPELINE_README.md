# Org Pipeline

One command runs analysis pipelines for **one GitHub org**, **one GitLab group/project**,
**one Bitbucket workspace/repo**, or a **folder of local/downloaded repos** per invocation:

1. **Merged PR counts** — fresh API fetch for every repo *(skipped in local mode)*
2. **PR task-profile report** — rules + LLM classification (`Standard Feature Work %`, `Rich Task %`, `Other %`, `Automated %`)
3. **Codebase profiler** — vendor intake sheet (`codebase_sheet.filled.xlsx`)
4. **Repo analyzer** — LLM-usage detection, training-data-quality scoring, and CI/test analysis per repo (`analysis/repo_analyzer.py`, local-clone mode)
5. **Data eval-kit** — full repository evaluation with **mandatory LLM** (quality, taxonomy, PR rubrics)
6. **Repo quality score** — sealed 0–100 heuristic scoring per repo + org rollup *(pass `--skip-quality-score` to skip)*

Output is a timestamped run folder and a **zip** containing all reports and logs.

Entry point: `org-analyser` (installed via `pip install -e .`, backed by [`cli.py`](./cli.py)).
`--skip-quality-score` replaces what used to be a separate no-quality script.

---

## Requirements

### Software

| Tool | Purpose |
|------|---------|
| Python 3.10+ | Orchestrator and child processes |
| git | Clone repositories |
| scc | Lines-of-code metrics (`profiler/`) |
| Node.js + npx | Duplication metrics via jscpd (`profiler/`) |

### Mac install (Homebrew)

```bash
brew install git scc node
```

### Python packages

From the repo root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python --version                      # must be 3.10+
python -m pip install --upgrade pip   # need pip>=21.3 for editable installs (PEP 660)
pip install -e .
cp config.example.yml config.yml
```

If your prompt already shows another virtualenv, for example `(env)`, run
`deactivate` first — this package requires Python 3.10+, so an older venv
will fail even after upgrading `pip`.

If the editable install fails with `setup.py or setup.cfg not found`, upgrade
`pip` inside the venv and retry:

```bash
python -m pip install --upgrade pip hatchling
pip install -e .
```

---

## Tokens and API keys

Edit `config.yml` → fill in `tokens:` (only whichever platform(s) you use).
`config.yml` is gitignored, never committed. Pass `--tokens-file` instead if
you'd rather keep tokens in a separate key=value file.

**The pipeline will not start without an LLM credential.** Set one of:

- environment variable `OPENAI_API_KEY`, or
- `openai_key=sk-...` under `tokens:` in `config.yml`, or
- `AZURE_OPENAI_ENDPOINT` + `AZURE_OPENAI_API_KEY` (+ `AZURE_OPENAI_DEPLOYMENT`, `OPENAI_API_VERSION`) in the environment

Required per platform:

| Key under `tokens:` | When required |
|--------------------|---------------|
| `github-data-token` | `--github-org`/`--github-repo` runs; optional for local mode if using a GitHub manifest/remote |
| `gitlab_token` | `--gitlab-group`/`--gitlab-project` runs; optional for local mode if using a GitLab manifest/remote |
| `bitbucket_token` (+ `bitbucket_username` for app passwords) | `--bitbucket-repo` runs; optional for public repos, required to list a whole `--bitbucket-workspace` |
| `openai_key` (or `OPENAI_API_KEY`/Azure env vars) | Always |

Example `config.yml` (use placeholders — never commit real secrets):

```yaml
tokens:
  github-data-token: ghp_your_github_token
  gitlab_token: glpat_your_gitlab_token
  bitbucket_token: your_bitbucket_token
  openai_key: sk-your_openai_key
```

---

## Usage

**One org, group, workspace, or local folder per run.**

```bash
# GitHub org
org-analyser --github-org your-org --workers 10

# GitLab group
org-analyser --gitlab-group my-group --workers 10

# Single GitLab project
org-analyser --gitlab-project my-group/my-repo --workers 1

# Multiple GitLab projects (one run, one output zip)
org-analyser \
  --gitlab-project my-group/repo-a \
  --gitlab-project my-group/repo-b \
  --gitlab-project other-group/repo-c \
  --workers 4

# Bitbucket workspace
org-analyser --bitbucket-workspace my-workspace --workers 10

# Single Bitbucket repo
org-analyser --bitbucket-repo my-workspace/my-repo --workers 1

# Local/downloaded repos (one subfolder per repo)
org-analyser --local-repos-dir ./my-repos --workers 4

# Local repos with GitHub mapping for PR analysis (optional manifest)
org-analyser --local-repos-dir ./my-repos --repos-manifest repos-manifest.json

# Skip repo-quality-score / sealed JSON
org-analyser --github-org your-org --skip-quality-score

# Skip F2P/P2P test verification in eval-kit (slowest phase; recommended for large repos)
org-analyser --github-org your-org --skip-f2p

# Never contact a remote API — code-based analyses only, on local checkouts
org-analyser --local-repos-dir ./my-repos --local-only
```

Any flag can instead be set as a default in `config.yml` — with a target and
tokens filled in there, `org-analyser` runs with zero flags.

Example `repos-manifest.json`:

```json
{
  "frontend": "your-org/frontend",
  "backend": "gitlab:my-group/my-backend"
}
```

If no manifest is provided, the pipeline uses each folder name as the repo id
and tries to parse `origin` from git remotes. Pure-local mode (no remote)
still runs profiler and eval-kit repo-level LLM; PR task-profile, PR rubrics,
and sealed quality score require a remote mapping + token where noted.
`--local-only` forces pure-local mode even if a checkout still has an `origin`
remote.

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--github-org` | — | GitHub org to process (mutually exclusive with other targets) |
| `--github-repo` | — | GitHub repo path(s) (`owner/repo`). Repeat flag or comma-separate. |
| `--gitlab-group` | — | GitLab top-level group to process |
| `--gitlab-project` | — | GitLab project path(s). Repeat flag or comma-separate. All repos land in one run zip. |
| `--bitbucket-workspace` | — | Bitbucket workspace to process |
| `--bitbucket-repo` | — | Bitbucket repo path(s) (`workspace/repo`). Repeat flag or comma-separate. |
| `--local-repos-dir` | — | Directory with one repo per subfolder |
| `--repos-manifest` | — | JSON map `folder_name → owner/repo` (or `gitlab:group/repo`) for local PR API access |
| `--local-batch-name` | `local` | Label used in output paths for local runs |
| `--local-only` | off | Never contact a remote API; local checkouts only |
| `--tokens-file` | — | Path to a key=value tokens file, instead of `config.yml`'s `tokens:` mapping |
| `--workers` | `10` | Parallel repo workers |
| `--retries` | `3` | Retries per repo per phase |
| `--clone-depth` | `0` (full clone) | Git shallow clone depth; `0` = full history |
| `--retention-days` | `90` | Delete run folders older than this before starting (run bundles contain contributor data; `0` disables the sweep) |
| `--skip-quality-score` | off | Skip the repo-quality-score phase and sealed-JSON org rollup |
| `--skip-f2p` | off | Skip F2P/P2P test verification in eval-kit |
| `--output-dir` | `outputs/org-analyser-runs` | Parent folder for run directories |
| `--github-host` | `github.com` | GitHub API host |
| `--gitlab-host` | `gitlab.com` | GitLab host |
| `--github-token-name` | `github-data-token` | Key in tokens for GitHub API |

There are **no** `--limit`, `--max-repos`, or `--max-prs` options. Every discovered repo is processed.

---

## What each run does

1. **Preflight** — verifies tokens, LLM credential (OpenAI or Azure), git, scc, node
2. **Discover repos** — lists org/group/workspace repos via API, or subfolders under `--local-repos-dir`
3. **Merged PR counts** — refetches counts from the API *(skipped for local mode)*
4. **PR task-profile** — org-level `org_summary.csv` / `org_summary.json` under `pr-task-profile/` *(skipped in local mode without remote mapping)*
5. **Per repo (parallel)** — for each repo:
   - **Remote mode:** delete any prior clone and **fresh clone** (token passed via a short-lived `git config` header, never embedded in the URL or written to `.git/config`)
   - **Local mode:** use existing checkout in place (no clone, source not deleted)
   - Run codebase profiler → append row to xlsx
   - Run repo analyzer (local-clone mode) → per-repo CSV + detail JSON
   - Run eval-kit with full LLM (unless `--skip-f2p`)
   - Run repo-quality-score collect → classify → seal *(unless `--skip-quality-score`)*
6. **Org quality rollup** — `org.sealed.json` + summary CSV/JSON *(unless `--skip-quality-score`)*
7. **Remove clones** — remote clones deleted before packaging; **local source folders are never deleted**
8. **Zip** — reports and logs only, packaged as `<run-name>.zip`

If one repo fails a phase after retries, the run **continues** with the next repo. Check `manifest.json` and per-repo logs under `logs/`.

---

## Output layout

```
outputs/org-analyser-runs/
└── org-analyser-your-org-20260627T120000Z/
    ├── manifest.json
    ├── org-analyser-your-org-20260627T120000Z.zip
    ├── logs/
    │   ├── pipeline.log
    │   └── pr-task-profile.log
    │   └── github/your-org/<repo>/
    │       ├── clone.log
    │       ├── codebase-profiler.log
    │       ├── repo-analyzer.log
    │       ├── eval-kit.log
    │       └── repo-quality-score.log
    ├── merged-pr-counts/
    │   ├── github_your-org.csv
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
| Script exits immediately | LLM credential missing; required platform token missing |
| Clone failures | Token scopes; repo access; logs in `logs/.../clone.log` |
| Profiler warnings | Install `scc` and Node.js; see profiler log |
| Repo-analyzer failures | Repo log under `repo-analyzer.log`; runs local-only, no token needed |
| Eval-kit failures | LLM credential valid; repo log under `eval-kit.log` |
| Bitbucket auth errors | See `profiler/README.md` → Authentication for the token-type-to-env-var mapping (Atlassian API token vs. app password vs. access token) |
| Partial run | Normal for large orgs — inspect `manifest.json` summary |

---

## Components (not replaced)

`cli.py` orchestrates existing packages in this repo:

- `analysis/merged_prs.py` / `analysis/pr_task_profile.py`
- `analysis/repo_analyzer.py` — LLM-usage detection, training-data-quality scoring, CI/test analysis; see [`PR_TASK_PROFILE_README.md`](./PR_TASK_PROFILE_README.md) for PR task-profile details
- `profiler/`
- `eval/repo_evaluator.py`
- `quality/` *(unless `--skip-quality-score`)*
