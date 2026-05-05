"""Unit tests for /health."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app, build_health_payload


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_health_ok(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("ok", "degraded")
    assert body["service"] == "investor-ops-api"
    assert "components" in body


def test_root(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "health" in r.json().get("message", "").lower()


def test_build_health_payload_database_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    p = build_health_payload("0.1.0")
    assert p["components"]["database"]["status"] == "not_configured"


def test_build_health_payload_with_groq(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/db")
    p = build_health_payload("0.1.0")
    assert p["status"] == "ok"
