"""Vector search over stored chunks (cosine on normalized embeddings)."""

from __future__ import annotations

import re

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import RagChunk
from app.rag.embed import Embedder
from app.sources.manifest import FUND_SOURCES

# When fund-specific or comparative metric context applies: lift scheme pages, sink category hubs.
GROWW_LAYER_SCORE_MULT = 1.3
EXTRA_LAYER_SCORE_MULT = 0.7
FUND_SLUG_PREF_MULT = 1.55  # When query resolves to a manifest fund, lift its scheme chunks

_DISPLAY_SUFFIXES = (
    " fund direct growth",
    " direct growth",
    " fund direct plan growth",
)

_PURE_METRIC_EDUCATION_RE = re.compile(
    r"^\s*(what\s+is|what\s+are|what\'s|define|explain|meaning\s+of)\s+(the\s+)?("
    r"nav|net\s+asset\s+value|expense\s+ratio|expense\s+ratios|exit\s+load|aum|assets\s+under\s+management"
    r")\s*[\?\.!]?\s*$",
    re.IGNORECASE | re.DOTALL,
)


def _fund_display_short(display_name: str) -> str:
    d = display_name.strip().lower()
    for suf in _DISPLAY_SUFFIXES:
        if d.endswith(suf):
            d = d[: -len(suf)].strip()
            break
    return d


def _query_mentions_manifest_fund(query: str) -> bool:
    ql = query.lower()
    for fund in FUND_SOURCES:
        short = _fund_display_short(fund.display_name)
        if len(short) >= 8 and short in ql:
            return True
        slug_words = fund.slug.replace("-", " ")
        if len(slug_words) >= 10 and slug_words in ql:
            return True
    return False


def _query_has_metric_keywords(query: str) -> bool:
    ql = query.lower()
    if "expense ratio" in ql or "exit load" in ql:
        return True
    if re.search(r"\baum\b", ql):
        return True
    return bool(re.search(r"\bnav\b", ql))


def fund_metric_layer_boost_applies(query: str) -> bool:
    """True when we should prefer groww scheme chunks over generic Groww category (extra) pages."""
    q = (query or "").strip()
    if not q:
        return False
    if _query_mentions_manifest_fund(q):
        return True
    if not _query_has_metric_keywords(q):
        return False
    if _PURE_METRIC_EDUCATION_RE.match(q):
        return False
    return True


def search_chunks(
    session: Session,
    embedder: Embedder,
    query: str,
    top_k: int = 5,
    layer: str | None = None,
    preferred_fund_slug: str | None = None,
) -> list[dict]:
    """Return top_k chunks with scores. Full scan — OK for Phase 2 corpus size.

    When ``layer`` is None and the query looks fund- or metric-comparison-driven,
    cosine similarity for ``groww`` rows is multiplied by `GROWW_LAYER_SCORE_MULT` and
    ``extra`` rows by `EXTRA_LAYER_SCORE_MULT`; other layers unchanged.

    When ``preferred_fund_slug`` is set (resolved manifest fund), matching ``groww``
    chunks for that slug get an extra multiplier so casual fund names still retrieve
    the right scheme page.

    The returned ``score`` is this adjusted ranking score (not raw cosine).
    """
    q = query.strip()
    if not q:
        return []
    qv = embedder.encode([q])
    if qv.size == 0:
        return []

    stmt = select(RagChunk).where(RagChunk.embedding.is_not(None))
    if layer:
        stmt = stmt.where(RagChunk.layer == layer)
    rows = list(session.scalars(stmt))

    if not rows:
        return []

    mat = np.asarray([r.embedding for r in rows], dtype=np.float32)
    # cosine similarity == dot product when vectors are normalized
    scores = (mat @ qv[0].astype(np.float32).T).ravel().astype(np.float64)
    rank_scores = scores.copy()
    apply_boost = layer is None and fund_metric_layer_boost_applies(q)
    pref = (preferred_fund_slug or "").strip()
    if apply_boost:
        for i, r in enumerate(rows):
            if r.layer == "groww":
                rank_scores[i] *= GROWW_LAYER_SCORE_MULT
            elif r.layer == "extra":
                rank_scores[i] *= EXTRA_LAYER_SCORE_MULT
    if pref:
        for i, r in enumerate(rows):
            if r.layer == "groww" and (r.fund_slug or "").strip() == pref:
                rank_scores[i] *= FUND_SLUG_PREF_MULT
    order = np.argsort(-rank_scores)[:top_k]

    out: list[dict] = []
    for idx in order:
        r = rows[int(idx)]
        out.append(
            {
                "id": r.id,
                "score": float(rank_scores[int(idx)]),
                "source_url": r.source_url,
                "layer": r.layer,
                "fund_slug": r.fund_slug,
                "chunk_index": r.chunk_index,
                "content": r.content[:2000],
            }
        )
    return out
