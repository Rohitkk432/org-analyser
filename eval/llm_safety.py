"""One redacting choke point for every LLM call (OpenAI, Azure, Gemini).

Redaction used to be opt-in per call site, which is exactly why three sites
(raw git diffs, PR bodies, human review comments) shipped unredacted for
months. Construct clients with `safe_openai()` instead of `OpenAI()`, or call
`safe_gemini()` instead of hand-rolling a Gemini request, and the redaction
cannot be forgotten: it happens on the way out, inside the client/call.

    from llm_safety import safe_openai
    client = safe_openai()                    # instead of OpenAI()
    client.chat.completions.create(...)       # messages redacted in flight
    client.beta.chat.completions.parse(...)   # same

    from llm_safety import safe_gemini
    text = safe_gemini(prompt)                # instead of requests.post(...)

Only secret *values* are replaced ([REDACTED]); prose, code structure, diff
markers and identifiers are untouched, so classification quality is unaffected.
"""

import logging
import os
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

    # Azure indexes by deployment name, not model name. If the deployment is
    # named differently from the model the call sites pass (e.g. "gpt-4o"), map
    # it here once so no call site has to change.
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "").strip()
    if deployment and "model" in kwargs:
        kwargs["model"] = deployment

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


def _is_azure() -> bool:
    return bool(os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip())


def llm_available() -> bool:
    """True if any supported LLM provider is configured — OpenAI or Azure.

    Call-site guards should use this instead of checking OPENAI_API_KEY
    directly, otherwise an Azure-only setup looks unconfigured and the LLM
    pass is wrongly skipped or aborted.
    """
    if os.environ.get("OPENAI_API_KEY", "").strip():
        return True
    return _is_azure() and bool(os.environ.get("AZURE_OPENAI_API_KEY", "").strip())


def safe_openai(**kwargs: Any) -> Any:
    """Redacting drop-in for `OpenAI(...)`.

    Talks to Azure AI Foundry / Azure OpenAI when AZURE_OPENAI_ENDPOINT is set,
    otherwise to OpenAI directly. Same guarded client either way, so redaction
    holds on both. Azure auth reads from the environment:

        AZURE_OPENAI_ENDPOINT     https://<resource>.openai.azure.com/
        AZURE_OPENAI_API_KEY      (or use api_key= / Entra ID; see below)
        OPENAI_API_VERSION        e.g. 2024-10-21  (defaults if unset)
        AZURE_OPENAI_DEPLOYMENT   deployment name, if it differs from the model

    Any explicit kwargs (api_key=…) still win over the environment.
    """
    if _is_azure():
        from openai import AzureOpenAI

        params = {
            "azure_endpoint": os.environ["AZURE_OPENAI_ENDPOINT"].strip(),
            "api_version": os.environ.get("OPENAI_API_VERSION", "2024-10-21"),
        }
        # An api_key passed by a call site is an OpenAI key, not an Azure one --
        # drop it so the Azure client uses AZURE_OPENAI_API_KEY (or Entra ID).
        kwargs.pop("api_key", None)
        kwargs.pop("base_url", None)
        params.update(kwargs)
        return _Guard(AzureOpenAI(**params))

    from openai import OpenAI

    return _Guard(OpenAI(**kwargs))


def gemini_available() -> bool:
    """True if GEMINI_API_KEY is configured.

    Separate from llm_available() deliberately: that check's callers never
    touch Gemini, so folding it in would change what "available" means for
    every existing OpenAI/Azure-only guard.
    """
    return bool(os.environ.get("GEMINI_API_KEY", "").strip())


def safe_gemini(
    prompt: str,
    model: str = "gemini-3-flash-preview",
    api_key: str | None = None,
) -> Any:
    """Redacting drop-in for a raw Gemini `generateContent` call.

    Gemini has no OpenAI-SDK-shaped client to wrap here, so this redacts the
    prompt directly and does the REST call itself -- the same on-the-way-out
    guarantee safe_openai() gives the OpenAI/Azure path. The key travels in
    the `x-goog-api-key` header only, never the query string (a query-string
    key lands in proxy logs, gateway logs, and shell history).

    Returns the response text, or None on failure (network error or an
    unexpected response shape) -- logged either way, never raised.
    """
    import requests

    cleaned, found = redact_secrets(prompt)
    total = sum(n for _, n in found)
    if total:
        logger.info("llm_safety: redacted %d secret(s) before sending to provider", total)

    key = api_key or os.environ.get("GEMINI_API_KEY", "")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    try:
        response = requests.post(
            url,
            headers={"Content-Type": "application/json", "x-goog-api-key": key},
            json={"contents": [{"role": "user", "parts": [{"text": cleaned}]}]},
            timeout=120,
        )
        response.raise_for_status()
        return response.json()["candidates"][0]["content"]["parts"][0]["text"]
    except requests.exceptions.RequestException as exc:
        logger.error(f"Gemini API failed: {exc}")
        return None
    except (KeyError, IndexError) as exc:
        logger.error(f"Unexpected Gemini response: {exc}")
        return None
