"""
Credential redaction for LLM analysis.
Removes secrets from code diffs before sending to OpenAI/external services.
Preserves code structure for analysis.
"""

import re
from typing import Optional


# Same patterns from repo_analyzer.py
SECRET_PATTERNS = [
    ("AWS Access Key",   r"\bAKIA[0-9A-Z]{16}\b"),
    ("GitHub Token",     r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b"),
    ("GitLab Token",     r"\bglpat-[A-Za-z0-9_\-]{20,}\b"),
    ("Google API Key",   r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    ("Slack Token",      r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b"),
    ("Stripe Key",       r"\b[sp]k_(live|test)_[A-Za-z0-9]{16,}\b"),
    ("OpenAI Key",       r"\bsk-[A-Za-z0-9_\-]{20,}\b"),
    ("Anthropic Key",    r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b"),
    # Must span header→footer: matching only the BEGIN line leaves the key
    # material in the text while the stats claim it was redacted.
    ("Private Key",      r"(?s)-----BEGIN [^-\n]*PRIVATE KEY-----.*?-----END [^-\n]*PRIVATE KEY-----"),
    ("AWS Secret Key",   r"(?i)\baws_secret_access_key\b\s*[:=]\s*['\"]?[A-Za-z0-9/+=]{40}['\"]?"),
    ("Connection String", r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^\s'\"]+:[^\s'\"@]+@[^\s'\"]+"),
    ("JWT",              r"\beyJ[A-Za-z0-9_\-]{15,}\.eyJ[A-Za-z0-9_\-]{15,}"),
    ("Hardcoded secret", r"(?i)\b(password|passwd|secret|api[_-]?key|auth[_-]?token)\b\s*[:=]\s*['\"][^'\"\s]{8,}['\"]"),
]


def redact_secrets(text: str, redaction_marker: str = "[REDACTED]") -> tuple[str, list[tuple[str, int]]]:
    """
    Remove secrets from text while preserving code structure.

    Args:
        text: Code or diff text to redact
        redaction_marker: Placeholder for redacted values (default: [REDACTED])

    Returns:
        Tuple of (redacted_text, list_of_redactions)
        where list_of_redactions is [(secret_type, count_redacted), ...]

    Example:
        >>> code = 'token = "sk-1234567890abcdefghij"'
        >>> redacted, stats = redact_secrets(code)
        >>> redacted
        'token = "[REDACTED]"'
        >>> stats
        [('OpenAI Key', 1)]
    """
    redacted_text = text
    redaction_counts = {}

    for secret_name, pattern in SECRET_PATTERNS:
        # subn on the running text, not findall on the original: counts then
        # reflect what was actually replaced, so the stats can never claim a
        # redaction that did not happen.
        redacted_text, count = re.subn(pattern, redaction_marker, redacted_text)
        if count:
            redaction_counts[secret_name] = count

    redactions = [(name, count) for name, count in redaction_counts.items()]

    return redacted_text, redactions


def scrub_secrets(text: str, *secrets: str, marker: str = "[REDACTED]") -> str:
    """Strip known-literal secrets (a token, an encoded auth header) from text.

    For subprocess stderr and log lines, where we know exactly which secret
    could appear. Pattern-based redact_secrets() is the fallback for text whose
    contents we cannot predict.
    """
    for secret in secrets:
        if secret and len(secret) >= 8:  # never scrub trivially short strings
            text = text.replace(secret, marker)
    return text


def redact_diff(diff_text: str) -> tuple[str, dict]:
    """
    Redact secrets from a unified diff while preserving diff structure.

    Args:
        diff_text: Unified diff text (output from git diff)

    Returns:
        Tuple of (redacted_diff, stats_dict)
        where stats_dict contains redaction statistics

    Redaction runs over the whole diff, not line by line: a PEM private key
    spans many lines, and a per-line pass can never match it. Diff headers
    (---/+++/@@) contain no secrets, so scanning them costs nothing.
    """
    if not diff_text:
        return diff_text, {"redacted": False, "secrets_found": 0}

    redacted_diff, redactions = redact_secrets(diff_text)
    total_redactions = dict(redactions)

    stats = {
        "redacted": len(total_redactions) > 0,
        "secrets_found": sum(total_redactions.values()),
        "secrets_by_type": total_redactions,
    }

    return redacted_diff, stats



# Logging/reporting functions for transparency

def redaction_summary(redactions: list[tuple[str, int]]) -> str:
    """
    Generate a human-readable summary of redactions.

    Args:
        redactions: List from redact_secrets() return value

    Returns:
        String like "Redacted: AWS Key (1), GitHub Token (2)"
    """
    if not redactions:
        return "No secrets redacted"

    parts = [f"{secret_type} ({count})" for secret_type, count in redactions]
    return f"Redacted: {', '.join(parts)}"


# Example usage:
if __name__ == "__main__":
    # Test code with credentials
    sample_code = '''
    # AWS config
    - aws_key = "AKIAIOSFODNN7EXAMPLE"
    + aws_key = os.environ.get("AWS_KEY")

    - github_token = "ghp_1234567890abcdefghijklmnopqrst"
    + github_token = os.environ.get("GITHUB_TOKEN")

    password = "MySecurePassword123"
    '''

    print("BEFORE REDACTION:")
    print(sample_code)
    print("\n" + "="*60 + "\n")

    redacted, stats = redact_diff(sample_code)
    print("AFTER REDACTION:")
    print(redacted)
    print("\n" + "="*60 + "\n")
    print("STATS:", stats)
    print("SUMMARY:", redaction_summary(stats.get("secrets_by_type", {}).items()))
