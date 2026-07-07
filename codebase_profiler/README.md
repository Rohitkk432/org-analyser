# codebase_profiler

Auto-fills the vendor **codebase intake sheet** (`codebase_sheet.xlsx`) by running
measurement tools over a repository. It computes every column derivable from code,
git history, and a hosting-platform API, and leaves true vendor fields (price, vendor
name, holdout verification) blank or supplied via `--meta`.

It works in three modes:

- **Local** — point at a folder already on disk.
- **Single remote repo** (`--repo`) — clone one GitHub/GitLab repo, write one row.
- **Whole organization** (`--organization`) — clone every repo under a GitHub org /
  GitLab group, or every repo in a Bitbucket workspace / project and write one row each.

## Requirements

| Tool | Why it's needed |
|------|-----------------|
| Homebrew | Mac package manager used to install everything else |
| `git` | Cloning repos and reading commit history |
| `uv` | Runs the Python script and manages its dependencies |
| `scc` | Counts lines of code, languages, files |
| Node.js (`node` + `npx`) | Runs `jscpd` for the duplication metric |
| `jscpd` | Duplication ratio (optional — skipped if absent) |

> The `gh` CLI is **not required** for the manual install — it's only a convenience
> fallback for local repos with a GitHub remote when you don't pass a token. (The Docker
> image bundles `gh`, so local-folder PR/fork stats work there without installing anything.)

## Easiest path: Docker (no tool installation)

If you have **Docker Desktop** installed, you don't need to install Python, scc, Node or
anything else — the image bundles them all. From inside the project folder:

```bash
# One-time setup: build the image (a few minutes). Optional — the first real
# run builds it automatically too.
./run.sh --install

# One GitHub repo (reuses your `gh` login if present; or pass --token)
./run.sh --repo owner/name

# One GitLab repo
GITLAB_TOKEN=glpat_xxx ./run.sh --repo https://gitlab.com/group/project --platform gitlab

# A whole GitHub org / GitLab group (name OR full URL — platform inferred from a URL)
./run.sh --organization my-github-org
./run.sh --organization https://github.com/data-tech
GITLAB_TOKEN=glpat_xxx ./run.sh --organization my-group --platform gitlab
GITLAB_TOKEN=glpat_xxx ./run.sh --organization https://gitlab.com/my-group
BITBUCKET_USERNAME=you BITBUCKET_TOKEN=xxx ./run.sh --organization my-workspace/MYPROJ --platform bitbucket

# A repo folder that's inside the current directory
./run.sh ./some-local-repo

# Force a rebuild of the image after updating the code
./run.sh --build --repo owner/name
```

What `run.sh` handles for you:

