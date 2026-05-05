"""Step-2 tests: chunk/extract/embed/ingest/search pipeline."""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from sqlalchemy import func, select

from app.config import reset_settings
from app.db.models import RagChunk
from app.db.session import get_session_factory, init_db, reset_engine
from app.rag.chunking import chunk_text
from app.rag.embed import HashEmbedder
from app.rag.ingest_pipeline import ingest_url_list, rag_stats
from app.rag.search import search_chunks


@dataclass
class DummyResponse:
    content: bytes
    status_code: int = 200

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("bad", request=None, response=None)


class DummyClient:
    def __init__(self, pages: dict[str, bytes]) -> None:
        self.pages = pages

    def get(self, url: str) -> DummyResponse:
        data = self.pages.get(url)
        if data is None:
            return DummyResponse(b"", status_code=404)
        return DummyResponse(data)


def test_chunk_text_overlap_behavior() -> None:
    text = "a " * 2000
    chunks = chunk_text(text, max_chars=200, overlap=50)
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)


def test_ingest_and_search_with_dummy_client(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "phase2_step2.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    reset_settings()
    reset_engine()
    init_db()

    page_url = "https://example.com/fund"
    html = b"<html><body><main>Expense ratio is low. Exit load applies for 1 year.</main></body></html>"
    client = DummyClient({page_url: html})

    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        n = ingest_url_list(
            session,
            client=client,
            embedder=HashEmbedder(),
            urls=[page_url],
            layer="groww",
            fund_slug="test-fund",
            fund_display_name="Test Fund",
        )
        assert n >= 1

        total = session.scalar(select(func.count()).select_from(RagChunk))
        assert total == n

        hits = search_chunks(session, HashEmbedder(), query="exit load", top_k=3, layer="groww")
        assert len(hits) >= 1
        assert hits[0]["layer"] == "groww"

        stats = rag_stats(session)
        assert stats["rag_chunks_total"] == n
        assert stats["groww_chunks"] == n
