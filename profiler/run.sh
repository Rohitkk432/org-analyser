#!/usr/bin/env bash
#
# One-command Docker runner for codebase-profiler.
#
#   ./run.sh --organization my-org
#   ./run.sh --repo owner/name
#   ./run.sh --repo https://gitlab.com/group/project --platform gitlab
#   ./run.sh some-local-repo-folder        # a folder inside the current directory
#   ./run.sh --build ...                   # force-rebuild the image first
#
# - Builds the image once (cached afterwards), so no installing scc/uv/node/jscpd by hand.
# - Output xlsx is written to the folder you run this from.
# - Cloned repos are cached in a Docker volume, so re-runs don't re-clone.
# - Tokens: set GITHUB_TOKEN / GITLAB_TOKEN, or it will reuse your `gh` login automatically.

set -euo pipefail

IMAGE="codebase-profiler:latest"
CACHE_VOLUME="codebase_profiler_cache"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if ! command -v docker >/dev/null 2>&1; then
  echo "error: Docker is not installed or not on PATH. Install Docker Desktop first." >&2
  exit 1
fi

# `--install`: build the image and exit (one-time setup, no profiling run).
if [[ "${1:-}" == "--install" ]]; then
  echo "Building the Docker image (one-time setup, a few minutes)..."
  docker build -t "$IMAGE" -f "$SCRIPT_DIR/Dockerfile" "$REPO_ROOT"
  docker volume create "$CACHE_VOLUME" >/dev/null
  echo "✓ Done. The profiler is installed. Now run, e.g.:"
  echo "    ./run.sh --repo owner/name"
  exit 0
fi

# Build the image on first use, or when --build is passed.
if [[ "${1:-}" == "--build" ]]; then
  shift
  docker build -t "$IMAGE" -f "$SCRIPT_DIR/Dockerfile" "$REPO_ROOT"
elif ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "First run: building the Docker image (one-time, a few minutes)..."
  docker build -t "$IMAGE" -f "$SCRIPT_DIR/Dockerfile" "$REPO_ROOT"
fi

# Convenience: reuse the host's gh login for GitHub when no token is set.
if [[ -z "${GITHUB_TOKEN:-}" ]] && command -v gh >/dev/null 2>&1; then
  GITHUB_TOKEN="$(gh auth token 2>/dev/null || true)"
  export GITHUB_TOKEN
fi

docker volume create "$CACHE_VOLUME" >/dev/null

# Allocate a TTY only when attached to one (portable across macOS bash 3.2 + set -u).
TTY_FLAGS=()
if [[ -t 0 && -t 1 ]]; then
  TTY_FLAGS=(-it)
fi

docker run --rm ${TTY_FLAGS[@]+"${TTY_FLAGS[@]}"} \
  -v "$(pwd)":/work -w /work \
  -v "${CACHE_VOLUME}":/root/.cache \
  -e GITHUB_TOKEN -e GH_TOKEN -e GITLAB_TOKEN -e GIT_TOKEN \
  -e BITBUCKET_TOKEN -e BITBUCKET_APP_PASSWORD -e BITBUCKET_USERNAME \
  -e ATLASSIAN_EMAIL -e BITBUCKET_EMAIL \
  "$IMAGE" "$@"
status=$?

# The container writes to /work, which is this folder. Show the real host location.
if [[ $status -eq 0 ]]; then
  echo "(results are in this folder: $(pwd))"
fi
exit $status
