# repo-mirror

Full-fidelity, copy-only replication of code hosting into copies you own. The
source org/group is never modified or deleted; re-runs resume from state and
skip anything already marked `success`.

| Script | Platform | Method |
|--------|----------|--------|
| `replicate_github_org.sh` | GitHub org | [GitHub Enterprise Importer (GEI)](https://docs.github.com/en/migrations/using-github-enterprise-importer) |
| `repo_mirror.py` | GitLab group | Project export → import |

Tokens come from `config.yml`'s `tokens:` mapping (`github-data-token` /
`gitlab_token`) or `--tokens-file` / `--token` directly — see the root `README.md`.

## GitHub org replication

Migrates repos (incl. archived/forks), branches/tags/commits, issues, PRs +
reviews, labels/milestones/releases, wikis, and LFS objects. Does **not**
migrate: Actions run history/secrets, stars/traffic stats, webhooks/deploy
keys, packages, org SSO/billing/team membership — handle those manually.

Prerequisites: [`gh`](https://cli.github.com/) + `gh extension install github/gh-gei`,
`git`/`git-lfs`/`jq`/`curl`, the target org already created, and a PAT with
`repo`/`read:org`/`workflow` scopes plus GEI access on both orgs.

```bash
./mirror/replicate_github_org.sh \
  --tokens-file tokens \
  --source-org acme-corp \
  --target-org acme-corp-mirror
```

Output: `org-replica-<source>-to-<target>/` with `logs/`, `state/`, a
migration report (csv/json), and `POST_MIGRATION_CHECKLIST.md`.

## GitLab group replication

Migrates projects (incl. archived, subgroups), the git repo, issues, MRs +
comments, labels/milestones/snippets, wiki/uploads, LFS. Does **not**
migrate: CI/CD variables, pipeline history, registries, webhooks/runners,
group-level permissions/SAML.

Prerequisites: Python 3.10+ (stdlib only), the target top-level group already
created in the GitLab UI, and a token with Maintainer+ / `api` scope on both.

```bash
repo-mirror \
  --tokens-file tokens \
  --source-group example-group \
  --target-group example-group-mirror \
  --gitlab-host gitlab.com   # default; omit for gitlab.com
```

Options: `--workdir` (default `./group-replica-<source>-to-<target>`),
`--poll-seconds` (15), `--export-timeout` / `--import-timeout` (7200s each).

Output: `group-replica-<source>-to-<target>/` with `logs/`, `state/`,
`exports/`, a migration report (csv/json), and `POST_MIGRATION_CHECKLIST.md`.
Target subgroups are created automatically as needed.
