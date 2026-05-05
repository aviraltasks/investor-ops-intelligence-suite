"""Fetch sources, chunk, embed, and persist RAG rows."""

from __future__ import annotations

import logging
from collections.abc import Callable

import httpx
import numpy as np
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.models import RagChunk
from app.rag.chunking import chunk_text
from app.rag.embed import Embedder, get_embedder
from app.rag.extract import extract_text_from_bytes
from app.rag.http_client import new_client
from app.sources.manifest import EXTRA_GROWW_PAGES, FUND_SOURCES, SEBI_SOURCES

logger = logging.getLogger(__name__)


def _delete_chunks_for_urls(session: Session, urls: list[str]) -> None:
    if urls:
        session.execute(delete(RagChunk).where(RagChunk.source_url.in_(urls)))


def _embed_batch(embedder: Embedder, texts: list[str], batch_size: int = 32) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        emb = embedder.encode(batch)
        out.extend([row.tolist() for row in np.asarray(emb, dtype=np.float32)])
    return out


def ingest_url_list(
    session: Session,
    client: httpx.Client,
    embedder: Embedder,
    urls: list[str],
    layer: str,
    *,
    fund_slug: str | None = None,
    fund_display_name: str | None = None,
) -> int:
    """Fetch URLs, replace existing chunks for those URLs, return chunk count written."""
    _delete_chunks_for_urls(session, urls)
    session.commit()
    written = 0

    for url in urls:
        try:
            resp = client.get(url)
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            logger.warning("fetch failed url=%s err=%s", url, exc)
            continue

        try:
            text = extract_text_from_bytes(url, resp.content)
        except Exception as exc:  # noqa: BLE001
            logger.warning("extract failed url=%s err=%s", url, exc)
            continue

        chunks = chunk_text(text)
        if not chunks:
            continue

        embeddings = _embed_batch(embedder, chunks)
        for idx, (content, emb) in enumerate(zip(chunks, embeddings, strict=False)):
            session.add(
                RagChunk(
                    source_url=url,
                    layer=layer,
                    fund_slug=fund_slug,
                    fund_display_name=fund_display_name,
                    chunk_index=idx,
                    content=content,
                    embedding=emb,
                )
            )
            written += 1

    session.commit()
    return written


def ingest_groww_funds(session: Session, client: httpx.Client, embedder: Embedder) -> int:
    total = 0
    for fund in FUND_SOURCES:
        total += ingest_url_list(
            session,
            client,
            embedder,
            [fund.url],
            "groww",
            fund_slug=fund.slug,
            fund_display_name=fund.display_name,
        )
    return total


def ingest_sebi_pages(session: Session, client: httpx.Client, embedder: Embedder) -> int:
    urls = [s.url for s in SEBI_SOURCES]
    return ingest_url_list(session, client, embedder, urls, "sebi")


def ingest_extra_groww_pages(session: Session, client: httpx.Client, embedder: Embedder) -> int:
    return ingest_url_list(session, client, embedder, list(EXTRA_GROWW_PAGES), "extra")


def rag_stats(session: Session) -> dict[str, int]:
    return {
        "rag_chunks_total": session.scalar(select(func.count()).select_from(RagChunk)) or 0,
        "groww_chunks": session.scalar(select(func.count()).where(RagChunk.layer == "groww")) or 0,
        "sebi_chunks": session.scalar(select(func.count()).where(RagChunk.layer == "sebi")) or 0,
        "extra_chunks": session.scalar(select(func.count()).where(RagChunk.layer == "extra")) or 0,
    }


def run_full_ingest(
    session: Session,
    *,
    client_factory: Callable[[], httpx.Client] | None = None,
    embedder: Embedder | None = None,
) -> dict[str, int]:
    """Run fund + SEBI + extra ingestion. Reviews handled separately."""
    client_factory = client_factory or new_client
    embedder = embedder or get_embedder()

    with client_factory() as client:
        groww = ingest_groww_funds(session, client, embedder)
        sebi = ingest_sebi_pages(session, client, embedder)
        extra = ingest_extra_groww_pages(session, client, embedder)

    stats = rag_stats(session)
    stats["ingested_groww"] = groww
    stats["ingested_sebi"] = sebi
    stats["ingested_extra"] = extra
    return stats
