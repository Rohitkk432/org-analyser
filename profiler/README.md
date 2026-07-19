# codebase_profiler

Auto-fills the vendor **codebase intake sheet** (`codebase_sheet.xlsx`) by running
measurement tools over a repository. It computes every column derivable from code,
git history, and a hosting-platform API, leaving true vendor fields (price, vendor
name, holdout verification) blank or supplied via `--meta`.

Three modes:

- **Local** — point at a folder already on disk.
- **Single remote repo** (`--repo`) — clone one GitHub/GitLab/Bitbucket repo, write one row.
- **Whole organization** (`--organization`) — clone every repo under a GitHub org,
  GitLab group, or Bitbucket workspace/project, one row each.

## Requirements

| Tool | Why |
|------|-----|
| `git` | Cloning repos, reading history |
| `scc` | LOC / language / file counts |
| Node.js + `jscpd` | Duplication ratio (optional — skipped if absent) |

```bash
brew install git scc node && npm install -g jscpd   # macOS
```

Or use Docker (no local tool install): see [`run.sh`](./run.sh) — `./run.sh --repo owner/name`.

Install this project from the repo root (not from `profiler/`):

```bash
cd ~/Coding/org-analyser
pip install -e .   # or: uv venv && uv pip install .
```

## Authentication

Remote modes need an API token, resolved in this order: `--token`, then env vars
(`GITHUB_TOKEN`/`GH_TOKEN`, `GITLAB_TOKEN`, `BITBUCKET_TOKEN`), then (GitHub only)
your `gh auth login` session. Tokens are used in memory only, never written to
disk or printed.

Bitbucket has three token types with different auth requirements:

| Token type | Env vars |
|------------|----------|
| Atlassian API token (`ATATT…`) | `ATLASSIAN_EMAIL` + `BITBUCKET_TOKEN` |
| App password | `BITBUCKET_USERNAME` + `BITBUCKET_TOKEN` |
| Workspace/repo access token | `BITBUCKET_TOKEN` only |

## Usage

```bash
# Local folder
codebase-profiler ~/Coding/example-project

# One remote repo (platform inferred from a URL, else --platform)
codebase-profiler --repo your-org/example-repo
codebase-profiler --repo your-workspace/example-repo --platform bitbucket

# Whole org/group/workspace
codebase-profiler --organization your-org --out ~/Downloads/your-org.xlsx
codebase-profiler --organization your-group --platform gitlab --limit 10

# Self-managed host
codebase-profiler --organization team --platform gitlab --host gitlab.acme.com

# Vendor fields applied to every row
codebase-profiler --repo your-org/example-repo --meta vendor.json
```

### Key flags

| Flag | Purpose |
|------|---------|
| `path` (positional) | Local folder to profile |
| `--repo OWNER/NAME\|URL` | Clone & profile one remote repo |
| `--organization ORG` | Clone & profile every repo under an org/group/workspace |
| `--platform github\|gitlab\|bitbucket` | Default `github`, inferred from a URL |
| `--host HOST` | Self-managed GitHub Enterprise / GitLab host |
| `--token TOKEN` | API token (else env vars above) |
| `--limit N` | Org mode: only the first N repos |
| `--out FILE` | Output xlsx (appended if it already exists) |
| `--no-github` | Skip all PR/MR & fork API calls |
| `--meta FILE` | JSON of vendor fields applied to every row |

Remote repos are full-cloned into `~/.cache/codebase_profiler/clones` (override with
`--workdir`); an already-cloned repo is fetched, not re-cloned.

Remote clones measure the most recently committed long-lived branch (`main`,
`develop`, `release/*`, etc.), not necessarily the default branch — avoids being
skewed by an abandoned `master`. Local-folder mode stays on its current branch.

Every run **appends** to the output file rather than overwriting it, so you can
profile one org today and another tomorrow into the same sheet.

## How columns map to tools

| Group | Tool | Columns |
|-------|------|---------|
| LOC / language | `scc` | Raw/Logical/Auto-Gen/Dependency LOC, Source Files, Primary Language, Language Distribution |
| Duplication | `jscpd` | Duplication Ratio |
| Git history | `git` | Non-Merge Commits, Unique Contributors |
| Hosting API | GitHub/GitLab/Bitbucket API (or `gh`) | Total PRs/MRs, Reviewed, Fork % |
| File heuristics | — | CI, Deployment Infra, Monitoring, Test Suite, Containerized, README Quality, Issue Tracker |
| Coverage reports | `coverage.xml` / `lcov.info` / `coverage-final.json` | Unit test coverage % |
| LLM attribution heuristics | git + file headers | % of code written with LLM (if any) |
| AST/source scan | `ast` + regex | Docstring Ratio, Avg Function Length |

Collectors run concurrently; a failing collector leaves its columns blank and logs
a warning rather than aborting the run. Exact per-column logic lives in
`collectors/*.py`, one file per group above.
