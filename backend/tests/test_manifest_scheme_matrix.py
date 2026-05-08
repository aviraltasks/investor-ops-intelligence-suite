"""Coverage: every manifest fund resolves and deterministic metric extraction works with seeded chunks."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import reset_settings
from app.db.models import RagChunk
from app.db.session import get_session_factory, reset_engine
from app.main import app
from app.rag.embed import get_embedder
from app.rag.fund_resolve import resolve_manifest_fund, resolve_manifest_funds_ordered
from app.sources.manifest import FUND_SOURCES


def _display_short(display_name: str) -> str:
    for suf in (" fund direct growth", " direct growth", " fund direct plan growth"):
        d = display_name.strip().lower()
        if d.endswith(suf):
            return d[: -len(suf)].strip()
    return display_name.strip().lower()


def test_every_manifest_fund_resolves_from_short_label() -> None:
    for fund in FUND_SOURCES:
        short = _display_short(fund.display_name)
        assert len(short) >= 6
        slug, url = resolve_manifest_fund(f"expense ratio {short}")
        assert slug == fund.slug
        assert url == fund.url


def test_kotak_quant_dual_resolve_for_nav_compare() -> None:
    q = "Compare NAV of Kotak Small Cap and Quant Small Cap"
    funds = resolve_manifest_funds_ordered(q)
    slugs = [f.slug for f in funds]
    assert "kotak-midcap-fund-direct-growth" in slugs
    assert "quant-small-cap-fund-direct-plan-growth" in slugs


def test_matrix_chat_ter_nav_aum_lock_tax(monkeypatch, tmp_path) -> None:
    db_file = tmp_path / "manifest_matrix.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("EMBEDDING_MODEL", "hash")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    reset_settings()
    reset_engine()

    embedder = get_embedder()
    rows: list[RagChunk] = []
    for idx, fund in enumerate(FUND_SOURCES):
        nav = 50 + idx + 0.11 * idx
        ter = 0.25 + (idx % 7) * 0.05
        aum_base = 1200 + idx * 37
        lock_line = ""
        if fund.category == "ELSS":
            lock_line = " Lock-in period is 3 years from allotment date under Section 80C."
        text = (
            f"{fund.display_name} scheme factsheet. Latest NAV ₹{nav:.2f} per unit. "
            f"Total expense ratio (TER) {ter:.2f}% for direct plan. "
            f"AUM ₹{aum_base:,} Cr as per latest filing.{lock_line}"
        )
        emb = embedder.encode([text])[0].tolist()
        rows.append(
            RagChunk(
                source_url=fund.url,
                layer="groww",
                fund_slug=fund.slug,
                fund_display_name=fund.display_name.split(" Direct")[0].strip(),
                chunk_index=0,
                content=text,
                embedding=emb,
            )
        )

    SessionLocal = get_session_factory()

    def post(client: TestClient, msg: str, sid: str, user: str) -> str:
        r = client.post(
            "/api/chat",
            json={"message": msg, "session_id": sid, "user_name": user},
        )
        assert r.status_code == 200
        return r.json()["response"]

    with TestClient(app) as client:
        with SessionLocal() as session:
            session.add_all(rows)
            session.commit()

        for fund in FUND_SOURCES:
            short = _display_short(fund.display_name)
            u = f"M-{fund.slug[:16]}"
            ter_body = post(client, f"What is the expense ratio of {short}?", f"m-ter-{fund.slug}", u)
            assert "%" in ter_body

            nav_body = post(client, f"What is NAV of {short}?", f"m-nav-{fund.slug}", u + "-n")
            assert "₹" in nav_body

            aum_body = post(client, f"What is AUM of {short}?", f"m-aum-{fund.slug}", u + "-a")
            assert "Cr" in aum_body or "cr" in aum_body.lower()

        lock_body = post(
            client,
            "Does Canara Robeco Large Cap have any lock-in period?",
            "m-lock-canara",
            "M-can-lock",
        )
        assert "open-ended" in lock_body.lower() or "lock" in lock_body.lower()

        mirae = next(f for f in FUND_SOURCES if "mirae" in f.slug)
        ms = _display_short(mirae.display_name)
        tax_body = post(client, f"What are the tax benefits of {ms}?", f"m-tax-{mirae.slug}", "M-tax")
        assert "80c" in tax_body.lower() or "section" in tax_body.lower()

        cmp_body = post(
            client,
            "Compare NAV of Kotak Small Cap and Quant Small Cap",
            "m-navcmp",
            "M-cmp",
        )
        assert "NAV comparison" in cmp_body or "comparison" in cmp_body.lower()
        assert cmp_body.count("₹") >= 2
