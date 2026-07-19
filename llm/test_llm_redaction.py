"""Nothing secret reaches an LLM provider.

Run (from repo root): python -m llm.test_llm_redaction
"""

from llm.credential_redactor import redact_diff, redact_secrets
from llm.llm_safety import _Guard

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


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeChatCompletion:
    def __init__(self, content="{}"):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    """Stands in for the OpenAI SDK; records what it was actually sent."""

    def __init__(self):
        self.seen = None

    def create(self, **kwargs):
        self.seen = kwargs
        return _FakeChatCompletion()

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


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeChatCompletion:
    def __init__(self, content="{}"):
        self.choices = [_FakeChoice(content)]


def test_quality_evaluator_openai_path_redacts_whole_prompt():
    # _call_openai now goes through llm.llm_safety.safe_openai(), not a raw
    # requests.post -- every interpolated field (diff, commit_message,
    # problem_statement) must still be redacted before it reaches the client.
    import eval.quality_evaluator as qe

    inner = _FakeClient()

    saved_safe_openai = qe.safe_openai
    try:
        qe.safe_openai = lambda **kwargs: _Guard(inner)

        ev = qe.QualityEvaluator(llm_provider="openai", api_key="test-key")
        ev.evaluate_candidate(
            src_diff="diff --git a/x b/x\n+++ b/x\n+print(1)\n",
            test_diff="",
            problem_statement="fix per sk-abcdefghijklmnopqrstuvwxyz012345",
            commit_message="rotate ghp_abcdefghijklmnopqrstuvwxyz01",
        )
        body = str(inner.chat.completions.seen)
        assert "ghp_abcdefghij" not in body, "commit_message secret reached provider"
        assert "sk-abcdefghij" not in body, "problem_statement secret reached provider"
        assert "REDACTED" in body
    finally:
        qe.safe_openai = saved_safe_openai


def test_quality_evaluator_gemini_path_redacts_prompt():
    # _call_gemini delegates entirely to llm.llm_safety.safe_gemini() -- this
    # exercises that function's own redaction pass, not quality_evaluator's.
    # requests.post is patched on the shared `requests` module object, so it's
    # seen regardless of which module does `import requests` and calls it.
    import requests

    import eval.quality_evaluator as qe

    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = json

        class R:
            def raise_for_status(self):
                pass

            def json(self):
                return {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}

        return R()

    saved_post = requests.post
    try:
        requests.post = fake_post

        ev = qe.QualityEvaluator(llm_provider="gemini", api_key="fake-gemini-key")
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
        # Key travels in the header only, never the query string.
        assert "fake-gemini-key" not in captured.get("url", "")
        assert captured["headers"]["x-goog-api-key"] == "fake-gemini-key"
    finally:
        requests.post = saved_post


def test_azure_selection_and_deployment_remap():
    import os
    import llm.llm_safety as llm_safety
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
