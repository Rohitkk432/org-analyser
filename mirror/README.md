# repo-mirror

Tools for **full-fidelity replication** of code hosting into copies you own.

| Script | Platform | Method |
|--------|----------|--------|
| `replicate_github_org.sh` | GitHub org | [GitHub Enterprise Importer (GEI)](https://docs.github.com/en/migrations/using-github-enterprise-importer) |
| `repo_mirror.py` | GitLab group | Project export → import |

Both scripts are **copy-only**: the source org/group is never modified or deleted. Re-runs are safe and resume from per-project/per-repo state.

---

## Setup

Uses the same `tokens` file as the rest of the repo (repo root, `github-data-token`
/ `gitlab_token` keys — see the root `README.md`). From the repo root:

```bash
cp tokens.example tokens   # if you haven't already — add your tokens, never commit it
```

---

# GitHub org replication

`replicate_github_org.sh` copies every repository from a source GitHub org into a target org.

## What gets migrated

- All repositories (including archived and forks)
- Branches, tags, commits
- Issues, pull requests, reviews, review comments
- Labels, milestones, releases
- Wikis and attachments (where GEI supports them)
- Git LFS objects (second pass)

## What does NOT migrate (manual follow-up)

- Actions run history (workflows migrate; past runs do not)
- Actions secrets/variables
- Stars, fork counts, traffic stats
- Deploy keys, webhooks, GitHub Apps
- GitHub Packages / container images
- Org SSO, billing, team membership

## Prerequisites

- [GitHub CLI](https://cli.github.com/) (`gh`)
- `git`, `git-lfs`, `jq`, `curl`
- GEI extension: `gh extension install github/gh-gei`
- **Target org must already exist** (e.g. `VendorOrg-mirror`)
- PAT with access to **both** source and target orgs (org owner or GEI role)

Required token scopes: `repo`, `read:org`, `workflow` (and GEI permissions on both orgs).

## Usage

Run from the repo root:

```bash
./repo_pipeline/mirror/replicate_github_org.sh \
  --tokens-file tokens \
  --source-org SOURCE_ORG \
  --target-org SOURCE_ORG-mirror
```

Or pass the token directly:

```bash
./repo_pipeline/mirror/replicate_github_org.sh \
  --token ghp_... \
  --source-org SOURCE_ORG \
  --target-org SOURCE_ORG-mirror
```

Token key in `tokens`: `github-data-token=ghp_...`

## Output

```
org-replica-<source>-to-<target>/
├── logs/
├── state/
├── repos.txt
├── migration-report.csv
├── migration-report.json
└── POST_MIGRATION_CHECKLIST.md
```

## Example

```bash
./repo_pipeline/mirror/replicate_github_org.sh \
  --tokens-file tokens \
  --source-org acme-corp \
  --target-org acme-corp-mirror
```

---

# GitLab group replication

`repo_mirror.py` copies every project from a source GitLab group into a target group on the same GitLab host.

## What gets migrated

- All projects (including archived, including subgroups)
- Git repository (branches, tags, commits)
- Issues and issue comments
- Merge requests and MR comments
- Labels, milestones, snippets
- Wiki and uploads (within GitLab export limits)
- Git LFS objects (when included in export)

## What does NOT migrate (manual follow-up)

- CI/CD variables and secrets
- Pipeline run history
- Container registry and package registry
- Webhooks, deploy keys, runners
- Group-level permissions and SAML settings

## Prerequisites

- Python 3.10+ (stdlib only — no pip dependencies)
- **Target top-level group must already exist** in GitLab UI
- Token with **Maintainer+** on source projects and target group (`api` scope)

## Usage

After `pip install -e .` (repo root), the `repo-mirror` console script is on your PATH:

```bash
repo-mirror \
  --tokens-file tokens \
  --source-group source-group \
  --target-group source-group-mirror
```

Or run from source without installing:

```bash
python -m repo_pipeline.mirror.repo_mirror \
  --tokens-file tokens \
  --source-group source-group \
  --target-group source-group-mirror
```

Or pass the token directly:

```bash
repo-mirror \
  --token glpat-... \
  --source-group my-group \
  --target-group my-group-mirror \
  --gitlab-host gitlab.com
```

Token key in `tokens`: `gitlab_token`.

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--gitlab-host` | `gitlab.com` | GitLab hostname or base URL |
| `--workdir` | `./group-replica-<source>-to-<target>` | Stable work directory |
| `--poll-seconds` | `15` | Export/import poll interval |
| `--export-timeout` | `7200` | Per-project export timeout (seconds) |
| `--import-timeout` | `7200` | Per-project import timeout (seconds) |

## Output

```
group-replica-<source>-to-<target>/
├── logs/
├── state/
├── exports/
├── projects.txt
├── migration-report.csv
├── migration-report.json
└── POST_MIGRATION_CHECKLIST.md
```

Subgroups under the target are created automatically when needed.

## Example

```bash
repo-mirror \
  --tokens-file tokens \
  --source-group example-group \
  --target-group example-group-mirror
```

---

## Notes (both platforms)

- Large orgs/groups can take many hours
- Re-running skips projects/repos already marked `success`
- Never commit `tokens` — it is listed in `.gitignore`
