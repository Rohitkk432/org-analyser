"""End-to-end: a malicious repository cannot steal pipeline credentials.

test_env_scrub.py unit-tests build_child_env(). This test does the real thing:
it builds a repository whose conftest.py exfiltrates its environment to disk
(exactly what a supply-chain postinstall or a hostile contributor's PR branch
would do), then drives the *real* PytestRunner against it and asserts the
credentials never arrived.

If build_child_env() is ever bypassed or weakened, this fails.

Run: python test_hostile_repo.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_runners import get_runner

# Credentials the pipeline legitimately holds while it runs.
SECRETS = {
    "GITHUB_TOKEN": "ghp_hostiletest000000000000000000000000",
    "GITLAB_TOKEN": "glpat-hostiletest00000000",
    "OPENAI_API_KEY": "sk-hostiletest0000000000000000000",
    "AWS_SECRET_ACCESS_KEY": "hostiletestAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    "REPO_EVAL_TOKEN": "ghp_hostiletest111111111111111111111111",
}

# The payload. A real attacker would POST this; writing to disk is the same
# capability and keeps the test hermetic (no network).
CONFTEST = '''
import os, json, pathlib
loot = pathlib.Path(__file__).parent / "stolen_env.json"
loot.write_text(json.dumps(dict(os.environ)))
'''

TEST_FILE = '''
def test_placeholder():
    assert True
'''


def main() -> int:
    for k, v in SECRETS.items():
        os.environ[k] = v

    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "hostile-repo"
        repo.mkdir()
        (repo / "conftest.py").write_text(CONFTEST)
        (repo / "test_thing.py").write_text(TEST_FILE)

        runner = get_runner(repo, "python")
        assert runner is not None, "no runner detected; test proves nothing"
        print(f"  runner: {runner.name}")

        runner.run_tests(repo, timeout=120)

        loot_file = repo / "stolen_env.json"
        assert loot_file.exists(), (
            "conftest.py never executed -- the test is not actually exercising "
            "the attack path, so a pass here would be meaningless"
        )

        stolen = json.loads(loot_file.read_text())
        print(f"  hostile conftest.py ran and captured {len(stolen)} env vars")

        leaked = [k for k, v in SECRETS.items() if k in stolen]
        leaked_by_value = [
            k for k, v in SECRETS.items() if v in stolen.values()
        ]

        assert not leaked, f"credentials visible to hostile repo code: {leaked}"
        assert not leaked_by_value, f"credential values leaked: {leaked_by_value}"

        # The attack ran, saw an environment, and found nothing worth taking.
        assert "PATH" in stolen, "PATH missing -- builds would not resolve tools"

    print("OK: hostile repo executed, stole nothing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
