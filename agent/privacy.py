"""Personal data stays out of logs and traces (Module 16, OWASP LLM02).

Traces are read by engineers, exported to monitoring tools and kept for months.
They need to show what the agent did, not who the customer is. redact() removes
the common identifiers from free text; redact_obj() also blanks fields whose
name says they hold personal data, wherever they appear in a nested record.
"""
from __future__ import annotations

import re

PATTERNS = [
    (re.compile(r"\b(?:\d[ -]?){13,16}\b"), "[card]"),
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[email]"),
    (re.compile(r"(?:\+44\s?7\d{3}|\b07\d{3})\s?\d{3}\s?\d{3}\b"), "[phone]"),
    (re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}\b"), "[postcode]"),
]
SENSITIVE_KEYS = {"email", "to", "to_addr", "address", "name", "phone", "card_last4"}


def redact(text: str) -> str:
    for pattern, label in PATTERNS:
        text = pattern.sub(label, text)
    return text


def redact_obj(value, key: str | None = None):
    if key in SENSITIVE_KEYS and value not in (None, ""):
        return "[redacted]"
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: redact_obj(v, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_obj(v) for v in value]
    return value
