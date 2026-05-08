"""Fund alias resolution and exit-load extraction helpers."""

from __future__ import annotations

from app.agents.rag_agent import _extract_exit_load_detail
from app.rag.fund_resolve import resolve_manifest_fund


def test_resolve_uti_nifty_casual() -> None:
    slug, url = resolve_manifest_fund("tell exit load for uti nifty 50 index")
    assert slug == "uti-nifty-fund-direct-growth"
    assert "uti-nifty-fund-direct-growth" in (url or "")


def test_resolve_sbi_nifty_shorthand() -> None:
    slug, _ = resolve_manifest_fund("expense ration of SBI Nifty Index")
    assert slug == "sbi-nifty-index-fund-direct-growth"


def test_extract_exit_load_nil() -> None:
    d = _extract_exit_load_detail("Exit load Nil for direct investors. Other terms apply.")
    assert d is not None
    assert d[0] == "Nil"


def test_extract_exit_load_percent() -> None:
    d = _extract_exit_load_detail("Exit load 0.25% if redeemed within 30 days.")
    assert d is not None
    assert "0.25%" in d[0]


def test_extract_exit_load_numeric_no_percent() -> None:
    d = _extract_exit_load_detail("Exit load 0 if held more than 1 year.")
    assert d is not None
    assert "0" in d[0]
