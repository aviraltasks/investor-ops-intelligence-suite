"""Step-1 tests: deps/models/session/manifest wiring."""

from __future__ import annotations

from sqlalchemy import func, select

from app.config import reset_settings
from app.db.models import RagChunk, Review
from app.db.session import get_session_factory, init_db, reset_engine
from app.sources.manifest import FUND_SOURCES, SEBI_SOURCES, all_manifest_urls


def test_manifest_counts() -> None:
    assert len(FUND_SOURCES) == 15
    assert len(SEBI_SOURCES) == 9
    assert len(all_manifest_urls()) >= 31


def test_db_init_and_insert(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "phase2_step1.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    reset_settings()
    reset_engine()

    init_db()
    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        session.add(
            RagChunk(
                source_url="https://example.com/a",
                layer="groww",
                fund_slug="abc",
                fund_display_name="ABC",
                chunk_index=0,
                content="hello",
                embedding=[0.1, 0.2],
            )
        )
        session.add(
            Review(
                external_id="r1",
                content="great app",
                score=5.0,
                source="csv_fallback",
            )
        )
        session.commit()

        rag_count = session.scalar(select(func.count()).select_from(RagChunk))
        review_count = session.scalar(select(func.count()).select_from(Review))
        assert rag_count == 1
        assert review_count == 1
