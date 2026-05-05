"""What-to-prepare scheduling intent (SCRIPT_FLOW Flow 6)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import reset_settings
from app.db.session import reset_engine
from app.main import app


def _chat(client: TestClient, session_id: str, msg: str) -> dict:
    r = client.post(
        "/api/chat",
        json={"session_id": session_id, "user_name": "Aviral", "message": msg},
    )
    assert r.status_code == 200
    return r.json()


def test_prepare_uses_booking_topic(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "p13_prep_book.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("EMBEDDING_MODEL", "hash")
    reset_settings()
    reset_engine()

    with TestClient(app) as client:
        _chat(client, "p13-1", "Book appointment tomorrow at 10 am for KYC")
        _chat(client, "p13-1", "yes")
        out = _chat(client, "p13-1", "What should I prepare for my appointment?")
        assert "PAN" in out["response"] or "KYC" in out["response"]
        assert "investor.sebi.gov.in" in out["response"]
        assert any(t.get("outcome") == "prepare_checklist" for t in out["traces"])


def test_prepare_topic_from_message(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "p13_prep_msg.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("EMBEDDING_MODEL", "hash")
    reset_settings()
    reset_engine()

    with TestClient(app) as client:
        out = _chat(client, "p13-2", "What to bring for a SIP & Mandates session?")
        assert "SIP" in out["response"] or "mandate" in out["response"].lower()
        assert "investor.sebi.gov.in" in out["response"]


def test_prepare_asks_topic_when_unknown(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "p13_prep_ask.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("EMBEDDING_MODEL", "hash")
    reset_settings()
    reset_engine()

    with TestClient(app) as client:
        out = _chat(client, "p13-3", "What should I prepare?")
        assert "Which topic" in out["response"] or "topic" in out["response"].lower()


def test_pulse_generate_returns_400_with_message(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "p13_pulse.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("EMBEDDING_MODEL", "hash")
    reset_settings()
    reset_engine()

    with TestClient(app) as client:
        r = client.post("/api/pulse/generate?sample_size=50")
        assert r.status_code == 400
        body = r.json()
        assert "detail" in body
        assert len(str(body["detail"])) > 0
