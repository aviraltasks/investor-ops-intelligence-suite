"""Guards for TER/exit-load snippet quality, FAQ cache poisoning, and slug-wide chunk scans."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.agents import rag_agent as ra
from app.config import reset_settings
from app.db.models import RagChunk
from app.db.session import get_session_factory, reset_engine
from app.main import app
from app.rag.embed import get_embedder


def test_snippet_score_rejects_returns_leaderboard_row() -> None:
    bad = (
        "Sundaram Small Cap Fund Direct Growth +17.18% +21.94% 2,982.57 "
        "Nippon India Small Cap Fund Direct Growth +11.26% +21."
    )
    assert ra._snippet_score_expense_ratio(bad) < 0
    good = "Total expense ratio (TER) for direct plan is 0.72% as per latest factsheet."
    assert ra._snippet_score_expense_ratio(good) > 0


def test_cache_rejects_extraction_failure_and_poisoned_entries() -> None:
    ra.clear_faq_answer_cache()
    key = ra._cache_key("compare expense ratios of small cap funds")
    ra._FAQ_ANSWER_CACHE[key] = (
        "I found related sources in our index, but could not pull an exact figure from the text snippets we have.",
        ["https://example.com"],
    )
    assert ra._cache_get("compare expense ratios of small cap funds") is None
    assert key not in ra._FAQ_ANSWER_CACHE


def test_slug_wide_blob_finds_ter_when_vector_slice_is_noisy(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "rag_robust.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("EMBEDDING_MODEL", "hash")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    reset_settings()
    reset_engine()

    embedder = get_embedder()
    noisy = (
        "Peers: Sundaram Small Cap +17% +22% Nippon Small Cap +11% mixed category returns snapshot."
    )
    quiet_ter = "SBI Small Cap Fund Direct Growth total expense ratio (TER) for direct plan is 0.72%."
    emb_noisy = embedder.encode([noisy])[0].tolist()
    emb_ter = embedder.encode([quiet_ter])[0].tolist()

    SessionLocal = get_session_factory()
    with TestClient(app) as client:
        with SessionLocal() as session:
            session.add_all(
                [
                    RagChunk(
                        source_url="https://groww.in/mutual-funds/sbi-small-midcap-fund-direct-growth",
                        layer="groww",
                        fund_slug="sbi-small-midcap-fund-direct-growth",
                        fund_display_name="SBI Small Cap Fund",
                        chunk_index=0,
                        content=noisy,
                        embedding=emb_noisy,
                    ),
                    RagChunk(
                        source_url="https://groww.in/mutual-funds/sbi-small-midcap-fund-direct-growth",
                        layer="groww",
                        fund_slug="sbi-small-midcap-fund-direct-growth",
                        fund_display_name="SBI Small Cap Fund",
                        chunk_index=1,
                        content=quiet_ter,
                        embedding=emb_ter,
                    ),
                ]
            )
            session.commit()
        r = client.post(
            "/api/chat",
            json={
                "message": "expense ratio of SBI Small Cap",
                "session_id": "robust-ter",
                "user_name": "Test",
            },
        )
        assert r.status_code == 200
        body = r.json()["response"]
        assert "0.72%" in body
        assert "Sundaram" not in body
        assert "+17" not in body

