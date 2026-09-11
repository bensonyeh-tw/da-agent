"""Python-level masking library for chat output sanitization and PII/data protection."""

import re
from typing import Any

# Regular expression patterns for sensitive data
# 1. Credit Card / Payment Card numbers (PAN) - 13 to 19 digits, optional dashes/spaces
CARD_PATTERN = re.compile(
    r"\b(?:\d[ -]*?){13,19}\b"
)

# 2. Email addresses
EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b"
)

# 3. US Phone numbers (common international and national formats)
PHONE_PATTERN = re.compile(
    r"\b(?:\+?1[-.\s]?)?\(?[2-9]\d{2}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"
)

# 4. Social Security Numbers (SSN)
SSN_PATTERN = re.compile(
    r"\b\d{3}-\d{2}-\d{4}\b"
)

# 5. Bearer tokens, private keys, API secrets
BEARER_TOKEN_PATTERN = re.compile(
    r"(?i)(?:bearer\s+[a-zA-Z0-9_\-\.]{20,}|(?:api[_-]?key|secret|token)\s*[:=]\s*['\"]?[a-zA-Z0-9_\-\.]{16,}['\"]?)"
)


def _mask_card(match: re.Match) -> str:
    raw = match.group(0)
    digits = re.sub(r"\D", "", raw)
    # Validate length typical for payment cards (13-19 digits)
    if 13 <= len(digits) <= 19:
        last4 = digits[-4:]
        return f"****-****-****-{last4}"
    return raw


def mask_sensitive_data(text: str) -> str:
    """Masks PII, payment card numbers, emails, phone numbers, and secrets in text outputs.

    Args:
        text: The raw output text to sanitize.

    Returns:
        Sanitized text with sensitive data masked.
    """
    if not isinstance(text, str):
        return text

    # Mask payment cards
    sanitized = CARD_PATTERN.sub(_mask_card, text)

    # Mask emails
    sanitized = EMAIL_PATTERN.sub(lambda m: f"{m.group(0)[:2]}***@{m.group(0).split('@')[1]}", sanitized)

    # Mask SSN
    sanitized = SSN_PATTERN.sub("***-**-****", sanitized)

    # Mask Phone numbers
    sanitized = PHONE_PATTERN.sub("[REDACTED_PHONE]", sanitized)

    # Mask Bearer tokens / API secrets
    sanitized = BEARER_TOKEN_PATTERN.sub("[REDACTED_TOKEN]", sanitized)

    return sanitized


def sanitize_response_payload(payload: Any) -> Any:
    """Recursively sanitizes dictionary, list, or string payloads."""
    if isinstance(payload, str):
        return mask_sensitive_data(payload)
    elif isinstance(payload, dict):
        return {k: sanitize_response_payload(v) for k, v in payload.items()}
    elif isinstance(payload, list):
        return [sanitize_response_payload(item) for item in payload]
    return payload
