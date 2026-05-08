"""Resolve casual user phrases to manifest fund slugs (Groww scheme pages)."""

from __future__ import annotations

import re

from app.sources.manifest import FUND_SOURCES, FundSource

_DISPLAY_SUFFIXES = (
    " fund direct growth",
    " direct growth",
    " fund direct plan growth",
)


def _display_short(display_name: str) -> str:
    d = display_name.strip().lower()
    for suf in _DISPLAY_SUFFIXES:
        if d.endswith(suf):
            d = d[: -len(suf)].strip()
            break
    return d


# Extra substrings that users type but are not full official names (longest matches win).
_EXTRA_PHRASES: dict[str, tuple[str, ...]] = {
    "uti-nifty-fund-direct-growth": (
        "uti nifty 50 index fund direct growth",
        "uti nifty 50 index fund",
        "uti nifty 50 index",
        "uti nifty 50",
        "uti nifty index",
        "nifty 50 index uti",
    ),
    "sbi-nifty-index-fund-direct-growth": (
        "sbi nifty index fund",
        "sbi nifty index",
        "sbi nifty 50",
        "sbi nifty index fund direct growth",
    ),
    "sbi-small-midcap-fund-direct-growth": (
        "sbi small cap fund",
        "sbi small cap",
    ),
    "parag-parikh-long-term-value-fund-direct-growth": (
        "parag parikh flexi cap",
        "parag parikh long term",
        "ppfas flexi",
    ),
    "hdfc-equity-fund-direct-growth": ("hdfc flexi cap",),
    "nippon-india-large-cap-fund-direct-growth": ("nippon india large cap",),
    "kotak-midcap-fund-direct-growth": ("kotak small cap",),
    "quant-small-cap-fund-direct-plan-growth": ("quant small cap",),
    "canara-robeco-large-cap-fund-direct-growth": ("canara robeco large cap", "canara robeco bluechip"),
    "icici-prudential-long-term-equity-fund-tax-saving-direct-growth": (
        "icici prudential elss",
        "icici elss",
    ),
}


def resolve_manifest_funds_ordered(query: str) -> list[FundSource]:
    """
    Detect every manifest fund mentioned in user text, left-to-right, without overlapping spans.

    Used for comparisons like “NAV of Kotak Small Cap and Quant Small Cap”.
    """
    ql = re.sub(r"\s+", " ", (query or "").lower()).strip()
    if not ql:
        return []

    spans: list[tuple[int, int, FundSource]] = []

    def add_span(start: int, end: int, fund: FundSource) -> None:
        if end > start:
            spans.append((start, end, fund))

    for fund in FUND_SOURCES:
        phrases: list[str] = []
        dn = fund.display_name.lower()
        phrases.append(dn)
        short = _display_short(fund.display_name)
        if len(short) >= 8:
            phrases.append(short)
        spaced = fund.slug.replace("-", " ")
        if len(spaced) >= 14:
            phrases.append(spaced)
        for extra in _EXTRA_PHRASES.get(fund.slug, ()):
            phrases.append(extra)
        seen_p: set[str] = set()
        for p in phrases:
            pl = p.strip().lower()
            if len(pl) < 6 or pl in seen_p:
                continue
            seen_p.add(pl)
            start = 0
            while True:
                i = ql.find(pl, start)
                if i < 0:
                    break
                add_span(i, i + len(pl), fund)
                start = i + 1

    spans.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    used: list[tuple[int, int]] = []
    ordered: list[FundSource] = []
    seen_slug: set[str] = set()

    for s, e, fund in spans:
        if fund.slug in seen_slug:
            continue
        overlap = any(not (e <= u[0] or s >= u[1]) for u in used)
        if overlap:
            continue
        used.append((s, e))
        seen_slug.add(fund.slug)
        ordered.append(fund)

    return ordered


def resolve_manifest_fund(query: str) -> tuple[str | None, str | None]:
    """
    Return (fund_slug, canonical_scheme_url) from user text, or (None, None).

    Chooses the longest matching phrase so partial tokens don't steal resolution.
    """
    ql = re.sub(r"\s+", " ", (query or "").lower()).strip()
    if not ql:
        return None, None

    scored: list[tuple[int, FundSource]] = []

    for fund in FUND_SOURCES:
        dn = fund.display_name.lower()
        if dn in ql:
            scored.append((len(dn), fund))
        short = _display_short(fund.display_name)
        if len(short) >= 10 and short in ql:
            scored.append((len(short), fund))
        spaced = fund.slug.replace("-", " ")
        if len(spaced) >= 14 and spaced in ql:
            scored.append((len(spaced), fund))

    for slug, phrases in _EXTRA_PHRASES.items():
        for p in phrases:
            if p in ql:
                fund = next((f for f in FUND_SOURCES if f.slug == slug), None)
                if fund:
                    scored.append((len(p), fund))

    if not scored:
        return None, None

    scored.sort(key=lambda x: (-x[0], x[1].slug))
    best = scored[0][1]
    return best.slug, best.url
