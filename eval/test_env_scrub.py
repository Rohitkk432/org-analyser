"""Untrusted repo commands must not inherit pipeline credentials.

Run: python test_env_scrub.py
"""

import os
import subprocess
import sys
from pathlib import Path

from eval.test_runners.base import build_child_env

SECRETS = {
    "GITHUB_TOKEN": "ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "GITLAB_TOKEN": "glpat-bbbbbbbbbbbbbbbbbbbb",
    "OPENAI_API_KEY": "sk-cccccccccccccccccccccccccccccccc",
    "AWS_SECRET_ACCESS_KEY": "dddddddddddddddddddddddddddddddddddddddd",
    "ANTHROPIC_API_KEY": "sk-ant-eeeeeeeeeeeeeeeeeeeeeeee",
}


def main() -> int:
    for k, v in SECRETS.items():
        os.environ[k] = v
    os.environ["PATH"] = os.environ.get("PATH", "/usr/bin")
    os.environ["JAVA_HOME"] = "/opt/java"

    env = build_child_env()

    for k in SECRETS:
        assert k not in env, f"secret {k} leaked into child env"
    assert "PATH" in env, "PATH must survive or no toolchain resolves"
    assert env.get("JAVA_HOME") == "/opt/java", "toolchain roots must survive"

    # overrides still apply (javascript.py relies on this)
    assert build_child_env({"CI": "true"})["CI"] == "true"

    # opt-in passthrough widens the allowlist, nothing else
    os.environ["F2P_ENV_PASSTHROUGH"] = "ARTIFACTORY_URL"
    os.environ["ARTIFACTORY_URL"] = "https://artifacts.internal"
    widened = build_child_env()
    assert widened["ARTIFACTORY_URL"] == "https://artifacts.internal"
    assert "GITHUB_TOKEN" not in widened, "passthrough must not reopen secrets"
    del os.environ["F2P_ENV_PASSTHROUGH"]

    # End to end: a hostile "test" reading the env sees no secrets.
    hostile = "import os,json;print(json.dumps({k:v for k,v in os.environ.items()}))"
    proc = subprocess.run(
        [sys.executable, "-c", hostile],
        capture_output=True, text=True, env=build_child_env(), timeout=30,
    )
    child_env = proc.stdout
    for k, v in SECRETS.items():
        assert v not in child_env, f"{k} value visible to child process"

    print("OK: repo commands run credential-free")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    raise SystemExit(main())