- **Builds the image once** (first run takes a few minutes; after that it's instant).
- **Writes results to the folder you run from** — `codebase_sheet.filled.xlsx`, appended across runs.
- **Caches cloned repos** in a Docker volume, so the same repo isn't downloaded twice
  between runs.
- **Forwards your `gh` login and `GITHUB_TOKEN`/`GITLAB_TOKEN`** into the container.

> First-time notes: the initial `./run.sh` builds the image (a few minutes — that's normal,
> not a hang). Large repos still take time to clone and scan the first time; the second run
> is fast thanks to the cache. To profile a folder, that folder must be **inside the
> directory you run `./run.sh` from** (that directory is what gets shared with the container).

If you'd rather not use Docker, follow the manual Mac install below.

## Install on a Mac — step by step (non-technical)

Open the **Terminal** app (press `Cmd+Space`, type "Terminal", hit Enter) and paste these
commands one block at a time, pressing Enter after each.

**1. Install Homebrew** (the Mac installer for developer tools). Skip if you already have it.

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

After it finishes it may print two `echo ...` lines starting with `eval`. Copy-paste and run
those so `brew` is found, then close and reopen Terminal.

**2. Install the tools** (Homebrew installs `git`, `uv`, `scc`, and Node in one go):

```bash
brew install git uv scc node
```

**3. Install `jscpd`** (the duplication checker) so it's ready and fast:

```bash
npm install -g jscpd
```

**4. Check everything is installed** — each line should print a version number:

```bash
git --version && uv --version && scc --version && node --version && jscpd --version
```

If any line says "command not found", re-run step 2/3 for that tool.

**5. Set up this project** (run from inside the `codebase_profiler` folder):

```bash
cd ~/Coding/codebase_profiler
uv sync
```

You're ready. Jump to [Usage](#usage).

## If someone sent you this as a ZIP

You received a `codebase_profiler.zip`. Here's the whole path from zero:

1. **Unzip it** — double-click the file in Finder. You'll get a `codebase_profiler` folder
   (say, in `~/Downloads`).
2. **Install the tools** — follow [Install on a Mac](#install-on-a-mac--step-by-step-non-technical)
   above (Homebrew, then `brew install git uv scc node`, then `npm install -g jscpd`). You
   only ever do this once per computer.
3. **Open the folder in Terminal**: type `cd ` (with a space), then drag the unzipped
   `codebase_profiler` folder onto the Terminal window and press Enter.
4. **Set it up**: `uv sync`
5. **Run it** (see the cases below). The blank spreadsheet template ships inside the zip,
   and results are written to `codebase_sheet.filled.xlsx` **in the folder you run from**,
   so you never have to hunt for output. The tool also prints the full path at the end.

### The common cases, copy-paste

```bash
# A) A repo already on your Mac (a folder):
uv run codebase-profiler /path/to/some/repo

# B) One GitHub repo:
uv run codebase-profiler --repo owner/name --token ghp_your_github_token

# C) One GitLab repo (a URL works too):
uv run codebase-profiler --repo https://gitlab.com/group/project --token glpat_your_token

# D) Every repo in a GitHub org:
uv run codebase-profiler --organization the-org --token ghp_your_github_token

# E) Every repo in a GitLab group:
uv run codebase-profiler --organization the-group --platform gitlab --token glpat_your_token

# Try a big org safely first with --limit, then drop it for the full run:
uv run codebase-profiler --organization the-org --token ghp_xxx --limit 3
```

Every run **adds rows to the same `codebase_sheet.filled.xlsx`** (it never overwrites), so
you can keep profiling more repos into one sheet. Use `--out myfile.xlsx` to choose a
different file.

## Authentication

Remote modes need an API token. It is resolved in this order:

1. `--token ...` on the command line
2. an env var — **GitHub:** `GITHUB_TOKEN`, `GH_TOKEN`, `GIT_TOKEN`; **GitLab:** `GITLAB_TOKEN`, `GIT_TOKEN`; **Bitbucket:** `BITBUCKET_TOKEN`, `BITBUCKET_APP_PASSWORD`
3. **GitHub only:** your existing `gh` CLI login (`gh auth token`) — so if you've run
   `gh auth login`, GitHub org/repo mode just works with **no token flag at all**.

The token is used only in memory — to authenticate API calls and to build a clone URL —
and is never written to disk or printed (clone errors are redacted).

### Bitbucket tokens (Cloud)

Create one of the following in Bitbucket → **Personal settings**:

| Token type | Where to create | Scopes needed | Env vars |
|------------|-----------------|---------------|----------|
| **Atlassian API token** (`ATATT…`) | [id.atlassian.com → Security → API tokens](https://id.atlassian.com/manage-profile/security/api-tokens) | Bitbucket read access on your account | `ATLASSIAN_EMAIL` + `BITBUCKET_TOKEN` |
| **App password** | Personal settings → **App passwords** | `Repositories: Read`, `Pull requests: Read`, `Projects: Read` | `BITBUCKET_USERNAME` + `BITBUCKET_TOKEN` |
| **Workspace access token** | Workspace settings → **Access tokens** | `repository:read`, `pullrequest:read`, `project:read` | `BITBUCKET_TOKEN` only (Bearer auth) |

```bash
# Atlassian API token (starts with ATATT…) — use your Atlassian login EMAIL, not username
export ATLASSIAN_EMAIL=you@company.com
export BITBUCKET_TOKEN=ATATT3x...

# App password (Bitbucket username + app password)
export BITBUCKET_USERNAME=you
export BITBUCKET_TOKEN=your_app_password

# One repo
uv run codebase-profiler --repo my-workspace/backend-api --platform bitbucket

# Whole Bitbucket project (all repos in project MYPROJ)
uv run codebase-profiler --organization https://bitbucket.org/my-workspace/workspace/projects/MYPROJ --platform bitbucket

# Or shorthand
uv run codebase-profiler --organization my-workspace/MYPROJ --platform bitbucket

# All repos in a workspace
uv run codebase-profiler --organization my-workspace --platform bitbucket
```

For **Bitbucket Data Center / Server**, pass `--host your-bitbucket.company.com` and use
`--organization PROJECT_KEY` (e.g. `MYPROJ`) with a personal access token that can read
repos and pull requests.

```bash
# GitHub: easiest path — log in once, then no token needed
gh auth login
uv run codebase-profiler --organization my-github-org

# Or pass a token explicitly (GitHub PAT needs `repo` scope, + SSO-authorized for the org)
export GITHUB_TOKEN=ghp_xxx
export GITLAB_TOKEN=glpat_xxx    # GitLab PAT with `read_api` + `read_repository`
export BITBUCKET_USERNAME=you
export BITBUCKET_TOKEN=your_app_password
```

## Usage

```bash
# --- Local ---------------------------------------------------------------
# Profile a folder already on disk; PR/fork come from the gh CLI if available
uv run codebase-profiler ~/Coding/test-repo --print -v
uv run codebase-profiler ~/Coding/test-repo --no-github   # purely local

# --- Single remote repo --------------------------------------------------
# owner/name or a full URL; platform is inferred from a URL, else --platform
uv run codebase-profiler --repo acme-corp/backend-api
uv run codebase-profiler --repo https://gitlab.com/group/sub/project
uv run codebase-profiler --repo my-workspace/backend-api --platform bitbucket

# --- Whole organization / group ------------------------------------------
# One row per repo; Originating company is set to the org/group name
uv run codebase-profiler --organization acme-corp --out ~/Downloads/acme-corp.xlsx
uv run codebase-profiler --organization my-group --platform gitlab --limit 10
uv run codebase-profiler --organization https://bitbucket.org/my-workspace/workspace/projects/MYPROJ --platform bitbucket

# Self-managed hosts
uv run codebase-profiler --organization team --platform gitlab --host gitlab.acme.com

# Supply vendor fields for every row
uv run codebase-profiler --repo acme-corp/backend-api \
    --meta vendor.json --out ~/Downloads/quote.xlsx
```

### Key flags

| Flag | Purpose |
|------|---------|
| `path` (positional) | Local folder to profile (mutually exclusive with `--repo`/`--organization`) |
| `--repo OWNER/NAME\|URL` | Clone & profile one remote repo |
| `--organization ORG` | Clone & profile every repo under a GitHub org / GitLab group / Bitbucket workspace or project |
| `--platform github\|gitlab\|bitbucket` | Platform for remote modes (default `github`, inferred from a URL) |
| `--host HOST` | Self-managed GitHub Enterprise / GitLab host |
| `--token TOKEN` | API token (else env vars above) |
| `--workdir DIR` | Where repos are cloned/pulled (default `~/.cache/codebase_profiler/clones`) |
| `--limit N` | Org mode: only the first N repos |
| `--out FILE` | Output xlsx (default `<template>.filled.xlsx`); created if missing, appended if present |
| `--no-github` | Skip all PR/MR & fork API calls |
| `--meta FILE` | JSON of vendor fields applied to every row |

Remote repos are **full clones** (history is needed for commit/contributor/PR metrics)
into `--workdir`; a repo already present there is fetched instead of re-cloned, so
re-runs are cheap.

### Which branch is measured

To avoid being skewed by an **abandoned default branch** (e.g. a `master` left untouched
for years while work moved to `develop`), remote clones don't just measure whatever the
default branch points at. After fetching, the tool checks out the **most recently committed
long-lived branch** and measures that:

- Candidates are integration branches only — `main`, `master`, `develop`/`dev`, `staging`,
  `trunk`, `production`/`prod`, and `release/*` / `stable/*`. Short-lived **feature/topic
  branches are ignored**.
- Among those, the one with the newest commit wins (`git for-each-ref --sort=-committerdate`).
- If no long-lived branch matches, the default checkout is kept as-is.

Run with `-v` to see the chosen branch logged per repo (`measuring branch 'develop'`).
This applies to `--repo`/`--organization` (cloned repos). **Local-folder mode is left on
its current branch** — the tool won't switch branches in a checkout you handed it.

### One growing spreadsheet

Every run **appends** to the output file rather than overwriting it. Point each run at the
same `--out` (or just rely on the default, which is always the same path) and rows keep
accumulating — profile one org today, another tomorrow, all in one sheet. The header and
the `Sheet2` data dictionary are preserved. At the end the tool prints the **absolute path**
of the file and how many rows it now contains, so you never have to hunt for it:

```
============================================================
✓ Done. Added 35 row(s) this run; the sheet now has 71 total.
📄 Output file: /Users/you/Downloads/codebase_sheet.filled.xlsx
============================================================
```

`vendor.json` keys use internal field names, e.g.:

```json
{
  "dataset_id": "DS-001",
  "vendor_name": "Acme Data",
  "description": "Temporal workflow backend for a media CMS.",
  "quoted_price": 40000,
  "holdout_verification": "Likely Private"
}
```

## How columns map to tools

| Group | Tool | Columns |
|-------|------|---------|
| LOC / language | `scc` | Raw/Logical/Auto-Gen/Dependency LOC, Source Files, Primary Language, Language Distribution |
| Duplication | `jscpd` | Duplication Ratio |
| Git history | `git` | Non-Merge Commits, Unique Contributors |
| Hosting API | GitHub/GitLab/Bitbucket API (or `gh`) | Total PRs/MRs, Reviewed, Fork % |
| File heuristics | — | CI, Deployment Infra, Monitoring, Test Suite, Containerized, README Quality, Issue Tracker |
| Coverage reports | parse `coverage.xml` / `lcov.info` / `coverage-final.json` | Unit test coverage % |
| LLM attribution heuristics | git + file headers | % of code written with LLM (if any) |
| AST/source scan | `ast` + regex | Docstring Ratio, Avg Function Length |

Collectors run concurrently; a failing collector leaves its columns blank and records a
warning rather than aborting the run.

## Column-by-column calculation

Each column maps to the data dictionary (Sheet2) "How to Measure" spec. Below is exactly
what the script does, and where in the code it lives.

### Identification (`runner.py`, `--meta`)

| Column | How it's calculated |
|--------|---------------------|
| **Dataset / Repo Name** | The repo name. In remote modes it's the platform repo/project slug; locally it's the directory name (multi-repo bundle: `"<dir> bundle"`). |
| **# Repos in Dataset** | Count of distinct `.git` roots discovered at/under the target path (`discovery.py`). In `--repo`/`--organization` modes each repo is profiled as its own row, so this is 1. |
| **Originating company** | In `--organization` mode, the org/group name; in `--repo` mode, the repo owner/namespace. Left blank in local mode unless supplied via `--meta`. |
| **Dataset ID, Type, Vendor Name, Description, Quoted Price, Dataset cost per Repo** | Vendor-provided — left blank unless supplied via `--meta`. Not derivable from code. |
| **Public LOC (Qty available in public training corpora)** | In `--repo`/`--organization` mode, derived from the repo's visibility: a **public** repo is openly crawlable, so this equals its Logical LOC; a **private** repo gets `0`. Left blank in local-folder mode (visibility unknown). Override via `--meta`. |
| **Holdout Verification** | Vendor-provided — left blank. It records whether the vendor kept a withheld holdout set (for decontamination checks against The Stack / StarCoder, etc.); there's no reliable repo signal, so the tool doesn't guess. Override via `--meta`. |

### LOC & language — `scc` (`collectors/loc.py`)

A single `scc --by-file --format json` pass per repo feeds all of these. **Data/markup
"languages" (CSV, JSON, YAML, Markdown, XML, TOML, INI, …) are excluded from LOC totals
and language stats** — they are data, not source code (see `DATA_LANGUAGES`).

| Column | How it's calculated |
|--------|---------------------|
| **Raw LOC** | Sum of scc `Lines` (incl. blanks & comments) across code languages, all repos. |
| **Logical LOC** | Sum of scc `Code` (excl. blanks & comments) across code languages, all repos. |
| **Auto-Generated LOC** | scc `Code` of files flagged generated, decided per-file by layered checks: (1) scc's own `Generated`/`Minified` flag; (2) lock files — any `*.lock` plus `package-lock.json`, `pnpm-lock.yaml`, `go.sum`…; (3) generated globs (`*_pb2.py`, `*.pb.go`, `*.min.js`, `*.bundle.js`…); (4) build/generated dirs (`vendor/ node_modules/ dist/ build/ generated/ migrations/ obj/ .cxx/`…); (5) a content scan of the first lines for generated headers (`do not edit`, `@generated`, `code generated by`…). Data/markup files are never counted here. |
| **Dependency dirs LOC** | scc `Code` re-scanned with `--no-ignore` over dependency dirs (`node_modules/`, `vendor/`, `.venv/`, `site-packages/`, `target/`…). `0` when scc ran but no dependency dirs are present; blank only if scc itself is unavailable. |
| **Total Source Files** | Count of files whose extension is in the dictionary's source allowlist (`SOURCE_EXTS`: `.py .js .ts .go .java …` plus `.json .yml .md .txt` config/docs). Broader than code languages by design. |
| **Primary Language** | The code language with the highest `Code` total. |
| **Language Distribution** | Each code language's `Code` as a fraction of total code LOC, listing those ≥ 1%, as a JSON-ish string e.g. `{"Python": 0.97, "Shell": 0.03}`. |

### Duplication — `jscpd` (`collectors/duplication.py`)

| Column | How it's calculated |
|--------|---------------------|
| **Duplication Ratio** | `jscpd --min-tokens 50 --min-lines 5 --reporters json` per repo (ignoring `.git/`, `node_modules/`, `vendor/`, `dist/`, `build/`), taking `statistics.total.percentage / 100`. Reported as the LOC-weighted average across repos. `0.00`–`1.00`. jscpd is run from the repo dir and **retried once** on a hard failure (it can transiently fail under load); a persistent failure logs the exit code/stderr rather than silently blanking the column. An empty branch with no measurable source legitimately yields a blank. |

### Git history — `git` (`collectors/git_history.py`)

| Column | How it's calculated |
|--------|---------------------|
| **Non-Merge Commit Count** | `git log --no-merges` commit count, summed across repos (merge commits excluded as bookkeeping). |
| **Unique Contributors** | Distinct authors from `git log --no-merges` (`%ae`/`%an`), deduplicated by lowercased email (fallback name) across all repos. |

### Hosting API — GitHub/GitLab/Bitbucket (`collectors/vcs_api.py`, `providers/`, skip with `--no-github`)

In remote modes the platform **provider** is queried directly with your token. In local
mode it falls back to the `gh` CLI when the checkout has a GitHub remote. GitHub PR review
data comes from a paged GraphQL query; GitLab from the REST merge-requests endpoint.

| Column | How it's calculated |
|--------|---------------------|
| **Total PR Count** | Count of `MERGED` pull requests (GitHub) / merged merge requests (GitLab). |
| **Reviewed PR Count** | **GitHub:** merged PRs where `reviewDecision` is `APPROVED`/`CHANGES_REQUESTED` or `reviews.totalCount > 0`. **GitLab:** merged MRs with `user_notes_count > 0` (human discussion, excluding system notes). **Bitbucket:** merged PRs with comments or an approval/changes-requested participant. |
| **Fork %** | Fraction of profiled repos that are forks (GitHub `fork` flag / GitLab `forked_from_project` / Bitbucket `parent`). In per-repo remote modes this is `0.0` or `1.0`. |

### Maturity heuristics — file/commit scan (`collectors/infra.py`)

One filesystem walk per repo (skipping `.git`, `node_modules`, `.venv`, …) feeds all of
these. Outputs use the dictionary's exact enum vocabularies.

| Column | How it's calculated |
|--------|---------------------|
| **CI Checks on PRs?** | `Yes` if any CI config exists: `.github/workflows/`, `.circleci/`, `.travis.yml`, `Jenkinsfile`, `.gitlab-ci.yml`, `azure-pipelines.yml`, `.drone.yml`, `bitbucket-pipelines.yml`. |
| **Deployment Infrastructure** | `None` (no CI/IaC) → `Basic CI` (CI present) → `Full CI-CD` (CI contains deploy keywords: `deploy`, `kubectl`, `helm`, `docker push`, `terraform apply`, `argocd`…) → `Enterprise` (deploy keywords **and** IaC: `*.tf`, Helm charts, Kustomize). |
| **Monitoring & Observability** | Scans source for SDK names. `None` → `Basic` (logging only: `logging.getLogger`, `structlog`, `winston`, `log4j`) → `APM+Alerting` (Sentry, Datadog, New Relic, Prometheus, PagerDuty, Honeycomb…) → `Full SRE` (APM **and** distributed tracing: OpenTelemetry, Jaeger, Grafana/Tempo). |
| **Test Suite Presence** | Counts test files (`test_*.py`, `*_test.go`, `*.spec.ts`, `*.test.js`, `*Test.java`). `None` (0) → `Basic` → `Comprehensive` (≥ 20 test files **and** ≥ 2 kinds among unit/integration/e2e, inferred from path). |
| **Unit test coverage %** | Parses committed coverage artifacts (`coverage.xml`, `lcov.info`, `coverage-final.json`, …). Prefers **branch** rate, then **line**, then **function**. LOC-weighted average across repos. Does **not** run tests. Reports `0.0` when no report exists. `0.00`–`1.00`. |
| **Containerized?** | `Yes` if any of `Dockerfile*`, `docker-compose.y*ml`, `.dockerignore`, k8s `deployment.y*ml`, Helm `Chart.yaml`/`values.yaml`. |
| **README Quality** | Grades the root README + extra docs. `None` (missing/empty) → `Basic` (short) → `Detailed` (has setup/usage **and** architecture sections, or > 1500 chars) → `Comprehensive` (Detailed **plus** `CONTRIBUTING.md`, `docs/`, `rfcs/`, or ADRs). Best tier across repos. |
| **Issue Tracker** | `None` → `Basic` (issue templates present) → `Linked to Commits` (recent commit messages reference issues, e.g. `#123`, `JIRA-456`) → `Full+Design Docs` (linked **and** design docs under `docs/`/`rfcs/`/`adr/`). |

### Code quality — AST + regex (`collectors/codeanalysis.py`)

Python is analysed accurately with the stdlib `ast` module; other languages
(JS/TS/Go/Java/Rust/C-family/Kotlin/Scala) use a brace/heuristic scan. Both metrics are
weighted by function count across all files.

| Column | How it's calculated |
|--------|---------------------|
| **Docstring Ratio** | (functions/methods/classes with a docstring or doc-comment) ÷ (total functions/methods/classes). Python: `ast.get_docstring`; C-style/JS: a `/** … */`, `///`, or `//!` block immediately above the declaration. `0.00`–`1.00`. |
| **Avg Function Length** | Mean lines per function. Python: `end_lineno − lineno + 1` from the AST; C-style/JS: brace-matched span from the opening `{`. |

### LLM attribution — heuristics (`collectors/llm_attribution.py`)

| Column | How it's calculated |
|--------|---------------------|
| **(if any) % of code written with LLM** | Heuristic only — reports `0.0` when no signal. **Primary:** source files whose headers contain AI-generation markers count fully toward the numerator; denominator is non-comment source lines in those files' extensions. **Fallback:** git history — lines added/deleted in commits whose message/body matches `Co-authored-by: Cursor/Copilot/…` or similar AI markers; denominator is total churn in non-merge commits. Override via `--meta` (`llm_written_pct`). `0.00`–`1.00`. |
