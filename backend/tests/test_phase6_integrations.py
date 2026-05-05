"""Phase 6 tests: scheduling integration hooks and fallback behavior."""

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


def test_booking_triggers_integration_sync(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "phase6_booking.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("GOOGLE_INTEGRATIONS_MODE", "mock")
    reset_settings()
    reset_engine()

    with TestClient(app) as client:
        _chat(client, "phase6-s1", "book appointment for KYC tomorrow at 10 am")
        out = _chat(client, "phase6-s1", "yes")
        payload = out["payload"]
        assert payload.get("booking_code", "").startswith("GRW-")
        sync = payload.get("integration_sync", {})
        assert sync.get("calendar", {}).get("ok") is True
        assert sync.get("sheets", {}).get("ok") is True
        assert sync.get("email_draft", {}).get("ok") is True


def test_cancel_triggers_calendar_and_sheet_sync(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "phase6_cancel.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("GOOGLE_INTEGRATIONS_MODE", "mock")
    reset_settings()
    reset_engine()

    with TestClient(app) as client:
        _chat(client, "phase6-s2", "book appointment tomorrow at 11 am")
        _chat(client, "phase6-s2", "yes")
        _chat(client, "phase6-s2", "cancel my booking")
        out = _chat(client, "phase6-s2", "yes")
        sync = out["payload"].get("integration_sync", {})
        assert sync.get("calendar", {}).get("ok") is True
        assert sync.get("sheets", {}).get("ok") is True


def test_live_mode_without_ids_falls_back_to_mock(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "phase6_live_fallback.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("GOOGLE_INTEGRATIONS_MODE", "live")
    monkeypatch.delenv("GOOGLE_CALENDAR_ID", raising=False)
    monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)
    reset_settings()
    reset_engine()

    with TestClient(app) as client:
        _chat(client, "phase6-s3", "book appointment next week for SIP")
        out = _chat(client, "phase6-s3", "yes")
        sync = out["payload"].get("integration_sync", {})
        # Should still succeed due to mock fallback in live-without-ids mode.
        assert sync.get("calendar", {}).get("ok") is True
        assert sync.get("sheets", {}).get("ok") is True
