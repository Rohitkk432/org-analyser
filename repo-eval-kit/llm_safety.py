"""One redacting choke point for every OpenAI call.

Redaction used to be opt-in per call site, which is exactly why three sites
(raw git diffs, PR bodies, human review comments) shipped unredacted for
months. Construct clients with `safe_openai()` instead of `OpenAI()` and the
redaction cannot be forgotten: it happens on the way out, inside the client.

    from llm_safety import safe_openai
    client = safe_openai()                    # instead of OpenAI()
    client.chat.completions.create(...)       # messages redacted in flight
    client.beta.chat.completions.parse(...)   # same

Only secret *values* are replaced ([REDACTED]); prose, code structure, diff
markers and identifiers are untouched, so classification quality is unaffected.
"""

import logging
from typing import Any

try:
    from .credential_redactor import redact_secrets
except ImportError:
    from credential_redactor import redact_secrets

logger = logging.getLogger(__name__)

# Call methods that carry a prompt payload to the provider.
_SENDING_METHODS = frozenset({"create", "parse", "stream"})


def _redact_content(value: Any) -> tuple[Any, int]:
    """Redact a message `content`, which may be a str or a list of parts."""
    if isinstance(value, str):
        cleaned, found = redact_secrets(value)
        return cleaned, sum(n for _, n in found)
    if isinstance(value, list):
        parts, total = [], 0
        for part in value:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                cleaned, found = redact_secrets(part["text"])
                total += sum(n for _, n in found)
                parts.append({**part, "text": cleaned})
            else:
                parts.append(part)
        return parts, total
    return value, 0


def _redact_kwargs(kwargs: dict) -> dict:
    total = 0

    messages = kwargs.get("messages")
    if isinstance(messages, list):
        clean_messages = []
        for msg in messages:
            if isinstance(msg, dict) and "content" in msg:
                content, found = _redact_content(msg["content"])
                total += found
                clean_messages.append({**msg, "content": content})
            else:
                clean_messages.append(msg)
        kwargs["messages"] = clean_messages

    # Responses API uses `input` rather than `messages`.
    if isinstance(kwargs.get("input"), str):
        cleaned, found = redact_secrets(kwargs["input"])
        kwargs["input"] = cleaned
        total += sum(n for _, n in found)

    if total:
        logger.info("llm_safety: redacted %d secret(s) before sending to provider", total)
    return kwargs


class _Guard:
    """Attribute proxy that redacts payloads on the terminal call."""

    def __init__(self, inner: Any):
        object.__setattr__(self, "_inner", inner)

    def __getattr__(self, name: str) -> Any:
        attr = getattr(object.__getattribute__(self, "_inner"), name)

        if name in _SENDING_METHODS and callable(attr):
            def guarded(*args: Any, **kwargs: Any) -> Any:
                return attr(*args, **_redact_kwargs(kwargs))
            return guarded

        # Namespaces (.chat, .beta, .completions, .responses) -> keep guarding.
        if hasattr(attr, "__dict__") and not callable(attr):
            return _Guard(attr)
        return attr


def safe_openai(**kwargs: Any) -> Any:
    """Drop-in for `OpenAI(...)` that redacts secrets from every prompt."""
    from openai import OpenAI

    return _Guard(OpenAI(**kwargs))
