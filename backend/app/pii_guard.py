"""Shared PII detection/scrubbing helpers for chat safety."""

from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", flags=re.IGNORECASE)
_PHONE_RE = re.compile(r"(?:\+91[\s-]?)?[6-9]\d{9}\b", flags=re.IGNORECASE)
_PAN_RE = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b", flags=re.IGNORECASE)
_AADHAAR_RE = re.compile(r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}\b", flags=re.IGNORECASE)


def contains_pii(text: str) -> bool:
    t = text or ""
    return any(p.search(t) for p in (_EMAIL_RE, _PHONE_RE, _PAN_RE, _AADHAAR_RE))


def scrub_pii(text: str) -> str:
    out = text or ""
    out = _EMAIL_RE.sub("[redacted-email]", out)
    out = _PHONE_RE.sub("[redacted-phone]", out)
    out = _PAN_RE.sub("[redacted-id]", out)
    out = _AADHAAR_RE.sub("[redacted-id]", out)
    return out.strip()
