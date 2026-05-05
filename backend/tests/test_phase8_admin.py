"""Phase 8 tests: admin dashboard APIs and actions."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import reset_settings
from app.db.session import reset_engine
from app.main import app


def _post_chat(client: TestClient, message: str, session_id: str = "admin-s1") -> dict:
    r = client.post("/api/chat", json={"message": message, "session_id": session_id, "user_name": "AdminUser"})
    assert r.status_code == 200
    return r.json()


def test_admin_analytics_and_logs(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "phase8_admin.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("EMBEDDING_MODEL", "hash")
    reset_settings()
    reset_engine()

    with TestClient(app) as client:
        _post_chat(client, "Please book an appointment for SIP planning tomorrow at 11 am", session_id="a-1")
        _post_chat(client, "yes", session_id="a-1")
        _post_chat(client, "What is expense ratio in small cap fund?", session_id="a-2")

        analytics = client.get("/api/admin/analytics?range=week")
        assert analytics.status_code == 200
        payload = analytics.json()
        assert "appointments_booked" in payload
        assert "faq_topics" in payload
        assert len(payload["appointments_booked"]) >= 1
        assert len(payload["faq_topics"]) >= 1

        logs = client.get("/api/admin/agent-activity?limit=50")
        assert logs.status_code == 200
        logs_payload = logs.json()
        assert logs_payload["count"] > 0
        agents = [x["agent"] for x in logs_payload["items"]]
        assert "orchestrator" in agents

        csv_export = client.get("/api/admin/export/analytics.csv?range=week")
        assert csv_export.status_code == 200
        assert b"section,key,value" in csv_export.content
        assert b"booking_topic" in csv_export.content or b"review_theme" in csv_export.content


def test_admin_append_pulse_doc_mock_mode(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "phase8_doc.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("EMBEDDING_MODEL", "hash")
    monkeypatch.setenv("GOOGLE_INTEGRATIONS_MODE", "mock")
    reset_settings()
    reset_engine()

    with TestClient(app) as client:
        r = client.post("/api/admin/pulse/append-doc")
        assert r.status_code == 200
        body = r.json()
        assert body.get("ok") is False


def test_admin_booking_email_actions(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "phase8_booking.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("EMBEDDING_MODEL", "hash")
    reset_settings()
    reset_engine()

    with TestClient(app) as client:
        _post_chat(client, "Book an appointment for taxation this Friday at 4 pm", session_id="b-1")
        chat = _post_chat(client, "yes", session_id="b-1")
        code = chat["payload"]["booking_code"]

        all_bookings = client.get("/api/admin/bookings")
        assert all_bookings.status_code == 200
        assert any(x["booking_code"] == code for x in all_bookings.json()["items"])

        preview = client.post(f"/api/admin/bookings/{code}/email/preview")
        assert preview.status_code == 200
        assert preview.json()["ok"] is True
        assert code in preview.json()["draft"]

        send = client.post(
            f"/api/admin/bookings/{code}/email/send",
            json={"to_email": "advisor@example.com"},
        )
        assert send.status_code == 200
        assert send.json()["ok"] is True
        assert send.json()["status"] == "sent"


def test_subscribers_and_pulse_send(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "phase8_subscribers.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("EMBEDDING_MODEL", "hash")
    monkeypatch.setenv("REVIEWS_FALLBACK_CSV", "sample_data/reviews_fallback.csv")
    reset_settings()
    reset_engine()

    with TestClient(app) as client:
        create = client.post("/api/subscribers", json={"email": "one@example.com"})
        assert create.status_code == 200
        assert create.json()["ok"] is True

        subs = client.get("/api/admin/subscribers")
        assert subs.status_code == 200
        emails = [x["email"] for x in subs.json()["items"]]
        assert "one@example.com" in emails

        no_pulse = client.post("/api/admin/pulse/send", json={"emails": emails})
        assert no_pulse.status_code == 200
        assert no_pulse.json()["ok"] is False

        reviews = client.post("/api/reviews/refresh?limit=200")
        assert reviews.status_code == 200
        generated = client.post("/api/pulse/generate?sample_size=200")
        assert generated.status_code == 200
        assert generated.json().get("pulse_id")

        sent = client.post("/api/admin/pulse/send", json={"emails": emails})
        assert sent.status_code == 200
        assert sent.json()["ok"] is True
        assert sent.json()["sent_count"] == 1
