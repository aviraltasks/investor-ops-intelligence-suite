"""Phase 3 tests for ML theme detection and pulse generation."""

from __future__ import annotations

from sqlalchemy import func, select

from app.config import reset_settings
from app.db.models import PulseRun, PulseTheme, Review
from app.db.session import get_session_factory, init_db, reset_engine
from app.ml.theme_pipeline import generate_pulse, get_latest_pulse, list_pulse_history


def _seed_reviews(session) -> None:
    rows = []
    for i in range(14):
        rows.append(
            Review(
                external_id=f"rev-withdraw-{i}",
                content="Withdrawal pending for days and timeline is unclear.",
                score=1.0,
                source="csv_fallback",
            )
        )
    for i in range(12):
        rows.append(
            Review(
                external_id=f"rev-kyc-{i}",
                content="KYC verification failed repeatedly after document upload.",
                score=2.0,
                source="csv_fallback",
            )
        )
    for i in range(10):
        rows.append(
            Review(
                external_id=f"rev-sip-{i}",
                content="SIP mandate setup and autopay linking is confusing.",
                score=2.0,
                source="csv_fallback",
            )
        )
    session.add_all(rows)
    session.commit()


def test_generate_pulse_persists_and_structures(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "phase3_ml.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("EMBEDDING_MODEL", "hash")
    reset_settings()
    reset_engine()
    init_db()

    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        _seed_reviews(session)
        pulse = generate_pulse(session, sample_size=100)
        assert pulse["review_count"] >= 30
        assert len(pulse["top_themes"]) == 3
        assert len(pulse["actions"]) == 3
        assert pulse["metrics"]["algorithm"] == "custom_kmeans_numpy"
        assert "silhouette" in pulse["metrics"]
        assert len(pulse["analysis"].split()) < 250

        run_count = session.scalar(select(func.count()).select_from(PulseRun))
        theme_count = session.scalar(select(func.count()).select_from(PulseTheme))
        assert run_count == 1
        assert theme_count == 3


def test_latest_and_history(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "phase3_history.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("EMBEDDING_MODEL", "hash")
    reset_settings()
    reset_engine()
    init_db()

    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        _seed_reviews(session)
        first = generate_pulse(session, sample_size=80)
        second = generate_pulse(session, sample_size=80)
        latest = get_latest_pulse(session)
        assert latest is not None
        assert latest["pulse_id"] == second["pulse_id"]
        hist = list_pulse_history(session, limit=10)
        assert len(hist) >= 2
