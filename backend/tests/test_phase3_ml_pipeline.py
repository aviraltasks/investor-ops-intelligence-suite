"""Phase 3 tests for ML theme detection and pulse generation."""

from __future__ import annotations

from sqlalchemy import func, select

from app.config import reset_settings
from app.db.models import PulseRun, PulseTheme, Review
from app.db.session import get_session_factory, init_db, reset_engine
from app.llm.client import LLMResponse
from app.ml import theme_pipeline as theme_pipeline_mod
from app.ml.theme_pipeline import (
    _build_llm_cluster_label_messages,
    _llm_cluster_short_label,
    _parse_llm_cluster_label,
    generate_pulse,
    get_latest_pulse,
    list_pulse_history,
)


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
        assert pulse["review_count"] >= 3
        assert len(pulse["top_themes"]) == 3
        assert len(pulse["actions"]) == 3
        assert pulse["metrics"]["algorithm"] == "custom_kmeans_numpy"
        assert "silhouette" in pulse["metrics"]
        assert pulse["metrics"]["llm_labels_applied_count"] == 0
        assert pulse["comparison"]["llm_labels_applied_count"] == 0
        assert pulse["metrics"]["llm_clusters_selected"] == 3
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


def test_generate_pulse_applies_quality_gate(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "phase3_quality_gate.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("EMBEDDING_MODEL", "hash")
    reset_settings()
    reset_engine()
    init_db()

    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        # Robust reviews (should pass quality gate)
        for i in range(7):
            session.add(
                Review(
                    external_id=f"r-login-{i}",
                    content="Login failed after update because otp verification is stuck on loading screen.",
                    score=1.0,
                    source="csv_fallback",
                )
            )
        for i in range(6):
            session.add(
                Review(
                    external_id=f"r-kyc-{i}",
                    content="KYC verification failed after document upload and bank linking is pending.",
                    score=2.0,
                    source="csv_fallback",
                )
            )
        for i in range(6):
            session.add(
                Review(
                    external_id=f"r-sip-{i}",
                    content="SIP mandate setup shows error during payment and autopay is not activated.",
                    score=2.0,
                    source="csv_fallback",
                )
            )
        # Junk / weak signal (should be dropped)
        for i in range(5):
            session.add(Review(external_id=f"junk-emoji-{i}", content="🔥🔥🔥", score=5.0, source="csv_fallback"))
        for i in range(5):
            session.add(Review(external_id=f"junk-short-{i}", content="bad app", score=1.0, source="csv_fallback"))
        for i in range(3):
            session.add(
                Review(
                    external_id=f"dup-{i}",
                    content="Login failed after update because otp verification is stuck on loading screen.",
                    score=1.0,
                    source="csv_fallback",
                )
            )
        session.commit()

        pulse = generate_pulse(session, sample_size=200)
        q = pulse["comparison"]["quality_gate"]
        assert q["fetched"] >= 25
        assert (q["junk_filtered"] + q["duplicate_filtered"]) >= 8
        assert q["duplicate_filtered"] >= 2
        assert q["used_for_themes"] >= 3
        assert pulse["metrics"]["sample_size"] == q["used_for_themes"]
        assert pulse["metrics"]["raw_sample_size"] == q["fetched"]


def test_generate_pulse_fails_when_only_noise(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "phase3_only_noise.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("EMBEDDING_MODEL", "hash")
    reset_settings()
    reset_engine()
    init_db()

    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        for i in range(30):
            session.add(Review(external_id=f"noise-{i}", content="ok", score=3.0, source="csv_fallback"))
        session.commit()
        try:
            generate_pulse(session, sample_size=50)
            raise AssertionError("expected ValueError for unusable reviews")
        except ValueError as exc:
            assert "No usable reviews" in str(exc)


def test_llm_cluster_prompt_shape() -> None:
    msgs = _build_llm_cluster_label_messages(
        [
            "App crashes during order placement and customer support is slow.",
            "Order failed with timeout and retry flow is confusing.",
        ]
    )
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert "Return JSON only" in msgs[0]["content"]
    assert msgs[1]["role"] == "user"
    assert "App crashes during order placement" in msgs[1]["content"]


def test_parse_llm_cluster_label_json_and_plain_text() -> None:
    assert _parse_llm_cluster_label('{"label":"Order Placement Failures"}') == "Order Placement Failures"
    assert _parse_llm_cluster_label("Order Placement Failures") == "Order Placement Failures"


def test_llm_cluster_short_label_retries_once(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_LLM_IN_PYTEST", "1")
    monkeypatch.setenv("GROQ_API_KEY", "fake-test-key")
    calls: list[int] = []
    sleeps: list[float] = []

    def fake_chat(messages: list[dict[str, str]], *, temperature: float = 0.25) -> LLMResponse:
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            return LLMResponse("", "none", "simulated_failure")
        return LLMResponse('{"label":"Retry Success Title"}', "groq", "")

    monkeypatch.setattr(theme_pipeline_mod, "chat_completion_safe", fake_chat)
    monkeypatch.setattr(theme_pipeline_mod.time, "sleep", lambda s: sleeps.append(float(s)))

    assert _llm_cluster_short_label(["withdrawal pending for several days"]) == "Retry Success Title"
    assert calls == [1, 2]
    assert sleeps == [2.0]


def test_llm_cluster_short_label_no_sleep_when_first_ok(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_LLM_IN_PYTEST", "1")
    monkeypatch.setenv("GROQ_API_KEY", "fake-test-key")
    calls: list[int] = []
    sleeps: list[float] = []

    def fake_chat(messages: list[dict[str, str]], *, temperature: float = 0.25) -> LLMResponse:
        calls.append(1)
        return LLMResponse('{"label":"First Try OK"}', "groq", "")

    monkeypatch.setattr(theme_pipeline_mod, "chat_completion_safe", fake_chat)
    monkeypatch.setattr(theme_pipeline_mod.time, "sleep", lambda s: sleeps.append(float(s)))

    assert _llm_cluster_short_label(["kyc verification failed"]) == "First Try OK"
    assert len(calls) == 1
    assert sleeps == []


def test_generate_pulse_spaces_llm_calls_between_clusters(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "phase3_llm_spacing.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("EMBEDDING_MODEL", "hash")
    reset_settings()
    reset_engine()
    init_db()

    sleeps: list[float] = []
    monkeypatch.setattr(theme_pipeline_mod, "llm_available", lambda: True)
    monkeypatch.setattr(theme_pipeline_mod, "_llm_cluster_short_label", lambda _texts: None)
    monkeypatch.setattr(theme_pipeline_mod.time, "sleep", lambda s: sleeps.append(float(s)))

    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        _seed_reviews(session)
        generate_pulse(session, sample_size=100)

    # For 3 selected clusters, spacing runs before clusters 2 and 3.
    assert sleeps == [4.0, 4.0]
