# syntax=docker/dockerfile:1
#
# Self-contained image: bundles git, scc, Node/jscpd, uv and the profiler itself, so a
# recipient only needs Docker. Build once; the tools live in the image layer and the clone
# cache lives in a mounted volume, so repeated runs don't reinstall or re-clone.

# Base on Node (for jscpd); uv brings its own Python, so we avoid the heavy/fragile
# system-python + apt-npm dependency trees.
FROM node:20-bookworm-slim

ARG TARGETARCH
ARG SCC_VERSION=3.7.0

# System tools: git (clone + history), curl/tar (fetch scc).
RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates curl tar \
    && rm -rf /var/lib/apt/lists/*

# scc — single Go binary from GitHub releases (LOC / language / file counting).
RUN set -eux; \
    case "${TARGETARCH}" in \
      arm64) SCC_ARCH=arm64 ;; \
      amd64) SCC_ARCH=x86_64 ;; \
      *)     SCC_ARCH=x86_64 ;; \
    esac; \
    curl -fsSL "https://github.com/boyter/scc/releases/download/v${SCC_VERSION}/scc_Linux_${SCC_ARCH}.tar.gz" \
        -o /tmp/scc.tgz; \
    tar -xzf /tmp/scc.tgz -C /usr/local/bin scc; \
    rm /tmp/scc.tgz; \
    scc --version

# gh CLI — lets local-folder runs read PR/fork stats from a checkout's GitHub remote
# (the provider path is used for --repo/--organization; this is the local fallback).
ARG GH_VERSION=2.62.0
RUN set -eux; \
    case "${TARGETARCH}" in \
      arm64) GH_ARCH=arm64 ;; \
      amd64) GH_ARCH=amd64 ;; \
      *)     GH_ARCH=amd64 ;; \
    esac; \
    curl -fsSL "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_${GH_ARCH}.tar.gz" \
        -o /tmp/gh.tgz; \
    tar -xzf /tmp/gh.tgz -C /tmp; \
    mv "/tmp/gh_${GH_VERSION}_linux_${GH_ARCH}/bin/gh" /usr/local/bin/gh; \
    rm -rf /tmp/gh.tgz "/tmp/gh_${GH_VERSION}_linux_${GH_ARCH}"; \
    gh --version

# jscpd — duplication detector, installed globally so it's instant at runtime.
RUN npm install -g jscpd@4 && jscpd --version

# uv — fast Python package manager (copied from the official image).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install the org-analyser package (profiler is one of its subpackages) and its deps into
# an in-image venv. uv downloads a managed CPython automatically (no system Python needed).
# Build context is the repo root (see run.sh), so this pulls in the whole package.
ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python
WORKDIR /app
COPY pyproject.toml README.md ./
COPY analysis ./analysis
COPY eval ./eval
COPY mirror ./mirror
COPY profiler ./profiler
COPY quality ./quality
COPY cli.py ./cli.py
RUN uv venv --python 3.12 && uv pip install .
ENV PATH="/app/.venv/bin:${PATH}"

# Clone cache lives here; mount a volume to persist it across runs.
ENV XDG_CACHE_HOME=/root/.cache

# Output and local repos are read/written under /work (mount the host cwd there).
WORKDIR /work
ENTRYPOINT ["codebase-profiler"]
CMD ["--help"]
