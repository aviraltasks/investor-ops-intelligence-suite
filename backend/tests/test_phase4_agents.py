"""Phase 4 tests: orchestrator + specialist agents through /api/chat."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import reset_settings
from app.db.session import reset_engine
from app.main import app


def _post_chat(client: TestClient, message: str, session_id: str = "s1", user_name: str = "Aviral") -> dict:
    r = client.post(
        "/api/chat",
        json={"message": message, "session_id": session_id, "user_name": user_name},
    )
    assert r.status_code == 200
    return r.json()


def test_chat_faq_path_has_rag_trace(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "phase4_faq.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("EMBEDDING_MODEL", "hash")
    reset_settings()
    reset_engine()

    with TestClient(app) as client:
        # Seed corpus quickly.
        ingest = client.post("/api/data/ingest")
        assert ingest.status_code == 200

        out = _post_chat(client, "What is exit load in SBI small cap fund?", session_id="faq-1")
        assert "traces" in out
        agents = [t["agent"] for t in out["traces"]]
        assert "orchestrator" in agents
        assert "rag_agent" in agents
        assert "Sources:" in out["response"] or "could not find reliable fund data" in out["response"]


def test_chat_booking_path_creates_draft(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "phase4_booking.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("EMBEDDING_MODEL", "hash")
    reset_settings()
    reset_engine()

    with TestClient(app) as client:
        proposed = _post_chat(
            client,
            "Please book an appointment for KYC tomorrow at 10 am",
            session_id="book-1",
        )
        assert proposed["payload"].get("status") == "awaiting_confirmation"
        assert "lock" in proposed["response"].lower() or "confirm" in proposed["response"].lower()
        out = _post_chat(client, "yes", session_id="book-1")
        payload = out["payload"]
        assert payload.get("booking_code", "").startswith("GRW-")
        assert "advisor_email_draft" in payload
        agents = [t["agent"] for t in out["traces"]]
        assert "scheduling_agent" in agents
        assert "email_drafting_agent" in agents


def test_chat_memory_continuity(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "phase4_memory.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("EMBEDDING_MODEL", "hash")
    reset_settings()
    reset_engine()

    with TestClient(app) as client:
        first = _post_chat(client, "I want to discuss withdrawals", session_id="mem-1")
        second = _post_chat(client, "book appointment tomorrow at 10 am for KYC", session_id="mem-1")
        assert second["payload"].get("status") == "awaiting_confirmation"
        third = _post_chat(client, "yes", session_id="mem-1")
        assert third["payload"].get("booking_code")
        mem_agents = [t["agent"] for t in second["traces"] if t["agent"] == "memory_agent"]
        assert len(mem_agents) >= 2  # load + save
