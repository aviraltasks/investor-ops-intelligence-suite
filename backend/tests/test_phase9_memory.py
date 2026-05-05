"""Phase 9 tests: short/long memory, recall, and PII-safe persistence."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import reset_settings
from app.db.models import MemoryFact
from app.db.session import get_session_factory, reset_engine
from app.main import app


def _chat(client: TestClient, message: str, session_id: str, user_name: str = "Aviral") -> dict:
    r = client.post("/api/chat", json={"message": message, "session_id": session_id, "user_name": user_name})
    assert r.status_code == 200
    return r.json()


def test_memory_recall_and_returning_user_context(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "phase9_memory.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("EMBEDDING_MODEL", "hash")
    reset_settings()
    reset_engine()

    with TestClient(app) as client:
        _chat(client, "I want to discuss withdrawals and timelines", session_id="voice-s1", user_name="Aviral")
        _chat(client, "Please book appointment tomorrow at 10 am for withdrawals", session_id="voice-s1", user_name="Aviral")
        _chat(client, "yes", session_id="voice-s1", user_name="Aviral")

        # New session with same user should be treated as returning user (cross-channel continuity proxy).
        greeting = _chat(client, "hi", session_id="text-s2", user_name="Aviral")
        assert "Welcome back Aviral" in greeting["response"]
        assert "Quick reminder: your booking GRW-" in greeting["response"]

        recall = _chat(client, "what did we discuss last time?", session_id="text-s2", user_name="Aviral")
        assert "Here is what we discussed recently" in recall["response"]
        assert "withdrawals" in recall["response"].lower()


def test_memory_fact_pii_scrub(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "phase9_pii.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("EMBEDDING_MODEL", "hash")
    reset_settings()
    reset_engine()

    with TestClient(app) as client:
        out = _chat(
            client,
            "my email is test.user@example.com and phone is +91 9876543210",
            session_id="pii-s1",
            user_name="Aviral",
        )
        assert "cannot process personal details in chat" in out["response"]

    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        last_fact = session.scalar(select(MemoryFact).order_by(MemoryFact.created_at.desc()).limit(1))
        # PII message should not be stored in chat memory at all after hardening.
        assert last_fact is None
