# Repo Eval Kit

A comprehensive toolkit for evaluating the quality, health, and suitability of GitHub, GitLab, and Bitbucket repositories. Analyze a **single repository** or **all repositories** across every organization/group/workspace your token has access to — in one command.

---

## Table of Contents

- [Repo Eval Kit](#repo-eval-kit)
  - [Table of Contents](#table-of-contents)
  - [Overview](#overview)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
  - [Creating Access Tokens](#creating-access-tokens)
    - [GitHub Token](#github-token)
    - [GitLab Token](#gitlab-token)
    - [Bitbucket Token](#bitbucket-token)
  - [Configuration (.env File)](#configuration-env-file)
  - [Script 1: `repo_evaluator.py` — Evaluate a Single Repository](#script-1-repo_evaluatorpy--evaluate-a-single-repository)
    - [What It Does](#what-it-does)
    - [Usage](#usage)
    - [CLI Arguments](#cli-arguments)
    - [Examples](#examples)
    - [Output](#output)
  - [Script 2: `run_all_repos.py` — Evaluate All Repositories You Have Access To](#script-2-run_all_repospy--evaluate-all-repositories-you-have-access-to)
    - [What It Does](#what-it-does-1)
    - [Two Modes](#two-modes)
    - [Usage](#usage-1)
    - [CLI Arguments](#cli-arguments-1)
    - [Environment Variables](#environment-variables)
    - [Examples](#examples-1)
    - [Output Structure](#output-structure)
  - [End-to-End Walkthrough](#end-to-end-walkthrough)
    - [Scenario A: Evaluate a single repo](#scenario-a-evaluate-a-single-repo)
    - [Scenario B: See every repo you can access (dry run)](#scenario-b-see-every-repo-you-can-access-dry-run)
    - [Scenario C: Evaluate all repos in your organization](#scenario-c-evaluate-all-repos-in-your-organization)
  - [What Gets Evaluated?](#what-gets-evaluated)
    - [Repository-Level Metrics](#repository-level-metrics)
    - [PR-Level Analysis](#pr-level-analysis)
    - [Supported Languages](#supported-languages)
    - [Supported Platforms](#supported-platforms)
  - [Utility Scripts](#utility-scripts)
  - [Troubleshooting](#troubleshooting)
    - ["No GitHub token provided"](#no-github-token-provided)
    - ["API rate limit exceeded"](#api-rate-limit-exceeded)
    - ["No repos found" in `run_all_repos.py`](#no-repos-found-in-run_all_repospy)
    - ["F2P analysis skipped"](#f2p-analysis-skipped)
    - [GitLab: "insufficient\_granular\_scope"](#gitlab-insufficient_granular_scope)
    - [Bitbucket: "Failed to authenticate" or 401 errors](#bitbucket-failed-to-authenticate-or-401-errors)
    - [Bitbucket: "No repos found"](#bitbucket-no-repos-found)
    - [Slow evaluations](#slow-evaluations)

---

## Overview

| Script                          | Purpose                                                                                                                                       |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| **`repo_evaluator.py`** | Deep-dive evaluation of a**single** repository (repo metrics, PR analysis, F2P tests, quality checks, taxonomy classification).         |
| **`run_all_repos.py`**  | Discovers**all** organizations/groups/workspaces and repos your token can see, then runs `repo_evaluator.py` on each one in parallel. |

Think of `run_all_repos.py` as the **orchestrator** and `repo_evaluator.py` as the **worker**.

---

## Prerequisites

- **Python 3.10+**
- **Git** installed and available on your `$PATH`
- A **Personal Access Token** for GitHub, GitLab, or Bitbucket (see [Creating Access Tokens](#creating-access-tokens))
- *(Optional)* An **OpenAI API key** if you want LLM-powered quality checks, PR rubrics, and taxonomy classification

---

## Installation

```bash
# 1. Clone this repository
git clone <repo-url>
cd repo-eval-kit

# 2. Create and activate a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows

# 3. Install dependencies
pip install -r requirements.txt
```

---

## Creating Access Tokens

### GitHub Token

1. Go to **[GitHub → Settings → Developer Settings → Personal Access Tokens → Fine-grained tokens](https://github.com/settings/tokens?type=beta)** (or classic tokens).
2. Click **Generate new token**.
3. Required scopes (classic token):
   - `repo` (full access to private repos)
   - `read:org` (read org membership)
4. Copy the token — it starts with `ghp_`.

### GitLab Token

1. Go to **[GitLab → Settings → Access Tokens](https://gitlab.com/-/user_settings/personal_access_tokens)** (or your self-hosted GitLab → Settings → Access Tokens).
2. Create a token with these scopes:
   - ✅ `read_api`
   - ✅ `read_repository`
   - ✅ `read_user` *(recommended)*
3. Copy the token — it starts with `glpat-`.

### Bitbucket Token

Bitbucket Cloud supports **App Passwords** (legacy) and **API tokens** (recommended). Both use HTTP Basic auth.

1. Go to **[Bitbucket → Personal settings → App passwords](https://bitbucket.org/account/settings/app-passwords/)** (app password) or create an **API token** from your Atlassian account.
2. Required scopes:
   - ✅ Account (Read)
   - ✅ Repositories (Read)
   - ✅ Workspace membership (Read)
3. You also need your **Bitbucket username** (app passwords) or **Atlassian account email** (API tokens) for Basic auth.

> **Auth note:** App passwords use `BITBUCKET_USERNAME=<bitbucket_username>`. API tokens use `BITBUCKET_EMAIL=<your-atlassian-email>` (or `BITBUCKET_USERNAME` with the same email).

---

## Configuration (.env File)

Create a `.env` file in the project root to avoid passing tokens on every command:

```dotenv
# ── Platform Tokens ──────────────────────────────────────
GITHUB_TOKEN=ghp_YourGitHubTokenHere
GITLAB_TOKEN=glpat-YourGitLabTokenHere
BITBUCKET_TOKEN=YourBitbucketAppPasswordOrApiToken
BITBUCKET_USERNAME=your-bitbucket-username   # app passwords
# BITBUCKET_EMAIL=you@example.com            # API tokens

# ── GitLab self-hosted (optional) ────────────────────────
# GITLAB_URL=https://gitlab.mycompany.com

# ── run_all_repos platform (optional) ────────────────────
# EVAL_PLATFORM=bitbucket

# ── OpenAI (optional — for LLM quality checks) ──────────
# OPENAI_API_KEY=sk-YourOpenAIKeyHere
```

> **Configuration priority** (highest → lowest):
>
> 1. CLI argument (`--token ghp_xxx`)
> 2. Environment variable (`export GITHUB_TOKEN=ghp_xxx`)
> 3. `.env` file (`GITHUB_TOKEN=ghp_xxx`)
> 4. Built-in default

---

## Script 1: `repo_evaluator.py` — Evaluate a Single Repository

### What It Does

Performs a deep analysis of one repository by:

| Category                              | What's Checked                                                                                                                         |
| ------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| **Repository Metrics**          | Total files, source/test files & LOC, language detection, CI/CD pipelines, test frameworks                                             |
| **Git History Analysis**        | Total commits, commit spread, contributor count, commit message quality, code churn rate, branch count                                 |
| **PR Analysis**                 | Iterates over merged PRs — filters by bot PRs, language, test presence, code changes, issue linkage. Produces an acceptance rate.     |
| **Feature PR Classification**   | Heuristic scoring to identify "feature" PRs vs. bug fixes/chores                                                                       |
| **F2P / P2P Test Verification** | *(Optional)* Runs actual test suites at base & head commits to verify fail-to-pass (F2P) and pass-to-pass (P2P) behavior             |
| **PR Rubrics**                  | *(Optional, needs OpenAI key)* LLM-based scoring of issue clarity, patch clarity, test clarity, alignment, false positives/negatives |
| **Quality Checks**              | *(Optional, needs OpenAI key)* Vibe-coding detection, security analysis, production-quality analysis                                 |
| **Taxonomy Classification**     | *(Optional, needs OpenAI key)* Classifies each PR by domain, archetype, complexity, horizon, and more                                |
| **Open Source Detection**       | Scores likelihood that the repo is open-source (license files, README keywords, manifest licenses)                                     |
| **AI Risk Detection**           | Scores likelihood of AI-generated code (explicit markers, generic commits, low-test-ratio patterns)                                    |

### Usage

```bash
python repo_evaluator.py <owner/repo> [OPTIONS]
```

### CLI Arguments

| Argument                  | Description                                                              | Default               |
| ------------------------- | ------------------------------------------------------------------------ | --------------------- |
| `repo`                  | Repository in`owner/repo-name` format (positional, **required**) | —                    |
| `--token`               | Platform access token (GitHub / GitLab / Bitbucket)                      | `None`              |
| `--platform`            | `auto`, `github`, `gitlab`, or `bitbucket`                       | `auto`              |
| `--repo-path`           | Path to a local clone (skips auto-clone)                                 | `None` (auto-clone) |
| `--json`                | Output results as JSON                                                   | `False`             |
| `--output`              | Write JSON output to this file path                                      | `None`              |
| `--max-prs`             | Maximum number of PRs to analyze                                         | `None` (all)        |
| `--start-date`          | Only analyze PRs merged on/after this date (`YYYY-MM-DD`)              | `None`              |
| `--pr-number`           | Evaluate only this specific PR number                                    | `None`              |
| `--min-test-files`      | Minimum test files required per PR                                       | `1`                 |
| `--max-non-test-files`  | Maximum non-test files allowed per PR                                    | `100`               |
| `--min-code-changes`    | Minimum code changes per PR                                              | `1`                 |
| `--skip-f2p`            | Skip F2P/P2P test verification                                           | `False`             |
| `--f2p-timeout`         | Timeout for F2P test execution per PR (seconds)                          | `600`               |
| `--skip-quality-checks` | Skip vibecode, security, and production quality checks                   | `False`             |
| `--skip-quality-llm`    | Skip LLM analysis in quality checks (static-only)                        | `False`             |
| `--skip-taxonomy`       | Skip taxonomy classification                                             | `False`             |
| `--skip-pr-rubrics`     | Skip LLM-based PR rubrics                                                | `False`             |
| `--pr-rubrics-provider` | LLM provider for PR rubrics:`openai` or `gemini`                     | `openai`            |
| `--taxonomy-model`      | Model for taxonomy classification                                        | `gpt-4o`            |

### Examples

```bash
# Basic evaluation of a public repo (no token needed, but rate limits apply)
python repo_evaluator.py microsoft/vscode

# Evaluate a private GitHub repo with a token and JSON output
python repo_evaluator.py my-org/my-private-repo \
  --token ghp_xxx \
  --json \
  --output results/my-repo.json

# Evaluate a GitLab repo
python repo_evaluator.py gitlab:my-group/my-project \
  --token glpat-xxx \
  --platform gitlab \
  --json

# Fast evaluation — skip heavy analysis steps
python repo_evaluator.py owner/repo \
  --token ghp_xxx \
  --skip-f2p \
  --skip-quality-checks \
  --skip-taxonomy \
  --skip-pr-rubrics \
  --json

# Evaluate only PRs from the last year, max 50
python repo_evaluator.py owner/repo \
  --token ghp_xxx \
  --start-date 2025-04-01 \
  --max-prs 50 \
  --json

# Evaluate a single PR
python repo_evaluator.py owner/repo \
  --token ghp_xxx \
  --pr-number 123 \
  --json

# Evaluate a local clone (no cloning needed)
python repo_evaluator.py owner/repo \
  --token ghp_xxx \
  --repo-path /path/to/local/clone \
  --json
```

### Output

For each evaluated repository, two files are generated:

| File            | Content                                                                                                |
| --------------- | ------------------------------------------------------------------------------------------------------ |
| `<repo>.json` | Complete evaluation report (repo metrics, PR analysis, F2P results, quality checks, taxonomy, rubrics) |
| `<repo>.csv`  | Single-row CSV with all metrics flattened — ready for spreadsheets or data pipelines                  |

**Key fields in the JSON output:**

```
repo_metrics.primary_language        — Detected primary language
repo_metrics.total_commits           — Total commits in git history
repo_metrics.source_files / test_files — File counts
repo_metrics.source_loc / test_loc   — Lines of code
repo_metrics.has_ci_cd               — CI/CD pipeline found
repo_metrics.ai_risk_level           — "low" / "medium" / "high"
repo_metrics.open_source_likelihood  — "low" / "medium" / "high"
pr_analysis.total_prs                — Total merged PRs analyzed
pr_analysis.pass_first_filter        — PRs that passed all quality filters
pr_analysis.pass_first_filter_rate   — Acceptance rate (0.0–1.0)
```

---

## Script 2: `run_all_repos.py` — Evaluate All Repositories You Have Access To

### What It Does

1. **Authenticates** with GitHub, GitLab, or Bitbucket using your token.
2. **Discovers** all organizations (GitHub), groups (GitLab), or workspaces (Bitbucket) you belong to.
3. **Lists** every repository in those organizations/groups/workspaces.
4. **Filters** repos by visibility, archived status, forks, and exclusion lists.
5. Optionally **runs `repo_evaluator.py`** on every discovered repo in parallel.

### Two Modes

| Mode          | What Happens                                                                                                                              |
| ------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `--dry-run` | Lists all orgs/groups/workspaces and their repos.**No evaluation is performed.** Use this first to see what the tool will evaluate. |
| `--run`     | Discovers repos*and* runs `repo_evaluator.py` on each one.                                                                            |

### Usage

```bash
python run_all_repos.py --dry-run [OPTIONS]    # Preview mode
python run_all_repos.py --run    [OPTIONS]    # Execute mode
```

### CLI Arguments

| Argument                  | Description                                                      | Default                          |
| ------------------------- | ---------------------------------------------------------------- | -------------------------------- |
| `--dry-run`             | List repos only — do not evaluate                               | *(required, or `--run`)*     |
| `--run`                 | Discover and evaluate all repos                                  | *(required, or `--dry-run`)* |
| **Platform & Auth** |                                                                  |                                  |
| `--platform`            | `github`, `gitlab`, or `bitbucket`                         | `github`                       |
| `--token`               | Personal Access Token                                            | env var                          |
| `--gitlab-url`          | GitLab instance URL (self-hosted)                                | `https://gitlab.com`           |
| `--bitbucket-username`  | Bitbucket username (app password) or Atlassian email (API token) | env var                          |
| **Filtering**       |                                                                  |                                  |
| `--org`                 | Only include these org(s)/group(s)/workspace(s) — repeatable    | all orgs                         |
| `--exclude-org`         | Exclude org(s)/group(s)/workspace(s) — repeatable               | none                             |
| `--exclude-repo`        | Exclude repos by`owner/repo` — repeatable                     | none                             |
| `--include-user-repos`  | Also include personal/owned repos                                | `False`                        |
| `--include-archived`    | Include archived repos                                           | `False`                        |
| `--include-forks`       | Include forked repos                                             | `False`                        |
| `--visibility`          | `all`, `public`, or `private`                              | `all`                          |
| **Execution**       |                                                                  |                                  |
| `--workers`             | Number of parallel workers                                       | `4`                            |
| `--fail-fast`           | Stop on first failure                                            | `False`                        |
| `--output-dir`          | Directory for results                                            | `eval_results`                 |
| `--evaluator-script`    | Path to`repo_evaluator.py`                                     | `repo_evaluator.py`            |
| `--evaluator-args`      | Extra flags passed to`repo_evaluator.py`                       | none                             |
| **Output**          |                                                                  |                                  |
| `--save-inventory`      | Save the repo inventory to a JSON file                           | none                             |

### Environment Variables

All CLI arguments have corresponding environment variables. This is useful for CI/CD pipelines or `.env` file configuration:

| Env Variable                                 | Maps To                     | Example                              |
| -------------------------------------------- | --------------------------- | ------------------------------------ |
| `GITHUB_TOKEN` / `GH_TOKEN`              | `--token` (GitHub)        | `ghp_xxx`                          |
| `GITLAB_TOKEN` / `GL_TOKEN`              | `--token` (GitLab)        | `glpat-xxx`                        |
| `GITLAB_URL`                               | `--gitlab-url`            | `https://gitlab.mycompany.com`     |
| `BITBUCKET_TOKEN` / `BB_TOKEN`           | `--token` (Bitbucket)     | app password or API token            |
| `BITBUCKET_USERNAME` / `BITBUCKET_EMAIL` | `--bitbucket-username`    | `my-user` or `you@example.com`   |
| `OPENAI_API_KEY`                           | Passed through to evaluator | `sk-xxx`                           |
| `EVAL_PLATFORM`                            | `--platform`              | `github`                           |
| `EVAL_ORGS`                                | `--org`                   | `my-org,other-org`                 |
| `EVAL_EXCLUDE_ORGS`                        | `--exclude-org`           | `archived-org`                     |
| `EVAL_EXCLUDE_REPOS`                       | `--exclude-repo`          | `org/old-repo,org/test-repo`       |
| `EVAL_INCLUDE_USER`                        | `--include-user-repos`    | `true`                             |
| `EVAL_INCLUDE_ARCHIVED`                    | `--include-archived`      | `true`                             |
| `EVAL_INCLUDE_FORKS`                       | `--include-forks`         | `true`                             |
| `EVAL_VISIBILITY`                          | `--visibility`            | `private`                          |
| `EVAL_WORKERS`                             | `--workers`               | `8`                                |
| `EVAL_OUTPUT_DIR`                          | `--output-dir`            | `my_results`                       |
| `EVAL_EVALUATOR_SCRIPT`                    | `--evaluator-script`      | `repo_evaluator.py`                |
| `EVAL_EVALUATOR_ARGS`                      | `--evaluator-args`        | `--skip-f2p --skip-quality-checks` |

### Examples

```bash
# ── GitHub ────────────────────────────────────────────────

# Step 1: Preview — see all repos your token can access
python run_all_repos.py --dry-run --token ghp_xxx

# Step 2: Evaluate everything (using token from .env file)
python run_all_repos.py --run

# Evaluate only one specific organization with 8 workers
python run_all_repos.py --run --org my-company --workers 8

# Evaluate only private repos, skip heavy analysis
python run_all_repos.py --run \
  --visibility private \
  --evaluator-args "--skip-f2p --skip-quality-checks --skip-taxonomy"

# Exclude some repos and include personal repos
python run_all_repos.py --run \
  --exclude-repo my-org/legacy-app \
  --exclude-repo my-org/test-sandbox \
  --include-user-repos

# Save the repo inventory for later reference
python run_all_repos.py --dry-run \
  --save-inventory inventory.json

# ── GitLab ────────────────────────────────────────────────

# Preview all GitLab groups and projects
python run_all_repos.py --platform gitlab --dry-run --token glpat-xxx

# Evaluate all GitLab projects in a specific group
python run_all_repos.py --platform gitlab --run --org my-group

# Self-hosted GitLab
python run_all_repos.py --platform gitlab --run \
  --gitlab-url https://gitlab.mycompany.com \
  --token glpat-xxx

# ── Bitbucket ───────────────────────────────────────────

# Preview all Bitbucket workspaces and repos
python run_all_repos.py --platform bitbucket --dry-run \
  --token <app-password-or-api-token> \
  --bitbucket-username <username-or-email>

# Evaluate all repos in one workspace
python run_all_repos.py --platform bitbucket --run \
  --org my-workspace \
  --workers 8

# Using .env (recommended)
# BITBUCKET_TOKEN=...
# BITBUCKET_USERNAME=...
# EVAL_PLATFORM=bitbucket
python run_all_repos.py --dry-run
python run_all_repos.py --run --org my-workspace
```

### Output Structure

When run with `--run`, the output is organized by org/group/workspace and repo:

```
eval_results/                         ← --output-dir (default: eval_results)
├── _summary.json                     ← Overall run summary (counts, timing, failures)
├── my-org/                           ← Organization / group name
│   ├── backend-api/
│   │   ├── backend-api.json          ← Full evaluation report
│   │   └── backend-api.csv           ← Flattened single-row CSV
│   ├── frontend-app/
│   │   ├── frontend-app.json
│   │   └── frontend-app.csv
│   └── ...
├── other-org/
│   └── ...
└── user/                             ← Personal repos (if --include-user-repos)
    └── ...
```

**`_summary.json`** contains:

```json
{
  "timestamp": "2026-04-07T12:00:00+00:00",
  "total": 42,
  "succeeded": 40,
  "failed": 2,
  "total_seconds": 1234.5,
  "results": [
    { "repo": "my-org/backend-api", "exit_code": 0, "duration_seconds": 45.2 },
    { "repo": "my-org/legacy-app", "exit_code": 1, "error": "..." }
  ]
}
```

---

## End-to-End Walkthrough

### Scenario A: Evaluate a single repo

```bash
# 1. Set up your token
echo "GITHUB_TOKEN=ghp_YourToken" > .env

# 2. Run the evaluator
python repo_evaluator.py my-org/my-repo --json --output results/my-repo.json

# 3. Check the results
cat results/my-repo.json | python -m json.tool
```

### Scenario B: See every repo you can access (dry run)

```bash
# 1. Set up your token
echo "GITHUB_TOKEN=ghp_YourToken" > .env

# 2. Run dry-run to see the inventory
python run_all_repos.py --dry-run

# Output:
# ======================================================================
#   📋  REPOSITORY INVENTORY [GITHUB] — 47 repo(s) across 3 org(s)
# ======================================================================
#   🏢 my-org  (25 repos)
#   ────────────────────────────────────────
#     • my-org/backend-api  [🔒 private, Python]
#     • my-org/frontend-app  [🔒 private, TypeScript]
#     ...
```

### Scenario C: Evaluate all repos in your organization

```bash
# 1. Set up .env
cat > .env << 'EOF'
GITHUB_TOKEN=ghp_YourToken
OPENAI_API_KEY=sk-YourOpenAIKey
EOF

# 2. Preview first
python run_all_repos.py --dry-run --org my-company

# 3. Run full evaluation (fast mode — skip heavy LLM steps)
python run_all_repos.py --run \
  --org my-company \
  --workers 4 \
  --evaluator-args "--skip-f2p --skip-quality-checks --skip-taxonomy --skip-pr-rubrics"

# 4. Consolidate all CSVs into a single spreadsheet
python consolidate_output.py
```

---

## What Gets Evaluated?

Here's a summary of every metric and check performed by `repo_evaluator.py`:

### Repository-Level Metrics

| Metric                            | Description                                                                         |
| --------------------------------- | ----------------------------------------------------------------------------------- |
| `total_files`                   | Total files in the repo                                                             |
| `source_files` / `test_files` | Source and test file counts                                                         |
| `source_loc` / `test_loc`     | Lines of code (source vs. test)                                                     |
| `primary_language`              | Detected primary programming language                                               |
| `has_ci_cd`                     | Whether CI/CD config files exist (GitHub Actions, GitLab CI, Travis, Jenkins, etc.) |
| `test_frameworks`               | Detected test frameworks (pytest, jest, junit, etc.)                                |
| `total_commits`                 | Total commit count                                                                  |
| `recent_commits_6mo` / `12mo` | Commits in last 6 / 12 months                                                       |
| `repo_age_days`                 | Days between first and latest commit                                                |
| `contributors_total`            | Number of unique contributors                                                       |
| `commit_spread_ratio`           | Unique commit days / repo age                                                       |
| `first_commit_loc`              | LOC changed in the very first commit                                                |
| `single_commit_loc_share`       | Largest commit as a fraction of total LOC                                           |
| `avg_loc_per_commit`            | Average LOC changed per commit                                                      |
| `branch_count`                  | Number of branches                                                                  |
| `code_churn_rate`               | Files touched ≥2 times / total files touched                                       |
| `comment_density`               | Comment lines / code lines                                                          |
| `open_source_likelihood`        | `low` / `medium` / `high` (based on LICENSE files, keywords)                  |
| `ai_risk_level`                 | `low` / `medium` / `high` (based on AI markers, generic commits)              |

### PR-Level Analysis

| Metric                     | Description                              |
| -------------------------- | ---------------------------------------- |
| `total_prs`              | Total merged PRs analyzed                |
| `pass_first_filter`      | PRs that passed all quality filters      |
| `pass_first_filter_rate` | Acceptance rate                          |
| `avg_loc_per_pr`         | Average LOC changed per PR               |
| `issue_linked_pr_ratio`  | PRs linked to issues / total PRs         |
| `feature_prs`            | Count of PRs classified as "feature" PRs |

### Supported Languages

Python, JavaScript, TypeScript, Java, Scala, Go, Rust, Ruby, PHP, C#, Swift, Kotlin, C, C++, COBOL.

### Supported Platforms

- **GitHub** (cloud)
- **GitLab** (cloud & self-hosted)
- **Bitbucket** (cloud)

---

## Utility Scripts

| Script                              | Description                                                                                 |
| ----------------------------------- | ------------------------------------------------------------------------------------------- |
| `consolidate_output.py`           | Combines all per-repo CSV files in the`output/` directory into a single `combined.csv`. |
| `transpose_csv.py`                | Transposes a CSV for easier reading.                                                        |
| `bulk_repo_evaluator_parallel.py` | Alternative bulk evaluator for a hardcoded list of repos.                                   |

---

## Troubleshooting

### "No GitHub token provided"

Set your token via **any** of these (highest priority first):

1. `--token ghp_xxx` on the CLI
2. `export GITHUB_TOKEN=ghp_xxx` in your shell
3. `GITHUB_TOKEN=ghp_xxx` in a `.env` file

### "API rate limit exceeded"

- Always provide a `--token` — unauthenticated GitHub requests are limited to 60/hour.
- Authenticated requests get 5,000/hour.
- The tool automatically waits and retries when rate-limited.

### "No repos found" in `run_all_repos.py`

- Your token may not have `read:org` scope — check your token permissions.
- Try adding `--include-user-repos` to include your personal repos.
- Use `--visibility all` (the default) to see both public and private repos.

### "F2P analysis skipped"

- F2P requires the project's test runner to be installed and working locally.
- Use `--skip-f2p` to skip this step if you don't need it.

### GitLab: "insufficient_granular_scope"

Your token needs these scopes: `read_user`, `read_api`, `read_repository`. Recreate your token at [GitLab → Access Tokens](https://gitlab.com/-/user_settings/personal_access_tokens).

### Bitbucket: "Failed to authenticate" or 401 errors

- App passwords and API tokens require **Basic auth**, not Bearer-only.
- Set `BITBUCKET_USERNAME` to your **Bitbucket username** (app password) or `BITBUCKET_EMAIL` to your **Atlassian account email** (API token).
- Pass `--bitbucket-username` on the CLI if not using `.env`.
- Ensure the token has **Account (Read)**, **Repositories (Read)**, and **Workspace membership (Read)** scopes.

### Bitbucket: "No repos found"

- Your token may only have access to specific workspaces — try `--org <workspace-slug>`.
- Use `--include-user-repos` to include personal/member repos outside workspaces.
- Confirm you are a **member** of the workspace, not just viewing public repos.

### Slow evaluations

Speed things up by skipping optional heavy steps:

```bash
--evaluator-args "--skip-f2p --skip-quality-checks --skip-taxonomy --skip-pr-rubrics"
```

---
