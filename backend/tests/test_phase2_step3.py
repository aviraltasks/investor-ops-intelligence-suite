"""Step-3 tests: review fetch fallback and persistence."""

from __future__ import annotations

from sqlalchemy import func, select

from app.config import reset_settings
from app.db.models import Review
from app.db.session import get_session_factory, init_db, reset_engine
from app.reviews.pipeline import (
    ReviewRecord,
    fetch_reviews_with_fallback,
    load_reviews_from_csv,
    persist_reviews,
)


def test_load_reviews_from_csv(tmp_path) -> None:
    csv_path = tmp_path / "fallback.csv"
    csv_path.write_text(
        "external_id,content,score,review_at\n"
        "a1,Slow login,2,2026-04-20T10:30:00\n"
        "a2,Great UI,5,2026-04-21T11:00:00\n",
        encoding="utf-8",
    )
    rows = load_reviews_from_csv(str(csv_path))
    assert len(rows) == 2
    assert rows[0].external_id == "a1"
    assert rows[1].score == 5.0


def test_fetch_reviews_with_fallback_uses_csv(tmp_path) -> None:
    csv_path = tmp_path / "fallback.csv"
    csv_path.write_text(
        "external_id,content,score,review_at\n"
        "b1,Withdrawal delayed,1,2026-04-23T08:00:00\n",
        encoding="utf-8",
    )

    def failing_fetcher(_app_id: str, _limit: int) -> list[ReviewRecord]:
        raise RuntimeError("rate limited")

    rows, source = fetch_reviews_with_fallback(
        app_id="com.nextbillion.groww",
        limit=50,
        fallback_csv=str(csv_path),
        play_fetcher=failing_fetcher,
    )
    assert source == "csv_fallback"
    assert len(rows) == 1
    assert rows[0].external_id == "b1"


def test_persist_reviews_insert_and_update(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "phase2_step3.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    reset_settings()
    reset_engine()
    init_db()

    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        first = [
            ReviewRecord(
                external_id="r1",
                content="Initial review",
                score=3.0,
                review_at=None,
                source="csv_fallback",
            )
        ]
        s1 = persist_reviews(session, first)
        assert s1["inserted"] == 1
        assert s1["updated"] == 0

        second = [
            ReviewRecord(
                external_id="r1",
                content="Updated review text",
                score=4.0,
                review_at=None,
                source="play_store",
            )
        ]
        s2 = persist_reviews(session, second)
        assert s2["inserted"] == 0
        assert s2["updated"] == 1

        total = session.scalar(select(func.count()).select_from(Review))
        assert total == 1
        r = session.scalar(select(Review).where(Review.external_id == "r1"))
        assert r is not None
        assert r.content == "Updated review text"
