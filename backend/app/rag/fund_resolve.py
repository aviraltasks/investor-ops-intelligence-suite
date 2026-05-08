"""Resolve casual user phrases to manifest fund slugs (Groww scheme pages)."""

from __future__ import annotations

import re

from app.sources.manifest import FUND_SOURCES

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
    ),
    "parag-parikh-long-term-value-fund-direct-growth": (
        "parag parikh flexi cap",
        "parag parikh long term",
        "ppfas flexi",
    ),
}


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
