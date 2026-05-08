"""Local smoke test: ingest minimal URLs + print top-3 search for layer-boost verification."""

from __future__ import annotations

import os
import tempfile
from typing import Any

# Env before app imports
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name.replace(chr(92), '/')}"
os.environ["EMBEDDING_MODEL"] = "hash"

from app.config import reset_settings  # noqa: E402
from app.db.session import get_session_factory, init_db, reset_engine  # noqa: E402
from app.rag.embed import get_embedder, set_embedder  # noqa: E402
from app.rag.http_client import new_client  # noqa: E402
from app.rag.ingest_pipeline import ingest_url_list  # noqa: E402
from app.rag.search import fund_metric_layer_boost_applies, search_chunks  # noqa: E402


EXTRA_URL = "https://groww.in/mutual-funds/equity-funds/small-cap-funds"
GROWW_URL = "https://groww.in/mutual-funds/sbi-small-midcap-fund-direct-growth"
SEBI_URL = "https://investor.sebi.gov.in/securities-mf-investments.html"

QUERIES: list[tuple[str, bool]] = [
    ("expense ratio SBI Small Cap", True),
    ("compare expense ratios small cap funds", True),
    ("What is NAV?", False),
]


def _fmt_hit(h: dict[str, Any]) -> str:
    return f"layer={h['layer']!s:<6} score={h['score']:.6f} url={h['source_url'][:88]}…"


def main() -> None:
    reset_settings()
    set_embedder(None)
    reset_engine()
    init_db()
    embedder = get_embedder()
    SessionLocal = get_session_factory()

    with SessionLocal() as session, new_client() as client:
        n_extra = ingest_url_list(session, client, embedder, [EXTRA_URL], "extra")
        n_groww = ingest_url_list(
            session,
            client,
            embedder,
            [GROWW_URL],
            "groww",
            fund_slug="sbi-small-midcap-fund-direct-growth",
            fund_display_name="SBI Small Cap Fund Direct Growth",
        )
        n_sebi = ingest_url_list(session, client, embedder, [SEBI_URL], "sebi")
        print(f"ingested chunks: extra={n_extra} groww={n_groww} sebi={n_sebi}")
        if n_extra == 0 or n_groww == 0:
            raise SystemExit("Ingest produced no chunks — check network / site blocking.")

        for q, expect_boost in QUERIES:
            boost = fund_metric_layer_boost_applies(q)
            print()
            print(f"query={q!r}")
            print(f"fund_metric_layer_boost_applies={boost} (expected {expect_boost})")
            hits = search_chunks(session, embedder, q, top_k=3, layer=None)
            for i, h in enumerate(hits, 1):
                print(f"  #{i} {_fmt_hit(h)}")
            if boost != expect_boost:
                raise SystemExit(f"Boost detection mismatch for {q!r}")


if __name__ == "__main__":
    main()
