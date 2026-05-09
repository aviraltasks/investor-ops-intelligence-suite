"""Parse user utterances into IST weekday booking slots with guardrails.

All comparisons use naive local datetimes (project assumes IST-style advisor hours).
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

# Monday = 0
_WEEKDAY_NAMES: tuple[tuple[str, int], ...] = (
    ("monday", 0),
    ("tuesday", 1),
    ("wednesday", 2),
    ("thursday", 3),
    ("friday", 4),
    ("mon", 0),
    ("tue", 1),
    ("wed", 2),
    ("thu", 3),
    ("fri", 4),
    ("thurs", 3),
    ("tues", 1),
)

_MONTH_WORDS: dict[str, int] = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

_OPEN_H = 9
_CLOSE_H = 18  # inclusive through 18:00 exactly


def _strip_booking_codes(text: str) -> str:
    s = re.sub(r"\bGRW-W-[A-Z0-9]{4}\b", " ", text, flags=re.IGNORECASE)
    return re.sub(r"\bGRW-[A-Z0-9]{4}\b", " ", s, flags=re.IGNORECASE)


def _normalize(text: str) -> str:
    t = text.lower()
    t = re.sub(r"\ba\.\s*m\.?\b", "am", t)
    t = re.sub(r"\bp\.\s*m\.?\b", "pm", t)
    weekday_typo_map = {
        "thurdfay": "thursday",
        "wedensday": "wednesday",
        "moday": "monday",
        "tueday": "tuesday",
        "firday": "friday",
    }
    for wrong, right in weekday_typo_map.items():
        t = re.sub(rf"\b{re.escape(wrong)}\b", right, t)
    # Common month mis-hearing / typo from voice (STT)
    t = re.sub(r"\bmaize\b", "may", t)
    return t


def _try_parse_iso_date(t: str) -> tuple[date | None, str]:
    m = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", t)
    if not m:
        return None, t
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        out = date(y, mo, d)
    except ValueError:
        return None, t
    span = m.span()
    return out, t[: span[0]] + " " + t[span[1] :]


def _month_from_token(tok: str) -> int | None:
    tok = tok.lower().strip(".,;")
    if not tok:
        return None
    if tok in _MONTH_WORDS:
        return _MONTH_WORDS[tok]
    for k, v in _MONTH_WORDS.items():
        if k.startswith(tok) and len(tok) >= 3:
            return v
    return None


def _try_parse_slash_date(t: str, now: datetime) -> tuple[date | None, str]:
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", t)
    if not m:
        return None, t
    a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 100:
        y += 2000
    # India-style DD/MM/YYYY when ambiguous prefer DD/MM
    if a > 12:
        day, month = a, b
    elif b > 12:
        month, day = a, b
    else:
        day, month = a, b
    try:
        out = date(y, month, day)
    except ValueError:
        return None, t
    span = m.span()
    return out, t[: span[0]] + " " + t[span[1] :]


def _try_parse_named_month_date(t: str) -> tuple[date | None, str]:
    # 12 may 2026
    m = re.search(
        r"\b(\d{1,2})[\s.,/-]+([a-z]{3,9})[\s.,/-]+(20\d{2})\b",
        t,
        flags=re.IGNORECASE,
    )
    if m:
        day = int(m.group(1))
        mon = _month_from_token(m.group(2))
        year = int(m.group(3))
        if mon is None:
            return None, t
        try:
            out = date(year, mon, day)
        except ValueError:
            return None, t
        span = m.span()
        return out, t[: span[0]] + " " + t[span[1] :]
    # may 12 2026 / may 12th, 2026
    m2 = re.search(
        r"\b([a-z]{3,9})[\s.,]+(\d{1,2})(?:st|nd|rd|th)?[\s.,]+(20\d{2})\b",
        t,
        flags=re.IGNORECASE,
    )
    if m2:
        mon = _month_from_token(m2.group(1))
        day = int(m2.group(2))
        year = int(m2.group(3))
        if mon is None:
            return None, t
        try:
            out = date(year, mon, day)
        except ValueError:
            return None, t
        span = m2.span()
        return out, t[: span[0]] + " " + t[span[1] :]
    return None, t


def _next_named_month_day(day: int, month: int, now: datetime) -> date | None:
    year = now.year
    for _ in range(2):
        try:
            cand = date(year, month, day)
        except ValueError:
            return None
        if cand >= now.date():
            return cand
        year += 1
    return None


def _try_parse_named_month_date_no_year(t: str, now: datetime) -> tuple[date | None, str]:
    # 26 may / 26th may / 14th of may (optional "of" between day and month)
    m = re.search(
        r"\b(\d{1,2})(?:st|nd|rd|th)?(?:\s+of\s+|[\s.,/-]+)([a-z]{3,9})\b",
        t,
        flags=re.IGNORECASE,
    )
    if m:
        day = int(m.group(1))
        mon = _month_from_token(m.group(2))
        if mon is None:
            return None, t
        out = _next_named_month_day(day, mon, now)
        if out is None:
            return None, t
        span = m.span()
        return out, t[: span[0]] + " " + t[span[1] :]
    # may 26 / may 26th
    m2 = re.search(r"\b([a-z]{3,9})[\s.,/-]+(\d{1,2})(?:st|nd|rd|th)?\b", t, flags=re.IGNORECASE)
    if m2:
        mon = _month_from_token(m2.group(1))
        day = int(m2.group(2))
        if mon is None:
            return None, t
        out = _next_named_month_day(day, mon, now)
        if out is None:
            return None, t
        span = m2.span()
        return out, t[: span[0]] + " " + t[span[1] :]
    return None, t


def _roll_to_weekday(d: date) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _parse_clock_from_fragment(work: str) -> tuple[int | None, int | None]:
    """Return hour (0-23), minute on success."""
    t = work.lower()
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", t)
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2) or 0)
        ampm = m.group(3)
        if ampm == "pm" and hh < 12:
            hh += 12
        if ampm == "am" and hh == 12:
            hh = 0
        return hh, mm
    compact = re.search(r"\b(\d{3,4})\s*(am|pm)\b", t)
    if compact:
        raw = compact.group(1)
        ampm = compact.group(2)
        if len(raw) == 3:
            hh = int(raw[0])
            mm = int(raw[1:])
        else:
            hh = int(raw[:2])
            mm = int(raw[2:])
        if ampm == "pm" and hh < 12:
            hh += 12
        if ampm == "am" and hh == 12:
            hh = 0
        return hh, mm
    # Plain clock without am/pm is ambiguous if dates use small integers — avoid eating "12" from "12 may"
    m2 = re.search(r"\b(\d{1,2})(:(\d{2}))?\b(?=\s*(?:ist\b|hrs|hours|o'clock)|\s*$)", t)
    if m2 and (m2.group(2) or "ist" in t):
        return int(m2.group(1)), int(m2.group(3) or 0)
    return None, None


def _parse_vague_time_hint(text: str) -> tuple[int | None, int | None]:
    t = text.lower()
    if "end of day" in t:
        return 17, 0
    if "after lunch" in t:
        return 13, 0
    if "morning" in t:
        return 10, 0
    if "afternoon" in t:
        return 14, 0
    if "evening" in t:
        return 16, 0
    return None, None


def _weekday_anchor(t: str, now: datetime, hh: int, mm: int) -> date | None:
    for name, wd in sorted(_WEEKDAY_NAMES, key=lambda x: -len(x[0])):
        if re.search(rf"\b{re.escape(name)}\b", t):
            d0 = now.date()
            for add in range(14):
                cand = d0 + timedelta(days=add)
                if cand.weekday() != wd or cand.weekday() >= 5:
                    continue
                dt = datetime(cand.year, cand.month, cand.day, hh, mm)
                if dt >= now:
                    return cand
            return None
    return None


def _explicit_date_heuristic(t: str) -> bool:
    if re.search(r"\b20\d{2}-\d{2}-\d{2}\b", t):
        return True
    if re.search(r"\b\d{1,2}[\s.,/-]+[a-z]{3,9}[\s.,/-]+20\d{2}\b", t, re.I):
        return True
    if re.search(r"\b[a-z]{3,9}[\s.,]+\d{1,2}(?:st|nd|rd|th)?[\s.,]+20\d{2}\b", t, re.I):
        return True
    if re.search(r"\b\d{1,2}[/-]\d{1,2}[/-]20\d{2}\b", t):
        return True
    return False


def resolve_booking_slot(
    text: str,
    *,
    now: datetime | None = None,
    max_days_ahead: int = 120,
) -> tuple[tuple[str, str] | None, str]:
    """Return ((YYYY-MM-DD, 'HH:MM IST'), reason_code). reason_code 'ok' on success."""
    now = now or datetime.now()
    raw = _strip_booking_codes(text or "")
    t = _normalize(raw)
    if not t.strip():
        return None, "missing_time"

    if any(x in t for x in ["sometime", "whenever", "soon"]):
        return None, "ambiguous_time"
    if any(x in t for x in ["yesterday", "last monday", "last week"]):
        return None, "past_time"
    if any(x in t for x in ["saturday", "sunday", "weekend"]):
        return None, "weekend"

    work = t
    anchor: date | None = None
    has_named_date = False

    d_iso, work = _try_parse_iso_date(work)
    if d_iso:
        anchor, has_named_date = d_iso, True
    if anchor is None:
        d_slash, work = _try_parse_slash_date(work, now)
        if d_slash:
            anchor, has_named_date = d_slash, True
    if anchor is None:
        d_nm, work = _try_parse_named_month_date(work)
        if d_nm:
            anchor, has_named_date = d_nm, True
    if anchor is None:
        d_nm_no_year, work = _try_parse_named_month_date_no_year(work, now)
        if d_nm_no_year:
            anchor, has_named_date = d_nm_no_year, True

    used_vague_time = False
    hh, mm = _parse_clock_from_fragment(work)
    if hh is None:
        hh, mm = _parse_vague_time_hint(t)
        if hh is None:
            return None, "missing_time"
        used_vague_time = True

    wd_match_date = _weekday_anchor(t, now, hh, mm)

    has_relative_hint = False
    if anchor is None:
        if "tomorrow" in t:
            anchor = _roll_to_weekday(now.date() + timedelta(days=1))
            has_relative_hint = True
        elif "today" in t:
            anchor = now.date()
            has_relative_hint = True
        elif "next week" in t:
            anchor = _roll_to_weekday(now.date() + timedelta(days=7))
            has_relative_hint = True
        elif wd_match_date is not None:
            anchor = wd_match_date
            has_relative_hint = True

    if anchor is None:
        anchor = now.date()

    has_date_hint = (
        has_named_date
        or has_relative_hint
        or _explicit_date_heuristic(t)
        or any(x in t for x in ("tomorrow", "today", "next week"))
        or (wd_match_date is not None)
    )

    dt = datetime(anchor.year, anchor.month, anchor.day, hh, mm)
    if used_vague_time and not has_date_hint:
        return None, "missing_date"

    if anchor < now.date():
        return None, "past_time"
    if dt.weekday() >= 5:
        return None, "weekend"
    if hh < _OPEN_H or hh > _CLOSE_H or (hh == _CLOSE_H and mm > 0):
        return None, "outside_hours"
    if dt < now:
        if not has_date_hint:
            return None, "missing_date"
        return None, "past_time"

    last_ok = now.date() + timedelta(days=max(1, max_days_ahead))
    if anchor > last_ok:
        return None, "too_far_future"

    return (dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M IST")), "ok"


def message_looks_like_slot_refinement(text: str) -> bool:
    """User is likely specifying/changing a slot (not a long unrelated chat)."""
    raw = (text or "").strip()
    if not raw or len(raw) > 220:
        return False
    t = raw.lower()

    if re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)\b", t):
        return True
    if re.search(r"\b\d{1,2}\s*(am|pm)\b", t):
        return True
    if re.search(r"\b\d{3,4}\s*(am|pm)\b", t):
        return True
    if re.search(r"\b20\d{2}-\d{2}-\d{2}\b", t):
        return True
    if re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*[\s.,]+\d{1,2}", t):
        return True
    if re.search(r"\b\d{1,2}[\s.,/-]+(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\b", t):
        return True
    if re.search(r"\b\d{1,2}[/-]\d{1,2}[/-]20\d{2}\b", t):
        return True
    if any(w in t for w in ("tomorrow", "today", "next week")) and re.search(r"\d", t):
        return True
    if any(re.search(rf"\b{re.escape(w)}\b", t) for w, _ in _WEEKDAY_NAMES if len(w) > 3) and re.search(
        r"\d{1,2}\s*(am|pm|:)", t
    ):
        return True
    if any(k in t for k in ("morning", "afternoon", "evening", "after lunch", "end of day")):
        return True
    return False
