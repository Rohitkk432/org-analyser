# org-analyser

Org/repo codebase analysis pipeline: merged-PR counts, PR task-profile, codebase
profiler, eval-kit, and sealed repo quality score — one command, one or many
repos, across GitHub, GitLab, Bitbucket, or a folder of local checkouts.

This repo is an installable package (`pyproject.toml`) with these subpackages:

- `analysis/` — merged-PR counts, PR task-profile classification, vendor-CSV repo analyzer
- `profiler/` — the codebase intake-sheet profiler (`codebase-profiler`)
- `eval/` — full LLM-backed repo evaluation ("eval-kit")
- `quality/` — sealed, tamper-evident repo quality score
- `mirror/` — GitHub org / GitLab group replication (copy-only, source never modified)

## System Dependencies

Install these before running the pipeline:

- Python 3.10+
- `git`
- `scc` for lines-of-code metrics (`profiler/`)
- Node.js / `npx` for duplication metrics (`profiler/`)

macOS:

```bash
brew install git scc node
```

Windows with Chocolatey:

```powershell
choco install git nodejs scc -y
```

If Chocolatey fails for `scc`, download the Windows binary directly from the
[`scc` releases page](https://github.com/boyter/scc/releases/latest), extract
`scc.exe`, and put it on your `PATH`.

Ubuntu/Debian:

```bash
sudo apt-get update
sudo apt-get install -y git nodejs npm
# Install scc from https://github.com/boyter/scc/releases/latest
```

Verify:

```bash
git --version
scc --version
node --version
npx --version
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip   # need pip>=21.3 for editable installs (PEP 660)
pip install -e .
cp config.example.yml config.yml
```

If your shell already shows another venv, run `deactivate` first — this
package requires Python 3.10+, and an older venv will fail even if
installation appears to start successfully.

## Tokens

Edit `config.yml` → fill in `tokens:` (only whichever platform(s) you use).
`config.yml` is gitignored, never committed. Pass `--tokens-file` instead if
you'd rather keep tokens in a separate key=value file.

- `github-data-token` — [github.com/settings/tokens](https://github.com/settings/tokens) (classic, `repo` scope)
- `gitlab_token` — [gitlab.com/-/user_settings/personal_access_tokens](https://gitlab.com/-/user_settings/personal_access_tokens) (`read_api` scope)
- `bitbucket_token` / `bitbucket_username` — Bitbucket app password, workspace/repo access token, or Atlassian API token (see `profiler/README.md` → Authentication for the token-type-to-env-var mapping); optional for public repos
- `openai_key` — [platform.openai.com/api-keys](https://platform.openai.com/api-keys) (or set `OPENAI_API_KEY`/`AZURE_OPENAI_*` in the environment)

Do not commit real tokens.

## Run Examples

GitHub org:

```bash
org-analyser --github-org <ORG_NAME> --workers 10
```

Single GitHub repo:

```bash
org-analyser --github-repo <OWNER>/<REPO> --workers 1
```

GitLab group:

```bash
org-analyser --gitlab-group <GROUP_NAME> --workers 10
```

Single GitLab project:

```bash
org-analyser --gitlab-project <GROUP>/<PROJECT> --workers 1
```

Bitbucket workspace:

```bash
org-analyser --bitbucket-workspace <WORKSPACE_NAME> --workers 10
```

Single Bitbucket repo:

```bash
org-analyser --bitbucket-repo <WORKSPACE>/<REPO> --workers 1
```

Local repos folder:

```bash
org-analyser --local-repos-dir ./repos --repos-manifest repos-manifest.example.json --workers 4
```

Skip the sealed repo-quality-score phase:

```bash
org-analyser --github-org <ORG_NAME> --skip-quality-score
```

Any flag can instead be set as a default in `config.yml` — with a target and
tokens filled in there, `org-analyser` runs with zero flags. `org-analyser --help`
lists every flag.

## Outputs

Runs are written under:

```text
outputs/org-analyser-runs/
```

Each run produces a timestamped folder, logs, CSV/JSON/XLSX outputs, and a zip
archive. Run bundles carry contributor names, per-author stats, and scores;
old bundles are pruned automatically after `--retention-days` (default 90).

## Debug

- **`SSL: CERTIFICATE_VERIFY_FAILED`** — fixed via `certifi`; rerun after `pip install -e .` picks up the dependency.
- **Auth / 404 / "Could not resolve to a Repository"** — check the token in `config.yml` has access to that org/repo, and the `owner/repo` (or `workspace/repo`) name is correct.
- **Config not picked up** — confirm you're running from the repo root (`config.yml` must sit next to `cli.py`), or set `ORG_ANALYSER_CONFIG=/path/to/config.yml`.
- **No target error** — pass one of `--github-org` / `--github-repo` / `--gitlab-group` / `--gitlab-project` / `--bitbucket-workspace` / `--bitbucket-repo` / `--local-repos-dir`, or set one under `config.yml`.
- Logs print to stdout during the run; check the run's `manifest.json` for a per-repo pass/fail summary.

## More Docs

See `ORG_PIPELINE_README.md` for the full pipeline documentation,
`PR_TASK_PROFILE_README.md` for PR classification details, and
`SECURITY_AND_COMPLIANCE.md` for the credential-handling and redaction model.
