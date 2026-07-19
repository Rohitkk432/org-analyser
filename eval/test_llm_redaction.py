"""Nothing secret reaches an LLM provider.

Run: python test_llm_redaction.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from eval.credential_redactor import redact_diff, redact_secrets
from eval.llm_safety import _Guard

PEM = """-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEA7x9Kq2vN8fLmZ0pQrStUvWxYz1234567890abcdefghij
kLmNoPqRsTuVwXyZ0987654321zyxwvutsrqponmlkjihgfedcbaABCDEFGH
-----END RSA PRIVATE KEY-----"""

KEY_BODY = "MIIEowIBAAKCAQEA7x9Kq2vN8fLmZ0pQrStUvWxYz1234567890abcdefghij"


def test_private_key_fully_redacted():
    out, stats = redact_secrets(PEM)
    assert KEY_BODY not in out, "key material survived redaction"
    assert "-----END RSA PRIVATE KEY-----" not in out
    assert dict(stats)["Private Key"] == 1


def test_private_key_in_diff():
    # The old line-by-line pass could never match a multi-line PEM.
    diff = "diff --git a/id_rsa b/id_rsa\n--- /dev/null\n+++ b/id_rsa\n"
    diff += "\n".join("+" + line for line in PEM.splitlines())
    out, stats = redact_diff(diff)
    assert KEY_BODY not in out, "key material survived diff redaction"
    assert stats["redacted"] is True
    assert stats["secrets_found"] >= 1


def test_stats_never_overclaim():
    # Stats come from the actual substitution count, so a "redacted" report
    # cannot be issued for text that was left intact.
    clean = "def add(a, b):\n    return a + b\n"
    out, stats = redact_secrets(clean)
    assert out == clean
    assert stats == []


def test_common_tokens_redacted():
    text = (
        'gh = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"\n'
        'oa = "sk-abcdefghijklmnopqrstuvwxyz0123"\n'
        'aws_secret_access_key = "abcdefghijklmnopqrstuvwxyz0123456789ABCD"\n'
        'db = "postgres://admin:hunter2@10.0.0.5:5432/prod"\n'
    )
    out, _ = redact_secrets(text)
    for leaked in ("ghp_abcdefghij", "sk-abcdefghij", "hunter2", "ABCD"):
        assert leaked not in out, f"{leaked!r} survived redaction"


class _FakeCompletions:
    """Stands in for the OpenAI SDK; records what it was actually sent."""

    def __init__(self):
        self.seen = None

    def create(self, **kwargs):
        self.seen = kwargs
        return "ok"

    parse = create


class _FakeChat:
    def __init__(self):
        self.completions = _FakeCompletions()


class _FakeClient:
    def __init__(self):
        self.chat = _FakeChat()


def test_wrapper_redacts_in_flight():
    inner = _FakeClient()
    client = _Guard(inner)

    client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "classify this"},
            {"role": "user", "content": f"here is the diff:\n{PEM}\ntoken=ghp_abcdefghijklmnopqrstuvwxyz01"},
        ],
    )

    sent = str(inner.chat.completions.seen)
    assert KEY_BODY not in sent, "private key reached the provider"
    assert "ghp_abcdefghij" not in sent, "github token reached the provider"
    assert "[REDACTED]" in sent
    # Non-secret content must survive, or classification quality degrades.
    assert "classify this" in sent
    assert "here is the diff" in sent
    assert inner.chat.completions.seen["model"] == "gpt-4o"


def test_quality_evaluator_raw_path_redacts_whole_prompt():
    # The raw requests path must redact every interpolated field, not just the
    # diff -- a secret in commit_message or problem_statement must not escape.
    import os
    import requests

    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["body"] = json

        class R:
            def raise_for_status(self):
                pass

            def json(self):
                return {"choices": [{"message": {"content": "{}"}}]}

        return R()

    saved_post = requests.post
    saved_key = os.environ.get("OPENAI_API_KEY")
    saved_az = {k: os.environ.get(k) for k in ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY")}
    try:
        requests.post = fake_post
        for k in saved_az:
            os.environ.pop(k, None)
        os.environ["OPENAI_API_KEY"] = "test-key"

        import eval.quality_evaluator as qe

        ev = qe.QualityEvaluator(llm_provider="openai")
        ev.evaluate_candidate(
            src_diff="diff --git a/x b/x\n+++ b/x\n+print(1)\n",
            test_diff="",
            problem_statement="fix per sk-abcdefghijklmnopqrstuvwxyz012345",
            commit_message="rotate ghp_abcdefghijklmnopqrstuvwxyz01",
        )
        body = str(captured.get("body", {}))
        assert "ghp_abcdefghij" not in body, "commit_message secret reached provider"
        assert "sk-abcdefghij" not in body, "problem_statement secret reached provider"
        assert "REDACTED" in body
    finally:
        requests.post = saved_post
        if saved_key is None:
            os.environ.pop("OPENAI_API_KEY", None)
        else:
            os.environ["OPENAI_API_KEY"] = saved_key
        for k, v in saved_az.items():
            if v is not None:
                os.environ[k] = v


def test_azure_selection_and_deployment_remap():
    import os
    import eval.llm_safety as llm_safety
    from openai import AzureOpenAI, OpenAI

    saved = {k: os.environ.get(k) for k in
             ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_DEPLOYMENT")}
    try:
        # No Azure env -> plain OpenAI client, model left as-is.
        for k in saved:
            os.environ.pop(k, None)
        assert isinstance(object.__getattribute__(llm_safety.safe_openai(api_key="x"), "_inner"), OpenAI)
        assert llm_safety._redact_kwargs({"model": "gpt-4o"})["model"] == "gpt-4o"

        # Azure env -> AzureOpenAI, and model remapped to the deployment name.
        os.environ["AZURE_OPENAI_ENDPOINT"] = "https://f.openai.azure.com/"
        os.environ["AZURE_OPENAI_API_KEY"] = "fake"
        os.environ["AZURE_OPENAI_DEPLOYMENT"] = "prod-4o"
        client = llm_safety.safe_openai(api_key="sk-openai", base_url="https://api.openai.com/v1")
        assert isinstance(object.__getattribute__(client, "_inner"), AzureOpenAI)
        assert llm_safety._redact_kwargs({"model": "gpt-4o"})["model"] == "prod-4o"
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
    print("OK: no secret reaches an LLM provider")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
