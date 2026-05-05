"""Phase 10 tests: secure booking page APIs + subscriber API behavior."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import reset_settings
from app.db.session import reset_engine
from app.main import app


def _chat(client: TestClient, message: str, session_id: str = "p10-s1", user_name: str = "Aviral") -> dict:
    r = client.post("/api/chat", json={"message": message, "session_id": session_id, "user_name": user_name})
    assert r.status_code == 200
    return r.json()


def test_secure_booking_lookup_and_submit(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "phase10_secure.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("EMBEDDING_MODEL", "hash")
    reset_settings()
    reset_engine()

    with TestClient(app) as client:
        _chat(client, "Book appointment tomorrow at 10 am for KYC", session_id="secure-1")
        out = _chat(client, "yes", session_id="secure-1")
        code = out["payload"]["booking_code"]

        lookup = client.get(f"/api/secure/{code}")
        assert lookup.status_code == 200
        body = lookup.json()
        assert body["ok"] is True
        assert body["booking"]["booking_code"] == code

        bad_phone = client.post(
            f"/api/secure/{code}/details",
            json={"phone": "12345", "email": "u@example.com", "consent": True},
        )
        assert bad_phone.status_code == 200
        assert bad_phone.json()["ok"] is False

        missing_consent = client.post(
            f"/api/secure/{code}/details",
            json={"phone": "+91 9876543210", "email": "u@example.com", "consent": False},
        )
        assert missing_consent.status_code == 200
        assert missing_consent.json()["ok"] is False

        ok_submit = client.post(
            f"/api/secure/{code}/details",
            json={"phone": "+91 9876543210", "email": "user@example.com", "consent": True},
        )
        assert ok_submit.status_code == 200
        assert ok_submit.json()["ok"] is True
        assert ok_submit.json()["secure_details"]["sheet_columns_updated"] == ["K", "L"]

        invalid = client.get("/api/secure/GRW-XXXX")
        assert invalid.status_code == 200
        assert invalid.json()["ok"] is False


def test_subscriber_api_basic_flow(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "phase10_subs.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("EMBEDDING_MODEL", "hash")
    reset_settings()
    reset_engine()

    with TestClient(app) as client:
        bad = client.post("/api/subscribers", json={"email": "bad-email"})
        assert bad.status_code == 200
        assert bad.json()["ok"] is False

        first = client.post("/api/subscribers", json={"email": "one@example.com"})
        assert first.status_code == 200
        assert first.json()["ok"] is True

        second = client.post("/api/subscribers", json={"email": "one@example.com"})
        assert second.status_code == 200
        assert second.json()["ok"] is True
        assert second.json()["message"] == "already subscribed"

        listed = client.get("/api/admin/subscribers")
        assert listed.status_code == 200
        emails = [x["email"] for x in listed.json()["items"]]
        assert "one@example.com" in emails
