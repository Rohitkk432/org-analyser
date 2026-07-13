"""Nothing secret reaches an LLM provider.

Run: python test_llm_redaction.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from credential_redactor import redact_diff, redact_secrets
from llm_safety import _Guard

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


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
    print("OK: no secret reaches an LLM provider")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
