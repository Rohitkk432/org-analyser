# Repo Eval Kit

Evaluates the quality, health, and suitability of GitHub, GitLab, Bitbucket, SVN,
or local repositories — one repo at a time, or every repo your token can see.

| Script | Purpose |
| --- | --- |
| `repo_evaluator.py` | Deep-dive evaluation of a **single** repository. |
| `run_all_repos.py` | Discovers every org/group/workspace your token can see, then runs `repo_evaluator.py` on each in parallel. |

## Setup

Installed as part of the repo-root install (not standalone):

```bash
cd ~/Coding/org-analyser
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[ui]"
```

### Tokens

| Platform | Where to create | Scopes | Env var |
| --- | --- | --- | --- |
| GitHub | [Settings → Developer settings → Tokens](https://github.com/settings/tokens) | `repo`, `read:org` | `GITHUB_TOKEN` |
| GitLab | [Settings → Access Tokens](https://gitlab.com/-/user_settings/personal_access_tokens) | `read_api`, `read_repository`, `read_user` | `GITLAB_TOKEN` |
| Bitbucket | Personal settings → App passwords, or an Atlassian API token | Account/Repositories/Workspace (Read) | `BITBUCKET_TOKEN` + `BITBUCKET_USERNAME` (app password) or `BITBUCKET_EMAIL` (API token) |
| SVN | Ask your admin | — | `SVN_USERNAME` + `SVN_PASSWORD` (or `--svn-username`/`--token`) |
| OpenAI (optional) | [platform.openai.com](https://platform.openai.com/api-keys) | — | `OPENAI_API_KEY` — enables PR rubrics, quality checks, taxonomy classification |

Put these in a `.env` file in `eval/` (or export them). CLI flag > env var > `.env` > default.

## Evaluate one repo

```bash
repo-evaluator owner/repo --token ghp_xxx --json --output results.json

# GitLab
repo-evaluator gitlab:group/repo --platform gitlab --token glpat-xxx --json

# Bitbucket
repo-evaluator my-workspace/repo --platform bitbucket --token xxx --json

# SVN
repo-evaluator https://svn.example.com/proj/trunk --platform svn \
  --svn-username USER --token PASS --json

# Local folder (no token needed)
repo-evaluator ~/projects/my-app --json

# Faster (skip the heavy/LLM steps)
repo-evaluator owner/repo --json --skip-f2p --skip-quality-checks --skip-taxonomy --skip-pr-rubrics
```

Produces `<repo>.json` (full report) and `<repo>.csv` (flattened, one row).

Key flags: `--max-prs`, `--start-date YYYY-MM-DD`, `--pr-number N`, `--repo-path DIR`
(use an existing local clone instead of cloning), `--pr-rubrics-provider openai|gemini`.
Run `repo-evaluator --help` for the full list.

## Evaluate every repo you can see

```bash
run-all-repos --dry-run                 # preview only, no evaluation
run-all-repos --run                     # evaluate everything
run-all-repos --run --org my-org --workers 8
run-all-repos --platform gitlab --run --gitlab-url https://gitlab.mycompany.com
run-all-repos --platform bitbucket --run --bitbucket-username you

# Faster, for large orgs
run-all-repos --run --evaluator-args "--skip-f2p --skip-quality-checks --skip-taxonomy --skip-pr-rubrics"

# Combine all resulting CSVs into one spreadsheet
consolidate-eval-output
```

Filters: `--exclude-org`, `--exclude-repo`, `--include-user-repos`, `--include-archived`,
`--include-forks`, `--visibility all|public|private`. Every flag has an `EVAL_*` env var
equivalent (see `run_all_repos.py --help`).

Output lands under `eval_results/<org>/<repo>/<repo>.{json,csv}`, plus a `_summary.json`
with counts, timing, and failures.

## Bulk SVN

```bash
# svn_urls.txt: one URL per line, optional |revision suffix
bulk-svn-evaluator --urls-file svn_urls.txt --workers 4 --svn-username USER --token PASS
```

## Cybersecurity PR scanner

Heuristic + optional LLM scoring of PRs for security relevance:

```bash
python -m eval.cybersecurity_pr_scanner --repo owner/name --token "$GITHUB_TOKEN" --json-out out.json
python -m eval.cybersecurity_pr_scanner --repo owner/name --skip-layer2   # heuristics only, no OpenAI
```

## Streamlit UI

Browser UI to pick repos and run the evaluator or scanner without hand-typing commands:

```bash
streamlit run eval/ui/github_eval_picker.py
```

## Troubleshooting

| Problem | Fix |
| --- | --- |
| No token provided | Set `--token`, or the platform's env var, or `.env` |
| API rate limit exceeded | Provide a token (unauthenticated GitHub is 60 req/hour); the tool retries automatically |
| No repos found | Check token scopes; try `--include-user-repos` |
| GitLab `insufficient_granular_scope` | Recreate the token with `read_api`, `read_repository`, `read_user` |
| Bitbucket 401 | Set `BITBUCKET_USERNAME` (app password) or `BITBUCKET_EMAIL` (API token) |
| SVN checkout failed | Check URL/credentials; add `--svn-trust-cert` for self-signed HTTPS |
| Slow evaluations | `--skip-f2p --skip-quality-checks --skip-taxonomy --skip-pr-rubrics` |

## Utility scripts

`consolidate_output.py` (merge CSVs), `transpose_csv.py` (transpose a CSV),
`bulk_repo_evaluator_parallel.py` (bulk evaluator for a hardcoded repo list).

## License

MIT — see [LICENSE](../LICENSE).
