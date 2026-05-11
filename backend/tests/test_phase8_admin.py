"""Phase 8 tests: admin dashboard APIs and actions."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agents import rag_agent
from app.config import reset_settings
from app.db.models import InteractionLog, PulseRun, PulseTheme
from app.db.session import get_session_factory, init_db, reset_engine
from app.main import app, purge_bot_echo_faq_interaction_logs


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

        sub = client.post("/api/subscribers", json={"email": "advisor-briefing-test@example.com"})
        assert sub.status_code == 200

        send = client.post(f"/api/admin/bookings/{code}/email/send", json={})
        assert send.status_code == 200
        body = send.json()
        assert body["ok"] is True
        assert body["status"] == "sent"
        assert body.get("sent_count") == 1
        assert "advisor-briefing-test@example.com" in (body.get("recipients") or [])


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


def test_purge_bot_echo_faq_interaction_logs(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "phase8_bot_echo_purge.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("EMBEDDING_MODEL", "hash")
    reset_settings()
    reset_engine()
    init_db()

    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        session.add_all(
            [
                InteractionLog(session_id="s1", intent="faq", topic="i provide factual mutual"),
                InteractionLog(session_id="s2", intent="faq", topic="what is the exit"),
                InteractionLog(session_id="s3", intent="scheduling", topic="i provide factual mutual"),
            ]
        )
        session.commit()
        removed = purge_bot_echo_faq_interaction_logs(session)
        session.commit()
        assert removed == 1

    with SessionLocal() as session:
        faq_topics = [
            row.topic
            for row in session.scalars(select(InteractionLog).where(InteractionLog.intent == "faq")).all()
        ]
        assert "i provide factual mutual" not in faq_topics
        assert "what is the exit" in faq_topics
        sched = session.scalars(select(InteractionLog).where(InteractionLog.intent == "scheduling")).first()
        assert sched is not None and sched.topic == "i provide factual mutual"


def test_admin_review_themes_reflect_latest_pulse_only(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "phase8_pulse_theme_latest.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("EMBEDDING_MODEL", "hash")
    reset_settings()
    reset_engine()
    init_db()

    now = datetime.utcnow()
    with TestClient(app) as client:
        SessionLocal = get_session_factory()
        with SessionLocal() as session:
            older = PulseRun(mode="ml", review_count=100, generated_at=now - timedelta(hours=3), analysis="")
            session.add(older)
            session.flush()
            session.add_all(
                [
                    PulseTheme(pulse_run_id=older.id, rank=1, label="Chart & After", volume=999, quote=""),
                    PulseTheme(pulse_run_id=older.id, rank=2, label="Money & Time", volume=888, quote=""),
                ]
            )
            newer = PulseRun(mode="ml", review_count=60, generated_at=now - timedelta(hours=1), analysis="")
            session.add(newer)
            session.flush()
            session.add_all(
                [
                    PulseTheme(pulse_run_id=newer.id, rank=1, label="Trading platform user feedback", volume=50, quote=""),
                    PulseTheme(pulse_run_id=newer.id, rank=2, label="Clean Theme B", volume=30, quote=""),
                    PulseTheme(pulse_run_id=newer.id, rank=3, label="Clean Theme C", volume=20, quote=""),
                ]
            )
            session.commit()

        analytics = client.get("/api/admin/analytics?range=week")
        assert analytics.status_code == 200
        themes = {x["theme"]: x["volume"] for x in analytics.json()["review_themes"]}
        assert "Chart & After" not in themes
        assert "Money & Time" not in themes
        assert themes == {
            "Trading platform user feedback": 50,
            "Clean Theme B": 30,
            "Clean Theme C": 20,
        }


def test_admin_faq_topics_skip_bot_echo_inputs(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "phase8_faq_topics_guard.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("EMBEDDING_MODEL", "hash")
    reset_settings()
    reset_engine()

    with TestClient(app) as client:
        _post_chat(client, "What is the exit load for Mirae ELSS?", session_id="faq-guard-1")
        _post_chat(
            client,
            "I provide factual mutual fund, SAP, and mandatory advisor appointments.",
            session_id="faq-guard-1",
        )
        analytics = client.get("/api/admin/analytics?range=week")
        assert analytics.status_code == 200
        faq_topics = [str(x.get("topic") or "").lower() for x in analytics.json().get("faq_topics", [])]
        assert all("i provide factual mutual" not in t for t in faq_topics)


def test_admin_can_clear_faq_cache(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "phase8_cache_clear.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("EMBEDDING_MODEL", "hash")
    reset_settings()
    reset_engine()

    with TestClient(app) as client:
        rag_agent._cache_set("cache smoke key", "answer", ["https://example.com"])  # type: ignore[attr-defined]

        cleared = client.post("/api/admin/cache/faq/clear")
        assert cleared.status_code == 200
        body = cleared.json()
        assert body["ok"] is True
        assert int(body["cleared_entries"]) >= 1

        cleared_again = client.post("/api/admin/cache/faq/clear")
        assert cleared_again.status_code == 200
        assert int(cleared_again.json()["cleared_entries"]) == 0
