"""Local verification for expense ratio vs exit load extraction (no network)."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name.replace(chr(92), '/')}"
os.environ["EMBEDDING_MODEL"] = "hash"

from fastapi.testclient import TestClient  # noqa: E402

from app.agents.rag_agent import clear_faq_answer_cache  # noqa: E402
from app.config import reset_settings  # noqa: E402
from app.db.session import get_session_factory, init_db, reset_engine  # noqa: E402
from app.main import app  # noqa: E402
from app.rag.embed import HashEmbedder  # noqa: E402
from app.rag.ingest_pipeline import ingest_url_list  # noqa: E402


@dataclass
class DummyResponse:
    content: bytes
    status_code: int = 200

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("bad status")


class DummyClient:
    def __init__(self, pages: dict[str, bytes]) -> None:
        self.pages = pages

    def get(self, url: str) -> DummyResponse:
        data = self.pages.get(url)
        if data is None:
            return DummyResponse(b"", status_code=404)
        return DummyResponse(data)


def main() -> None:
    u_sbi_small = "https://groww.in/mutual-funds/sbi-small-midcap-fund-direct-growth"
    u_sbi_nifty = "https://groww.in/mutual-funds/sbi-nifty-index-fund-direct-growth"
    u_mirae = "https://groww.in/mutual-funds/mirae-asset-elss-tax-saver-fund-direct-growth"
    u_quant = "https://groww.in/mutual-funds/quant-small-cap-fund-direct-plan-growth"
    u_cat = "https://groww.in/mutual-funds/equity-funds/small-cap-funds"

    html_small = b"""<html><body><main>
    <p>SBI Small Cap Fund Direct Growth overview.</p>
    <p>Exit load is 0.50% if redeemed within 12 months from allotment.</p>
    <p>Total Expense Ratio (TER) is 1.05% per annum as per latest mandate.</p>
    </main></body></html>"""

    html_nifty = b"""<html><body><main>
    <p>SBI Nifty Index Fund Direct Growth tracks Nifty 50.</p>
    <p>Exit load Nil.</p>
    <p>Expense ratio 0.22% for direct plan.</p>
    </main></body></html>"""

    html_mirae = b"""<html><body><main>
    <p>Mirae Asset ELSS Tax Saver Fund Direct Growth.</p>
    <p>Expense ratio 0.65% p.a.</p>
    <p>Exit load of 1% if redeemed within 1 year from allotment.</p>
    </main></body></html>"""

    html_quant = b"""<html><body><main>
    <p>Quant Small Cap Fund Direct Plan Growth.</p>
    <p>TER 1.18%.</p>
    <p>Exit load 1% within 365 days.</p>
    </main></body></html>"""

    html_cat = b"""<html><body><main>
    <p>Small cap mutual funds category page.</p>
    <p>Scheme names include SBI Small Cap Fund Direct Growth and Quant Small Cap Fund Direct Plan Growth.</p>
    </main></body></html>"""

    pages = {
        u_sbi_small: html_small,
        u_sbi_nifty: html_nifty,
        u_mirae: html_mirae,
        u_quant: html_quant,
        u_cat: html_cat,
    }

    reset_settings()
    reset_engine()
    init_db()
    embedder = HashEmbedder()
    SessionLocal = get_session_factory()
    http = DummyClient(pages)
    with SessionLocal() as session:
        ingest_url_list(session, http, embedder, [u_sbi_small], "groww", fund_slug="sbi-small-midcap-fund-direct-growth", fund_display_name="SBI Small Cap Fund Direct Growth")
        ingest_url_list(session, http, embedder, [u_sbi_nifty], "groww", fund_slug="sbi-nifty-index-fund-direct-growth", fund_display_name="SBI Nifty Index Fund Direct Growth")
        ingest_url_list(session, http, embedder, [u_mirae], "groww", fund_slug="mirae-asset-elss-tax-saver-fund-direct-growth", fund_display_name="Mirae Asset ELSS Tax Saver Fund Direct Growth")
        ingest_url_list(session, http, embedder, [u_quant], "groww", fund_slug="quant-small-cap-fund-direct-plan-growth", fund_display_name="Quant Small Cap Fund Direct Growth")
        ingest_url_list(session, http, embedder, [u_cat], "extra")
        session.commit()

    queries = [
        "expense ratio of SBI Small Cap",
        "expense ration of SBI Nifty Index",
        "exit load of Mirae ELSS",
        "Compare expense ratios of small cap funds",
    ]

    clear_faq_answer_cache()
    with TestClient(app) as client:
        for i, msg in enumerate(queries, start=1):
            clear_faq_answer_cache()
            sid = f"verify-fee-{i}"
            r = client.post("/api/chat", json={"message": msg, "session_id": sid, "user_name": "LocalVerify"})
            assert r.status_code == 200, r.text
            body = r.json()
            print("=" * 72)
            print(f"Q{i}: {msg}")
            print("-" * 72)
            print(body.get("response", ""))


if __name__ == "__main__":
    main()
