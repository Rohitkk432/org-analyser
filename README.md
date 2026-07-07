# Org Pipeline

Runnable package for the org/repo analysis pipeline.

This repo contains the master orchestrator plus the local subprojects it calls during a full run:

- `codebase_profiler/`
- `repo_analyzer.py` — LLM-usage detection, training-data-quality scoring, CI/test analysis
- `repo-eval-kit/`
- `repo-quality-score/`
- helper scripts for merged PR counts and PR task-profile classification

## What It Runs

`run_org_pipeline.py` runs these phases:

1. Merged PR/MR counts
2. PR task-profile report
3. Codebase profiler vendor sheet
4. Repo analyzer — LLM-usage, training-data-quality, and CI/test report per repo
5. Data eval-kit repository evaluation
6. Sealed repo quality score and org rollup

Use `run_org_pipeline_no_quality.py` when you want to skip the sealed repo-quality-score stage.

## System Dependencies

Install these before running the pipeline:

- Python 3.10+
- `git`
- `scc` for lines-of-code metrics in `codebase_profiler`
- Node.js / `npx` for duplication metrics in `codebase_profiler`

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

## Python Setup

```bash
python3.12 -m venv .venv  # or python3.11 / python3.10
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python --version            # must be 3.10+
python -m pip install --upgrade pip setuptools wheel hatchling
python -m pip install -r requirements.txt
python -m pip install -e ./codebase_profiler
export ORG_PIPELINE_PYTHON="$(pwd)/.venv/bin/python"
```

If your shell already shows another venv, such as `(env)`, run `deactivate`
first. `codebase_profiler` requires Python 3.10+, so a Python 3.9 venv will fail
even if package installation starts successfully.

`ORG_PIPELINE_PYTHON` is important: the master script launches helper scripts in
subprocesses, and this forces them to use the same venv where `requests`,
`openai`, `openpyxl`, and other dependencies were installed.

If `pip install -e ./codebase_profiler` fails with `setup.py or setup.cfg not found`,
your `pip` is too old for editable installs from `pyproject.toml`. Run:

```bash
python -m pip install --upgrade pip hatchling
python -m pip install -e ./codebase_profiler
```

## Tokens

Copy `tokens.example` to `tokens` and fill in the values:

```ini
github-data-token=...
gitlab_token=...
openai_key=...
```

Do not commit real tokens. `tokens` is ignored by git.

## Run Examples

GitHub org:

```bash
ORG_PIPELINE_PYTHON="$(pwd)/.venv/bin/python" python run_org_pipeline.py --github-org <ORG_NAME> --tokens-file tokens --workers 10
```

Single GitHub repo:

```bash
ORG_PIPELINE_PYTHON="$(pwd)/.venv/bin/python" python run_org_pipeline.py --github-repo <OWNER>/<REPO> --tokens-file tokens --workers 1
```

GitLab group:

```bash
ORG_PIPELINE_PYTHON="$(pwd)/.venv/bin/python" python run_org_pipeline.py --gitlab-group <GROUP_NAME> --tokens-file tokens --workers 10
```

Single GitLab project:

```bash
ORG_PIPELINE_PYTHON="$(pwd)/.venv/bin/python" python run_org_pipeline.py --gitlab-project <GROUP>/<PROJECT> --tokens-file tokens --workers 1
```

Local repos folder:

```bash
ORG_PIPELINE_PYTHON="$(pwd)/.venv/bin/python" python run_org_pipeline.py --local-repos-dir ./repos --repos-manifest repos-manifest.example.json --tokens-file tokens --workers 4
```

No-quality variant:

```bash
ORG_PIPELINE_PYTHON="$(pwd)/.venv/bin/python" python run_org_pipeline_no_quality.py --github-org <ORG_NAME> --tokens-file tokens --workers 10
```

## Outputs

Runs are written under:

```text
outputs/org-pipeline-runs/
```

Each run produces a timestamped folder, logs, CSV/JSON/XLSX outputs, and a zip archive.

## More Docs

See `ORG_PIPELINE_README.md` for the full pipeline documentation and `PR_TASK_PROFILE_README.md` for PR classification details.
