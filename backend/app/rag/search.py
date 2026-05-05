"""Vector search over stored chunks (cosine on normalized embeddings)."""

from __future__ import annotations

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import RagChunk
from app.rag.embed import Embedder


def search_chunks(
    session: Session,
    embedder: Embedder,
    query: str,
    top_k: int = 5,
    layer: str | None = None,
) -> list[dict]:
    """Return top_k chunks with scores. Full scan — OK for Phase 2 corpus size."""
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
    scores = (mat @ qv[0].astype(np.float32).T).ravel()
    order = np.argsort(-scores)[:top_k]

    out: list[dict] = []
    for idx in order:
        r = rows[int(idx)]
        out.append(
            {
                "id": r.id,
                "score": float(scores[int(idx)]),
                "source_url": r.source_url,
                "layer": r.layer,
                "fund_slug": r.fund_slug,
                "chunk_index": r.chunk_index,
                "content": r.content[:2000],
            }
        )
    return out
