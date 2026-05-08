"""Shared detection for Groww-style support topics (KYC, SIP, statements, etc.)."""

from __future__ import annotations

import re


def _normalize_topic_text(text: str) -> str:
    t = (text or "").strip().lower()
    t = t.replace("&", " and ")
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def match_quick_topic_chip_label(text: str) -> str | None:
    """Recognize bare quick-topic chip labels (without 'help with' phrasing)."""
    t = _normalize_topic_text(text)
    if not t:
        return None
    if t in {"kyc onboarding", "kyc and onboarding"}:
        return "KYC & Onboarding"
    if t in {"sip mandates", "sip and mandates"}:
        return "SIP & Mandates"
    if t in {"statements tax documents", "statements and tax documents", "statement and tax document"}:
        return "Statements & Tax Documents"
    if t in {"withdrawals timelines", "withdrawals and timelines"}:
        return "Withdrawals & Timelines"
    if t in {"account changes nominee updates", "account changes and nominee updates"}:
        return "Account Changes & Nominee Updates"
    return None


def looks_like_topic_help_query(text: str) -> bool:
    """True when the user is asking for help/info on a support topic (not e.g. a bare keyword)."""
    ql = (text or "").strip().lower()
    if not ql:
        return False
    if "help with" in ql or "i want help" in ql:
        return True
    if "give me" in ql or "tell me about" in ql:
        return True
    if ql.startswith("i want ") or re.search(r"\bi want\b", ql):
        return True
    if "need help" in ql or "need info" in ql:
        return True
    if ql.startswith("about ") or ql.startswith("info on ") or ql.startswith("information on "):
        return True
    return False


def match_quick_support_topic_label(text: str) -> str | None:
    """Map message to chip-style topic label when it looks like a support-topic request."""
    chip_label = match_quick_topic_chip_label(text)
    if chip_label:
        return chip_label
    if not looks_like_topic_help_query(text):
        return None
    t = text.lower()
    if "kyc" in t or "onboarding" in t:
        return "KYC & Onboarding"
    if "sip" in t or "mandate" in t:
        return "SIP & Mandates"
    if "statement" in t or "tax document" in t or "form 16" in t or ("statement" in t and "tax" in t):
        return "Statements & Tax Documents"
    if "withdraw" in t or "withdrawal" in t:
        return "Withdrawals & Timelines"
    if "account change" in t or "account changes" in t or "nominee" in t:
        return "Account Changes & Nominee Updates"
    # "timelines" alone is too noisy; pair with withdrawal-ish context
    if "timeline" in t and ("withdraw" in t or "payout" in t or "redemption" in t or "money" in t):
        return "Withdrawals & Timelines"
    return None


def message_suggests_support_faq(text: str, *, scheduling_focus: bool) -> bool:
    """Heuristic: user likely wants FAQ/RAG for ops topics (skip when scheduling a meeting)."""
    if scheduling_focus:
        return False
    m = (text or "").lower()
    if _contains_any(m, ["kyc", "onboarding", "mandate", "nominee", "account change", "account changes"]):
        return True
    if re.search(r"\bsip\b", m):
        return True
    if ("statement" in m and "tax" in m) or "tax document" in m or "form 16" in m:
        return True
    if _contains_any(m, ["withdraw", "withdrawal"]):
        return True
    return False


def _contains_any(haystack: str, needles: list[str]) -> bool:
    return any(n in haystack for n in needles)
