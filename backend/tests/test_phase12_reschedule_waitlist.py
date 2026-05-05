"""Reschedule + waitlist first-class flows (PRD + SCRIPT_FLOW)."""

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


def test_reschedule_same_booking_code(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "p12_resched.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("EMBEDDING_MODEL", "hash")
    monkeypatch.setenv("GOOGLE_INTEGRATIONS_MODE", "mock")
    reset_settings()
    reset_engine()

    with TestClient(app) as client:
        _chat(client, "p12-r1", "Book appointment tomorrow at 10 am for KYC")
        book = _chat(client, "p12-r1", "yes")
        code = book["payload"]["booking_code"]
        assert code.startswith("GRW-") and not code.startswith("GRW-W-")

        res = _chat(
            client,
            "p12-r1",
            f"I need to reschedule {code} to tomorrow at 3 pm",
        )
        assert res["payload"].get("status") == "awaiting_confirmation"
        res2 = _chat(client, "p12-r1", "yes")
        assert res2["payload"].get("booking_code") == code
        assert res2["payload"].get("status") == "tentative"
        assert res2["payload"].get("time_ist") == "15:00 IST"
        assert "orchestrator" in {t["agent"] for t in res2["traces"]}


def test_reschedule_rejects_cancelled_booking(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "p12_cancel_resched.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("EMBEDDING_MODEL", "hash")
    reset_settings()
    reset_engine()

    with TestClient(app) as client:
        _chat(client, "p12-r2", "Book tomorrow at 11 am for SIP")
        book = _chat(client, "p12-r2", "yes")
        code = book["payload"]["booking_code"]
        _chat(client, "p12-r2", f"Cancel booking {code}")
        _chat(client, "p12-r2", "yes")
        res = _chat(client, "p12-r2", f"Reschedule {code} to tomorrow at 2 pm")
        assert "cancelled" in res["response"].lower()
        assert res["payload"].get("status") == "cancelled"


def test_waitlist_creates_grw_w_code(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "p12_wl.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("EMBEDDING_MODEL", "hash")
    monkeypatch.setenv("GOOGLE_INTEGRATIONS_MODE", "mock")
    reset_settings()
    reset_engine()

    with TestClient(app) as client:
        out = _chat(client, "p12-w1", "Please add me to the waitlist for KYC onboarding")
        code = out["payload"].get("booking_code", "")
        assert code.startswith("GRW-W-")
        assert out["payload"].get("status") == "waitlisted"
        sync = out["payload"].get("integration_sync", {})
        assert sync.get("calendar", {}).get("ok") is True
        ref = str(sync.get("calendar", {}).get("reference", ""))
        assert "waitlist" in ref or "mock-waitlist" in ref


def test_cancel_waitlist_entry(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "p12_wl_cancel.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("EMBEDDING_MODEL", "hash")
    reset_settings()
    reset_engine()

    with TestClient(app) as client:
        wl = _chat(client, "p12-w2", "join waitlist for withdrawals")
        code = wl["payload"]["booking_code"]
        _chat(client, "p12-w2", f"Cancel {code}")
        can = _chat(client, "p12-w2", "yes")
        assert can["payload"].get("status") == "cancelled"
