"""Phase 14 tests: deterministic FAQ fast-path and concise fallback behavior."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import reset_settings
from app.db.models import RagChunk
from app.db.session import get_session_factory, reset_engine
from app.main import app
from app.rag.embed import get_embedder


def _post_chat(client: TestClient, message: str, session_id: str = "p14", user_name: str = "Aviral") -> dict:
    r = client.post(
        "/api/chat",
        json={"message": message, "session_id": session_id, "user_name": user_name},
    )
    assert r.status_code == 200
    return r.json()


def _seed_chunks() -> None:
    embedder = get_embedder()
    texts = [
        "Mirae Asset ELSS Tax Saver Fund Direct Growth has an exit load of 1% if redeemed within 1 year from allotment.",
        "Exit load is charged to discourage short-term redemptions and stabilize fund management.",
        "Current NAV is 123.45 as per latest published update.",
        "SBI Small Cap Fund Direct Growth expense ratio is 0.72% for direct plan.",
        "Kotak Small Cap Fund Direct Growth expense ratio is 0.89% for direct plan.",
        "Quant Small Cap Fund Direct Growth expense ratio is 0.64% for direct plan.",
    ]
    embs = embedder.encode(texts)
    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        session.add_all(
            [
                RagChunk(
                    source_url="https://groww.in/mutual-funds/mirae-asset-elss-tax-saver-fund-direct-growth",
                    layer="groww",
                    fund_slug="mirae-asset-elss-tax-saver-fund-direct-growth",
                    fund_display_name="Mirae Asset ELSS Tax Saver",
                    chunk_index=0,
                    content=texts[0],
                    embedding=embs[0].tolist(),
                ),
                RagChunk(
                    source_url="https://investor.sebi.gov.in/exit_load.html",
                    layer="sebi",
                    fund_slug=None,
                    fund_display_name=None,
                    chunk_index=0,
                    content=texts[1],
                    embedding=embs[1].tolist(),
                ),
                RagChunk(
                    source_url="https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth",
                    layer="groww",
                    fund_slug="hdfc-equity-fund-direct-growth",
                    fund_display_name="HDFC Flexi Cap Fund",
                    chunk_index=0,
                    content=texts[2],
                    embedding=embs[2].tolist(),
                ),
                RagChunk(
                    source_url="https://groww.in/mutual-funds/sbi-small-midcap-fund-direct-growth",
                    layer="groww",
                    fund_slug="sbi-small-midcap-fund-direct-growth",
                    fund_display_name="SBI Small Cap Fund",
                    chunk_index=0,
                    content=texts[3],
                    embedding=embs[3].tolist(),
                ),
                RagChunk(
                    source_url="https://groww.in/mutual-funds/kotak-midcap-fund-direct-growth",
                    layer="groww",
                    fund_slug="kotak-midcap-fund-direct-growth",
                    fund_display_name="Kotak Small Cap Fund",
                    chunk_index=0,
                    content=texts[4],
                    embedding=embs[4].tolist(),
                ),
                RagChunk(
                    source_url="https://groww.in/mutual-funds/quant-small-cap-fund-direct-plan-growth",
                    layer="groww",
                    fund_slug="quant-small-cap-fund-direct-plan-growth",
                    fund_display_name="Quant Small Cap Fund",
                    chunk_index=0,
                    content=texts[5],
                    embedding=embs[5].tolist(),
                ),
            ]
        )
        session.commit()


def test_deterministic_exit_load_answer_is_concise(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "phase14_exit.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("EMBEDDING_MODEL", "hash")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    reset_settings()
    reset_engine()

    with TestClient(app) as client:
        _seed_chunks()
        out = _post_chat(client, "What is the exit load for Mirae ELSS and why is it charged?", session_id="p14-exit")
        text = out["response"]
        assert "temporarily unavailable" not in text.lower()
        assert "1%" in text
        assert "Sources:" in text
        assert text.count("https://") <= 2
        assert len(text) < 520


def test_deterministic_nav_answer_uses_value(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "phase14_nav.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("EMBEDDING_MODEL", "hash")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    reset_settings()
    reset_engine()

    with TestClient(app) as client:
        _seed_chunks()
        out = _post_chat(client, "What is the NAV for HDFC Flexi Cap?", session_id="p14-nav")
        text = out["response"]
        assert "123.45" in text
        assert text.count("https://") <= 2
        assert "I found related information" not in text


def test_cached_faq_path_is_used(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "phase14_cache.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("EMBEDDING_MODEL", "hash")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    reset_settings()
    reset_engine()

    with TestClient(app) as client:
        _seed_chunks()
        q = "What is the NAV for HDFC Flexi Cap?"
        _ = _post_chat(client, q, session_id="p14-cache-1")
        out2 = _post_chat(client, q, session_id="p14-cache-2")
        rag_steps = [t for t in out2["traces"] if t["agent"] == "rag_agent"]
        assert any("cache_hit" in (t.get("outcome") or "") for t in rag_steps)


def test_deterministic_expense_ratio_comparison(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "phase14_compare.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("EMBEDDING_MODEL", "hash")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    reset_settings()
    reset_engine()

    with TestClient(app) as client:
        _seed_chunks()
        out = _post_chat(
            client,
            "Compare expense ratio of SBI Small Cap, Kotak Small Cap and Quant Small Cap",
            session_id="p14-compare",
        )
        text = out["response"]
        assert "expense ratio comparison" in text.lower()
        assert "0.72%" in text and "0.89%" in text and "0.64%" in text
        assert "Sources:" in text
