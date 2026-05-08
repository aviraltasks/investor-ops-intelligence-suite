"""RAG specialist agent for FAQ/fund queries (LLM plan + synthesize when keys are set)."""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.agents.topic_routing import looks_like_topic_help_query, match_quick_topic_chip_label
from app.agents.types import AgentResult, AgentTraceStep
from app.llm.client import chat_completion_safe, llm_available, parse_json_object
from app.db.models import RagChunk
from app.rag.embed import get_embedder
from app.rag.fund_resolve import resolve_manifest_fund
from app.rag.search import search_chunks
from app.sources.manifest import FUND_SOURCES

_FAQ_ANSWER_CACHE: dict[str, tuple[str, list[str]]] = {}
_FAQ_CACHE_MAX = 300
# Bump when FAQ strings/logic change so stale in-process cache entries are not reused.
_FAQ_CACHE_PREFIX = "v3:"
_FUND_NAME_KEYS = tuple((f.display_name or "").lower() for f in FUND_SOURCES)


def expense_ratio_requested(query: str) -> bool:
    """Typo-tolerant detection for expense ratio intent (user query)."""
    ql = (query or "").lower()
    # Matches ratio | ration | ratios | common typo expence
    if re.search(r"expense\s+rati(?:o|on)s?\b", ql):
        return True
    if re.search(r"expence\s+rati(?:o|on)s?\b", ql):
        return True
    return False


def exit_load_requested(query: str) -> bool:
    ql = (query or "").lower()
    return "exit load" in ql or bool(re.search(r"\bexit\s+loads?\b", ql))


def _primary_fee_metric(query: str) -> str | None:
    """When both fee metrics appear, prefer the one that occurs first in the query."""
    er = expense_ratio_requested(query)
    el = exit_load_requested(query)
    if er and not el:
        return "expense_ratio"
    if el and not er:
        return "exit_load"
    if er and el:
        ql = (query or "").lower()
        m = re.search(r"expense\s+rati(?:o|on)s?\b|expence\s+rati(?:o|on)s?\b", ql)
        pos_er = m.start() if m else 10**9
        pos_el = ql.find("exit load")
        if pos_el < 0:
            pos_el = 10**9
        return "expense_ratio" if pos_er <= pos_el else "exit_load"
    return None


def _snippet_score_expense_ratio(sentence: str) -> float:
    low = sentence.lower()
    sc = 0.0
    if re.search(r"expense\s+ratio|total\s+expense\s+ratio", low):
        sc += 16.0
    elif "total expense" in low:
        sc += 11.0
    if re.search(r"\bter\b", low):
        sc += 10.0
    if "expense" in low:
        sc += 6.0
    if "%" in low:
        sc += 2.0
    if re.search(r"exit\s+load", low) and not re.search(r"expense\s+ratio|total\s+expense\s+ratio|\bter\b", low):
        sc -= 20.0
    return sc


def _snippet_score_exit_load(sentence: str) -> float:
    low = sentence.lower()
    sc = 0.0
    if "exit load" in low:
        sc += 18.0
    elif re.search(r"\bredeem|redemption", low):
        sc += 7.0
    if "%" in low:
        sc += 3.0
    if re.search(r"expense\s+ratio|total\s+expense\s+ratio", low) and "exit load" not in low:
        sc -= 18.0
    if re.search(r"\bter\b", low) and "exit load" not in low:
        sc -= 12.0
    return sc


def _extract_exit_load_detail(text: str) -> tuple[str, str] | None:
    """Parse exit load from chunk text: supports Nil/NA and numeric with or without %."""
    if not text:
        return None
    t = text
    # Nil / not applicable (common on index funds)
    m = re.search(
        r"exit\s+load[^.\n]{0,260}?\b(nil|n\.a\.|n\/a|\bn/a\b|not\s+applicable|no\s+exit\s+load)\b",
        t,
        re.IGNORECASE,
    )
    if m:
        raw = m.group(1).strip().lower()
        if raw in {"nil", "n/a", "n.a.", "not applicable", "no exit load"}:
            return ("Nil", "")
        return (m.group(1).strip(), "")
    # Standard: ... X% ...
    m = re.search(r"exit\s+load[^.\n]{0,160}?(\d+(?:\.\d+)?)\s*%([^.\n]{0,120})", t, re.IGNORECASE)
    if m:
        return (f"{m.group(1)}%", _compact(m.group(2), max_len=80))
    # Numeric near label without forcing % on same token
    m = re.search(r"exit\s+load[^.\n]{0,120}?(\d+(?:\.\d+)?)(?:\s*%|\s*percent)?", t, re.IGNORECASE)
    if m:
        return (f"{m.group(1)}%", "")
    # Label:value tables (Groww) — exit load on its own line
    m = re.search(
        r"(?:^|\n)\s*exit\s+load\s*[:\-]\s*(nil|n\.a\.|n\/a|[\d.]+\s*%?)\s*(?:\n|$)",
        t,
        re.IGNORECASE | re.MULTILINE,
    )
    if m:
        raw = m.group(1).strip().lower()
        if raw.rstrip("%") in {"nil", "n.a.", "n/a"} or raw.startswith("nil"):
            return ("Nil", "")
        if "%" in m.group(1):
            return (m.group(1).strip(), "")
        return (f"{m.group(1).strip()}%", "")
    return None


def _extract_expense_ratio_pct_match(text: str) -> re.Match[str] | None:
    """Match TER / expense ratio percentages in noisy Groww-style text."""
    for pat in (
        r"expense\s+ratio[^.\n]{0,140}?(\d+(?:\.\d+)?)\s*%",
        r"(?:total\s+expense\s+ratio|\bter\b)[^.\n]{0,140}?(\d+(?:\.\d+)?)\s*%",
        r"(?:total\s+expense|annual\s+recurring)[^\d]{0,80}?(\d+(?:\.\d+)?)\s*%",
        r"(?:\bter\b|total\s+expense\s+ratio)\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*%",
    ):
        m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
        if m:
            return m
    return None


def _query_terms(query: str) -> set[str]:
    terms = {t for t in re.findall(r"[a-z0-9]{3,}", query.lower())}
    stop = {
        "what",
        "why",
        "how",
        "when",
        "where",
        "which",
        "with",
        "from",
        "about",
        "fund",
        "funds",
        "direct",
        "growth",
        "plan",
        "show",
        "tell",
    }
    return {t for t in terms if t not in stop}


def _rerank_and_trim_hits(
    query: str,
    hits: list[dict[str, Any]],
    top_k: int = 4,
    *,
    preferred_fund_slug: str | None = None,
) -> list[dict[str, Any]]:
    """Boost lexical overlap so final context stays tightly on-topic."""
    terms = _query_terms(query)
    pref = (preferred_fund_slug or "").strip()
    if not hits:
        return []
    scored: list[tuple[float, dict[str, Any]]] = []
    for h in hits:
        base = float(h.get("score") or 0.0)
        hay = f"{h.get('source_url', '')} {h.get('content', '')}".lower()
        overlap = sum(1 for t in terms if t in hay)
        score = base + (0.06 * overlap)
        if pref and str(h.get("fund_slug") or "").strip() == pref:
            score += 0.35
        scored.append((score, h))
    scored.sort(key=lambda x: x[0], reverse=True)
    trimmed = [h for _, h in scored[: max(2, top_k)]]
    return trimmed


def _format_sources(urls: list[str]) -> str:
    if not urls:
        return ""
    # Keep citations concise and relevant for chat + TTS.
    top = urls[:1]
    return "Sources:\n" + "\n".join(f"- {u}" for u in top)


def _cache_key(query: str) -> str:
    return f"{_FAQ_CACHE_PREFIX}{query.strip().lower()}"


def _cache_get(query: str) -> tuple[str, list[str]] | None:
    return _FAQ_ANSWER_CACHE.get(_cache_key(query))


def _cache_set(query: str, answer: str, sources: list[str]) -> None:
    key = _cache_key(query)
    if not key:
        return
    if len(_FAQ_ANSWER_CACHE) >= _FAQ_CACHE_MAX:
        # simple FIFO-ish eviction (dict insertion order)
        oldest = next(iter(_FAQ_ANSWER_CACHE.keys()))
        _FAQ_ANSWER_CACHE.pop(oldest, None)
    _FAQ_ANSWER_CACHE[key] = (answer, sources[:2])


def clear_faq_answer_cache() -> int:
    """Clear in-memory FAQ cache for current API process."""
    n = len(_FAQ_ANSWER_CACHE)
    _FAQ_ANSWER_CACHE.clear()
    return n


def _compact(text: str, *, max_len: int = 220) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    if len(t) <= max_len:
        return t
    cut = t[:max_len].rstrip()
    # Avoid ending mid-URL (e.g. "https://groww.") when trimming for chat/TTS limits.
    tail_http = re.search(r"https?://\S*$", cut)
    if tail_http:
        cut = cut[: tail_http.start()].rstrip(" ,;:-")
    m = re.search(r"[.!?](?!.*[.!?])", cut)
    if m:
        return cut[: m.end()].rstrip()
    # Fallback: avoid broken trailing fragments.
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:-")


def _index_fund_exit_load_fallback(
    slug: str | None, fund_url: str | None, hits: list[dict[str, Any]]
) -> tuple[str, list[str]] | None:
    """When chunks omit a clean exit-load line, still answer index schemes without guessing a percentage."""
    if not slug:
        return None
    fund = next((f for f in FUND_SOURCES if f.slug == slug), None)
    if not fund:
        return None
    if "index" not in (fund.category or "").lower():
        return None
    answer = _two_sentences(
        f"{fund.display_name} is an index-oriented scheme in our catalog; official pages usually show exit load as Nil "
        "or not applicable for such funds. Please confirm the exact figure on the scheme page linked under Sources."
    )
    sources = _collect_sources(hits)
    if fund_url and fund_url not in sources:
        sources = [fund_url] + sources
    return answer, sources[:2]


def _prefer_slug_hits(hits: list[dict[str, Any]], slug: str | None) -> list[dict[str, Any]]:
    if not slug:
        return hits
    pref = [h for h in hits if str(h.get("fund_slug") or "").strip() == slug]
    return pref if pref else hits


def _should_run_small_cap_basket_ter_comparison(query: str) -> bool:
    ql = (query or "").lower()
    if not expense_ratio_requested(query):
        return False
    if "small cap" not in ql:
        return False
    if any(k in ql for k in ("compare", "comparison", "versus", "difference", "between")):
        return True
    if "in your database" in ql or "in our database" in ql:
        return True
    return False


def _deterministic_small_cap_expense_comparison(
    session: Session, query: str
) -> tuple[str, list[str]] | None:
    """Compare TER across manifest Small Cap funds without relying on vector ranking."""
    if not _should_run_small_cap_basket_ter_comparison(query):
        return None
    embedder = get_embedder()
    small_caps = [f for f in FUND_SOURCES if f.category == "Small Cap"]
    found: list[tuple[str, str, str]] = []
    for fund in small_caps:
        qh = f"{fund.display_name} expense ratio TER total expense direct plan"
        hits = search_chunks(
            session,
            embedder,
            qh,
            top_k=10,
            preferred_fund_slug=fund.slug,
        )
        slug_hits = [h for h in hits if str(h.get("fund_slug") or "").strip() == fund.slug]
        scan = slug_hits if slug_hits else hits
        blob = "\n".join(str(h.get("content", "")) for h in scan[:8])
        m = _extract_expense_ratio_pct_match(blob)
        if not m:
            continue
        pct_val = m.group(1)
        src_url = fund.url
        for h in scan:
            u = str(h.get("source_url", "")).strip()
            if u:
                src_url = u
                break
        short_label = fund.display_name.replace(" Direct Growth", "").strip()
        found.append((short_label, pct_val, src_url))
    if len(found) < 2:
        return None
    facts = ", ".join(f"{lab}: {pct}%" for lab, pct, _ in found)
    answer = _two_sentences(
        f"From indexed sources, expense ratio comparison for small-cap schemes in our dataset is {facts}. "
        "Lower expense ratio is generally more cost-efficient, all else equal."
    )
    sources: list[str] = []
    for _, _, u in found:
        if u and u not in sources:
            sources.append(u)
    return answer, sources[:3]


def _two_sentences(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "")).strip()
    if not t:
        return ""
    # Preserve list-style deterministic outputs as-is.
    if "\n-" in text:
        return text.strip()
    parts = re.split(r"(?<=[.!?])\s+", t)
    return " ".join(parts[:2]).strip()


def _query_has_specific_fund(query: str) -> bool:
    q = (query or "").lower()
    if resolve_manifest_fund(query)[0]:
        return True
    if any(name and name in q for name in _FUND_NAME_KEYS):
        return True
    # Handle common shorthand mentions for this corpus.
    shorthand = (
        "mirae",
        "hdfc",
        "sbi",
        "kotak",
        "quant",
        "ppfas",
        "parag parikh",
        "nippon",
        "uti",
        "axis",
        "canara",
        "icici",
        "motilal",
    )
    return any(k in q for k in shorthand)


def _is_metric_query(query: str) -> bool:
    q = (query or "").lower()
    return expense_ratio_requested(query) or exit_load_requested(query) or "nav" in q


def _is_concept_query(query: str) -> bool:
    q = (query or "").lower()
    concept_markers = (
        "what is",
        "how is",
        "how does",
        "meaning of",
        "explain",
        "calculate",
    )
    return any(m in q for m in concept_markers)


def _deterministic_metric_clarifier(query: str) -> tuple[str, list[str]] | None:
    q = (query or "").lower()
    if not _is_metric_query(q):
        return None
    is_comparison_shape = any(k in q for k in ("compare", "vs", "versus", "between", "difference"))
    is_category_basket = (
        "funds" in q
        and any(k in q for k in ("small cap", "large cap", "mid cap", "database", "in your database"))
    )
    if is_comparison_shape or is_category_basket:
        return None
    has_fund = _query_has_specific_fund(q)
    is_concept = _is_concept_query(q)
    if "nav" in q and is_concept and not has_fund:
        answer = _two_sentences(
            "NAV means Net Asset Value, i.e., the per-unit value of a mutual fund based on total assets minus liabilities. "
            "If you want the current NAV number, tell me the exact fund name."
        )
        return answer, ["https://investor.sebi.gov.in/securities-mf-investments.html"]
    if expense_ratio_requested(query) and is_concept and not has_fund:
        answer = _two_sentences(
            "Expense ratio is the annual percentage fee a fund charges to manage your money. "
            "If you want the exact value, share the fund name and I will fetch it."
        )
        return answer, ["https://investor.sebi.gov.in/understanding_mf.html"]
    if exit_load_requested(query) and is_concept and not has_fund:
        answer = _two_sentences(
            "Exit load is a fee charged when units are redeemed within a defined period. "
            "If you want the exact percentage, share the fund name."
        )
        return answer, ["https://investor.sebi.gov.in/exit_load.html"]
    if not has_fund:
        metric = (
            "NAV"
            if "nav" in q
            else "expense ratio"
            if expense_ratio_requested(query)
            else "exit load"
        )
        answer = _two_sentences(
            f"I can fetch exact {metric} values, but I need the fund name first. "
            f"Please share the fund, for example: '{metric} of Mirae Asset ELSS'."
        )
        return answer, []
    return None


def _sentences(text: str) -> list[str]:
    raw = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    out: list[str] = []
    for s in raw:
        t = re.sub(r"\s+", " ", s).strip(" -•\t")
        if len(t) < 30:
            continue
        out.append(t)
    return out


def _extract_snippets(query: str, hits: list[dict[str, Any]], limit: int = 3) -> list[str]:
    """Pull readable sentences; for fee metrics use scored lines so exit load does not hijack expense queries."""
    ql = (query or "").lower()
    fee_m = _primary_fee_metric(query)
    snippets: list[str] = []
    seen: set[str] = set()

    def metric_digit_skip(sentence: str) -> bool:
        if not ("nav" in ql or exit_load_requested(query) or expense_ratio_requested(query)):
            return False
        if re.search(r"\d", sentence):
            return False
        if "nil" in sentence.lower():
            return False
        return True

    if fee_m == "expense_ratio":
        ranked: list[tuple[float, str]] = []
        for h in hits:
            for s in _sentences(str(h.get("content", ""))):
                if metric_digit_skip(s):
                    continue
                sc = _snippet_score_expense_ratio(s)
                if sc <= 0:
                    continue
                ranked.append((sc, s[:220].rstrip()))
        ranked.sort(key=lambda x: x[0], reverse=True)
        for sc, s in ranked:
            if s in seen:
                continue
            seen.add(s)
            snippets.append(s)
            if len(snippets) >= limit:
                return snippets
        return snippets

    if fee_m == "exit_load":
        ranked = []
        for h in hits:
            for s in _sentences(str(h.get("content", ""))):
                if metric_digit_skip(s):
                    continue
                sc = _snippet_score_exit_load(s)
                if sc <= 0:
                    continue
                ranked.append((sc, s[:220].rstrip()))
        ranked.sort(key=lambda x: x[0], reverse=True)
        for sc, s in ranked:
            if s in seen:
                continue
            seen.add(s)
            snippets.append(s)
            if len(snippets) >= limit:
                return snippets
        return snippets

    if "nav" in ql:
        keys = ["nav", "net asset value", "asset value"]
    else:
        keys = list(_query_terms(query)) or ["fund", "mutual"]
    for h in hits:
        for s in _sentences(str(h.get("content", ""))):
            low = s.lower()
            if not any(k in low for k in keys):
                continue
            if ("nav" in ql or exit_load_requested(query) or expense_ratio_requested(query)) and metric_digit_skip(s):
                continue
            piece = s[:220].rstrip()
            if piece in seen:
                continue
            seen.add(piece)
            snippets.append(piece)
            if len(snippets) >= limit:
                return snippets
    return snippets


def _extraction_failure_message(query: str, fund_page_url: str | None) -> str:
    msg = (
        "I found related sources in our index, but could not pull an exact figure from the text snippets we have. "
    )
    if fund_page_url:
        msg += "Please open the official scheme page linked under Sources to verify the latest figure. "
    msg += (
        "Try the full official scheme name if unsure—for example "
        "“What is the exit load of UTI Nifty 50 Index Fund Direct Growth?”."
    )
    return _two_sentences(msg)


def _heuristic_answer(
    query: str,
    hits: list[dict[str, Any]],
    *,
    fund_page_url: str | None = None,
) -> str:
    snippets = _extract_snippets(query, hits, limit=3)
    if snippets:
        q = query.lower()
        if exit_load_requested(query):
            intro = "From indexed fund sources, the key exit-load details are:"
        elif "nav" in q:
            intro = "From indexed fund sources, the key NAV details are:"
        elif expense_ratio_requested(query):
            intro = "From indexed sources, the key expense-ratio details are:"
        else:
            intro = "From available sources, the key facts are:"
        joined = "; ".join(_compact(s, max_len=120) for s in snippets[:2])
        return _two_sentences(f"{intro} {joined}.")
    return _extraction_failure_message(query, fund_page_url)


def _collect_sources(hits: list[dict[str, Any]], limit: int = 2) -> list[str]:
    out: list[str] = []
    for h in hits:
        url = str(h.get("source_url", "")).strip()
        if url and url not in out:
            out.append(url)
        if len(out) >= limit:
            break
    return out


def _fund_label(hit: dict[str, Any]) -> str:
    name = str(hit.get("fund_display_name") or "").strip()
    if name:
        return name
    url = str(hit.get("source_url", "")).strip().lower()
    m = re.search(r"/mutual-funds/([a-z0-9\-]+)", url)
    if m:
        slug = m.group(1).replace("-", " ")
        return " ".join(w.capitalize() for w in slug.split())
    return "Fund"


def _deterministic_comparison_answer(query: str, hits: list[dict[str, Any]]) -> tuple[str, list[str]] | None:
    q = query.lower()
    if not any(k in q for k in ("compare", "vs", "versus", "difference", "between")):
        return None

    metric = ""
    metric_re: re.Pattern[str] | None = None
    suffix = ""
    if expense_ratio_requested(query):
        metric = "expense_ratio"
        suffix = "%"
    elif "nav" in q:
        metric = "nav"
        metric_re = re.compile(r"\bnav\b[^0-9₹]{0,30}(?:₹\s*)?([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
        suffix = ""
    else:
        return None

    found: list[tuple[str, str, str]] = []  # label, value, source
    seen_labels: set[str] = set()
    for h in hits:
        text = str(h.get("content", ""))
        if metric == "expense_ratio":
            m = _extract_expense_ratio_pct_match(text)
        else:
            m = metric_re.search(text) if metric_re else None
        if not m:
            continue
        label = _fund_label(h)
        if label.lower() in seen_labels:
            continue
        seen_labels.add(label.lower())
        val = m.group(1)
        src = str(h.get("source_url", "")).strip()
        found.append((label, val, src))
        if len(found) >= 3:
            break

    if len(found) < 2:
        return None

    if metric == "expense_ratio":
        facts = ", ".join(f"{lab}: {val}{suffix}" for lab, val, _ in found)
        answer = _two_sentences(f"From indexed sources, expense ratio comparison is {facts}. Lower expense ratio is generally more cost-efficient, all else equal.")
    else:
        facts = ", ".join(f"{lab}: ₹{val}" for lab, val, _ in found)
        answer = _two_sentences(f"From indexed sources, NAV comparison is {facts}. NAV is a per-unit value and not a standalone performance recommendation.")
    sources = []
    for _, _, src in found:
        if src and src not in sources:
            sources.append(src)
    return answer, sources[:2]


def _deterministic_faq_answer(session: Session, query: str) -> tuple[str, list[str]] | None:
    """
    LLM-light fast path: answer core FAQ intents with deterministic extraction.
    Returns (answer, sources) when confident, else None.
    """
    q = query.lower()
    if not (
        exit_load_requested(query)
        or expense_ratio_requested(query)
        or "nav" in q
        or any(k in q for k in ["compare", "vs", "versus", "difference", "between"])
    ):
        return None

    basket_cmp = _deterministic_small_cap_expense_comparison(session, query)
    if basket_cmp:
        return basket_cmp

    _slug, _fund_url = resolve_manifest_fund(query)
    raw_hits = search_chunks(session, get_embedder(), query, top_k=8, preferred_fund_slug=_slug)
    hits = _prefer_slug_hits(raw_hits, _slug)
    hits = _rerank_and_trim_hits(query, hits, top_k=6, preferred_fund_slug=_slug)
    if not hits:
        return None

    cmp_ans = _deterministic_comparison_answer(query, hits)
    if cmp_ans:
        return cmp_ans

    fee_pri = _primary_fee_metric(query)

    if fee_pri == "exit_load":
        for h in hits:
            text = str(h.get("content", ""))
            detail = _extract_exit_load_detail(text)
            if not detail:
                continue
            main, tail = detail
            answer = _two_sentences(
                f"The exit load is {main}{(' — ' + tail) if tail else ''}. "
                "Funds charge exit load to discourage short-term redemptions and maintain portfolio stability."
            )
            return answer, _collect_sources([h] + hits)
        joined_el = "\n".join(str(h.get("content", "")) for h in hits[:10])
        dj = _extract_exit_load_detail(joined_el)
        if dj:
            main, tail = dj
            answer = _two_sentences(
                f"The exit load is {main}{(' — ' + tail) if tail else ''}. "
                "Funds charge exit load to discourage short-term redemptions and maintain portfolio stability."
            )
            return answer, _collect_sources(hits)
        idx_fb = _index_fund_exit_load_fallback(_slug, _fund_url, hits)
        if idx_fb:
            return idx_fb

    elif fee_pri == "expense_ratio":
        for h in hits:
            text = str(h.get("content", ""))
            m = _extract_expense_ratio_pct_match(text)
            if m:
                pct = m.group(1)
                answer = _two_sentences(f"The expense ratio found in our indexed sources is {pct}%.")
                return answer, _collect_sources([h] + hits)
        joined = "\n".join(str(h.get("content", "")) for h in hits[:10])
        mj = _extract_expense_ratio_pct_match(joined)
        if mj:
            pct = mj.group(1)
            answer = _two_sentences(f"The expense ratio found in our indexed sources is {pct}%.")
            return answer, _collect_sources(hits)

    elif "nav" in q:
        for h in hits:
            text = str(h.get("content", ""))
            # Typical patterns: "NAV: 123.45" or "NAV is ₹123.45"
            m = re.search(r"\bnav\b[^0-9₹]{0,30}(?:₹\s*)?([0-9]+(?:\.[0-9]+)?)", text, re.IGNORECASE)
            if m:
                nav = m.group(1)
                answer = _two_sentences(f"The latest NAV found in our indexed sources is ₹{nav}.")
                return answer, _collect_sources([h] + hits)

    # Concept fallback: short extracted bullets when exact value not parsable.
    snippets = _extract_snippets(query, hits, limit=2)
    if snippets:
        answer = _two_sentences(" ".join(_compact(s, max_len=120) for s in snippets))
        return answer, _collect_sources(hits)
    return None


def _deterministic_coverage_answer(query: str) -> tuple[str, list[str]] | None:
    q = query.lower()
    if not (
        ("what" in q or "which" in q or "list" in q)
        and ("fund" in q or "mutual fund" in q or "schemes" in q)
        and any(k in q for k in ("cover", "covered", "database", "available", "have"))
    ):
        return None
    names = [f.display_name for f in FUND_SOURCES]
    if not names:
        return None
    preview = ", ".join(names[:8])
    extra = len(names) - 8
    if extra > 0:
        preview = f"{preview}, and {extra} more."
    answer = _two_sentences(
        f"We currently cover {len(names)} mutual funds in our indexed dataset, including {preview} "
        "I can also compare specific funds for NAV, expense ratio, or exit load."
    )
    sources = [f.url for f in FUND_SOURCES[:2]]
    return answer, sources


def _deterministic_fund_only_prompt(query: str) -> tuple[str, list[str]] | None:
    q = (query or "").strip().lower()
    if not q or len(q.split()) > 8:
        return None
    has_fund = _query_has_specific_fund(q)
    has_metric = any(k in q for k in ("nav", "aum")) or expense_ratio_requested(query) or exit_load_requested(query)
    if not has_fund or has_metric:
        return None
    answer = _two_sentences(
        "Got it. Please tell me what you want for this fund: NAV, expense ratio, exit load, or AUM."
    )
    return answer, []


def _deterministic_out_of_scope_fund_answer(query: str) -> tuple[str, list[str]] | None:
    q = (query or "").strip().lower()
    if not q:
        return None
    if "fund" not in q and "elss" not in q:
        return None
    # If we already match a covered scheme, this is not out-of-scope.
    if any(name and name in q for name in _FUND_NAME_KEYS):
        return None
    # Detect user asking for a specific named fund.
    if not any(k in q for k in ("tell me about", "what about", "details", "info", "information", "explain")):
        return None
    m = re.search(r"(?:tell me about|what about|details of|info on|information on|explain)\s+(.+)", q)
    if not m:
        return None
    requested = re.sub(r"[?.!,]+$", "", m.group(1)).strip()
    if not requested:
        return None
    covered = [f.display_name for f in FUND_SOURCES]
    preview = ", ".join(covered[:5])
    answer = _two_sentences(
        f"I do not have {requested.title()} in my current indexed database. "
        f"I currently cover funds like {preview}. Ask 'which funds do you cover' to see the full list."
    )
    return answer, [f.url for f in FUND_SOURCES[:2]]


def _deterministic_domain_clarifier(query: str) -> tuple[str, list[str]] | None:
    q = (query or "").strip().lower()
    if not q:
        return None
    chip_label = match_quick_topic_chip_label(query)
    if not looks_like_topic_help_query(query) and not chip_label:
        return None
    if "kyc" in q or "onboarding" in q:
        return (
            _two_sentences(
                "Sure — for KYC & Onboarding, do you want a quick checklist or to book an advisor call?"
            ),
            ["https://investor.sebi.gov.in/"],
        )
    if re.search(r"\bsip\b", q) or "mandate" in q:
        return (
            _two_sentences(
                "Sure — for SIP & mandates, are you asking setup basics, mandate failure troubleshooting, or advisor booking?"
            ),
            ["https://investor.sebi.gov.in/"],
        )
    if ("statement" in q and "tax" in q) or "tax document" in q or "form 16" in q:
        return (
            _two_sentences(
                "Sure — for statements & tax docs, want download steps, Form 16 timing, or transaction history issues?"
            ),
            ["https://investor.sebi.gov.in/"],
        )
    if "withdraw" in q or "withdrawal" in q:
        return (
            _two_sentences(
                "Sure — for withdrawals, are you asking about settlement timelines, limits, or a failed bank transfer?"
            ),
            ["https://investor.sebi.gov.in/"],
        )
    if "account change" in q or "nominee" in q:
        return (
            _two_sentences(
                "Sure — for account changes/nominee updates, do you want required documents, process steps, or advisor booking?"
            ),
            ["https://investor.sebi.gov.in/"],
        )
    return None


def _merge_hits(
    session: Session,
    queries: list[str],
    top_per: int = 4,
    *,
    preferred_fund_slug: str | None = None,
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for q in queries:
        for h in search_chunks(
            session,
            get_embedder(),
            q,
            top_k=top_per,
            layer=None,
            preferred_fund_slug=preferred_fund_slug,
        ):
            key = f"{h.get('source_url', '')}#{h.get('chunk_index', 0)}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(h)
    merged.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
    return merged


def answer_faq(session: Session, query: str) -> AgentResult:
    traces: list[AgentTraceStep] = []

    cached = _cache_get(query)
    if cached:
        cached_answer, cached_sources = cached
        traces.append(
            AgentTraceStep(
                agent="rag_agent",
                reasoning_brief="Served FAQ response from internal cache for low-latency reliability.",
                tools=["faq.cache"],
                replanned=False,
                outcome="cache_hit",
            )
        )
        out = _compact(cached_answer, max_len=220)
        src_block = _format_sources(cached_sources)
        if src_block:
            out = f"{out}\n\n{src_block}"
        return AgentResult(response_text=out, payload={"sources": cached_sources[:2], "confidence": "high"}, traces=traces)

    clarifier = _deterministic_metric_clarifier(query)
    if clarifier:
        answer_body, clarifier_sources = clarifier
        _cache_set(query, answer_body, clarifier_sources)
        traces.append(
            AgentTraceStep(
                agent="rag_agent",
                reasoning_brief="Detected ambiguous metric query and asked clarifying follow-up instead of assuming fund.",
                tools=["faq.metric_clarifier"],
                replanned=False,
                outcome="clarification_prompt",
            )
        )
        out = _compact(answer_body, max_len=220)
        src_block = _format_sources(clarifier_sources)
        if src_block:
            out = f"{out}\n\n{src_block}"
        return AgentResult(response_text=out, payload={"sources": clarifier_sources[:1], "confidence": "high"}, traces=traces)

    domain_clarifier = _deterministic_domain_clarifier(query)
    if domain_clarifier:
        answer_body, clarifier_sources = domain_clarifier
        traces.append(
            AgentTraceStep(
                agent="rag_agent",
                reasoning_brief="Detected broad help-topic query and asked concise disambiguation prompt.",
                tools=["faq.domain_clarifier"],
                replanned=False,
                outcome="clarification_prompt",
            )
        )
        out = _compact(answer_body, max_len=220)
        src_block = _format_sources(clarifier_sources)
        if src_block:
            out = f"{out}\n\n{src_block}"
        return AgentResult(response_text=out, payload={"sources": clarifier_sources[:1], "confidence": "high"}, traces=traces)

    deterministic = _deterministic_faq_answer(session, query)
    if deterministic:
        answer_body, det_sources = deterministic
        _cache_set(query, answer_body, det_sources)
        traces.append(
            AgentTraceStep(
                agent="rag_agent",
                reasoning_brief="Answered core FAQ intent using deterministic extraction without LLM.",
                tools=["vector.search", "faq.fast_path"],
                replanned=False,
                outcome="fast_path_answer",
            )
        )
        out = _compact(answer_body, max_len=220)
        src_block = _format_sources(det_sources)
        if src_block:
            out = f"{out}\n\n{src_block}"
        return AgentResult(response_text=out, payload={"sources": det_sources[:1], "confidence": "high"}, traces=traces)

    deterministic_coverage = _deterministic_coverage_answer(query)
    if deterministic_coverage:
        answer_body, det_sources = deterministic_coverage
        _cache_set(query, answer_body, det_sources)
        traces.append(
            AgentTraceStep(
                agent="rag_agent",
                reasoning_brief="Answered source-coverage query deterministically to avoid noisy synthesis.",
                tools=["faq.coverage_fast_path"],
                replanned=False,
                outcome="coverage_fast_path",
            )
        )
        out = _compact(answer_body, max_len=220)
        src_block = _format_sources(det_sources)
        if src_block:
            out = f"{out}\n\n{src_block}"
        return AgentResult(response_text=out, payload={"sources": det_sources[:1], "confidence": "high"}, traces=traces)

    out_of_scope = _deterministic_out_of_scope_fund_answer(query)
    if out_of_scope:
        answer_body, det_sources = out_of_scope
        traces.append(
            AgentTraceStep(
                agent="rag_agent",
                reasoning_brief="Detected named fund outside indexed corpus and returned explicit coverage boundary.",
                tools=["faq.coverage_guard"],
                replanned=False,
                outcome="out_of_scope_fund",
            )
        )
        out = _compact(answer_body, max_len=220)
        src_block = _format_sources(det_sources)
        if src_block:
            out = f"{out}\n\n{src_block}"
        return AgentResult(response_text=out, payload={"sources": det_sources[:1], "confidence": "high"}, traces=traces)

    fund_only = _deterministic_fund_only_prompt(query)
    if fund_only:
        answer_body, det_sources = fund_only
        traces.append(
            AgentTraceStep(
                agent="rag_agent",
                reasoning_brief="Detected fund-only follow-up and asked user for one specific metric.",
                tools=["faq.fund_metric_clarifier"],
                replanned=False,
                outcome="clarification_prompt",
            )
        )
        out = _compact(answer_body, max_len=180)
        return AgentResult(response_text=out, payload={"sources": det_sources[:1], "confidence": "high"}, traces=traces)

    if llm_available():
        plan_res = chat_completion_safe(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a retrieval planner for Finn (Indian mutual fund support). "
                        'Output ONLY valid JSON: {"search_queries":["q1","q2"],"reasoning":"one sentence"}. '
                        "Use 1-3 short English search strings for a vector DB over Groww fund pages + SEBI docs. "
                        "Prefer specific fund names if present in the user question."
                    ),
                },
                {"role": "user", "content": query},
            ],
            temperature=0.15,
        )
        plan_obj = parse_json_object(plan_res.text) if plan_res.text else None
        reasoning = (plan_obj or {}).get("reasoning", "") if isinstance(plan_obj, dict) else ""
        raw_qs = (plan_obj or {}).get("search_queries") if isinstance(plan_obj, dict) else None
        queries: list[str] = []
        if isinstance(raw_qs, list):
            queries = [str(x).strip() for x in raw_qs if str(x).strip()][:3]
        if not queries:
            queries = [query]
        traces.append(
            AgentTraceStep(
                agent="rag_agent",
                reasoning_brief=reasoning or "Planned retrieval queries using LLM.",
                tools=[f"llm.{plan_res.provider}", "retrieval_plan"],
                replanned=False,
                outcome=(
                    f"planned_queries={queries}"
                    if plan_res.provider != "none"
                    else f"planned_queries={queries}; llm_error={plan_res.error[:220]}"
                ),
            )
        )

        plan_slug, plan_url = resolve_manifest_fund(query)
        hits = _merge_hits(session, queries, preferred_fund_slug=plan_slug)
        if plan_slug:
            slug_only = [h for h in hits if str(h.get("fund_slug") or "").strip() == plan_slug]
            if slug_only:
                hits = slug_only
        traces.append(
            AgentTraceStep(
                agent="rag_agent",
                reasoning_brief="Executed vector search for each planned query and merged/deduped hits.",
                tools=["vector.search(multi_query)"],
                replanned=False,
                outcome=f"hits={len(hits)}",
            )
        )

        if not hits:
            return AgentResult(
                response_text=(
                    "I could not find reliable fund data for that yet. I can still help with advisor booking, "
                    "or you can rephrase the question."
                ),
                payload={"sources": [], "confidence": "low"},
                traces=traces,
            )

        top = _rerank_and_trim_hits(query, hits, top_k=4, preferred_fund_slug=plan_slug)
        context_blocks = []
        source_by_idx: dict[int, str] = {}
        for idx, h in enumerate(top, start=1):
            url = str(h.get("source_url", ""))
            source_by_idx[idx] = url
            context_blocks.append(f"[{idx}] URL: {url}\nEXCERPT:\n{str(h.get('content', ''))[:900]}")
        context = "\n\n---\n\n".join(context_blocks)

        ans_res = chat_completion_safe(
            [
                {
                    "role": "system",
                    "content": (
                        "You are Finn (Groww-style assistant). Use ONLY provided excerpts. "
                        "Return STRICT JSON only with this schema: "
                        '{"answer":"string","used_source_indices":[1,2]}. '
                        "answer rules: conversational, concise, default to max 2 sentences for simple questions, "
                        "no raw chunk dumping, no ellipses from excerpts, "
                        "include concrete values when present (NAV, %, period), and if data is insufficient say that clearly. "
                        "Metric discipline: if the user asks only for expense ratio (or TER), do not answer with exit-load figures (and vice versa), "
                        "unless the question explicitly asks for both. "
                        "used_source_indices rules: include only 1-2 excerpt indices actually used for the final answer."
                    ),
                },
                {
                    "role": "user",
                    "content": f"QUESTION:\n{query}\n\nEXCERPTS:\n{context}",
                },
            ],
            temperature=0.25,
        )
        traces.append(
            AgentTraceStep(
                agent="rag_agent",
                reasoning_brief="Synthesized a grounded answer from retrieved chunks using LLM.",
                tools=[f"llm.{ans_res.provider}", "rag.synthesize"],
                replanned=False,
                outcome=(
                    "answer_ready"
                    if ans_res.provider != "none"
                    else f"answer_fallback; llm_error={ans_res.error[:220]}"
                ),
            )
        )
        parsed = parse_json_object(ans_res.text) if ans_res.text else None
        answer_body = ""
        used_urls: list[str] = []
        if isinstance(parsed, dict):
            answer_body = str(parsed.get("answer", "")).strip()
            raw_indices = parsed.get("used_source_indices")
            if isinstance(raw_indices, list):
                for x in raw_indices[:2]:
                    try:
                        idx = int(x)
                    except (TypeError, ValueError):
                        continue
                    url = source_by_idx.get(idx)
                    if url and url not in used_urls:
                        used_urls.append(url)
        if not used_urls:
            # Fallback: keep citations tight to top 1-2 reranked sources.
            for h in top:
                url = str(h.get("source_url", "")).strip()
                if url and url not in used_urls:
                    used_urls.append(url)
                if len(used_urls) >= 2:
                    break
        if not answer_body:
            # Non-LLM/parse fallback: provide query-specific extracted facts.
            answer_body = _heuristic_answer(query, top, fund_page_url=plan_url)
        answer = _two_sentences(answer_body.strip())
        src_block = _format_sources(used_urls)
        if src_block:
            answer = f"{answer}\n\n{src_block}"
        _cache_set(query, answer_body, used_urls)
        return AgentResult(
            response_text=_compact(answer, max_len=520),
            payload={"sources": used_urls[:1], "confidence": "medium"},
            traces=traces,
        )

    # --- Deterministic fallback (no LLM keys) ---
    fb_slug, fb_url = resolve_manifest_fund(query)
    first_hits = _prefer_slug_hits(
        search_chunks(session, get_embedder(), query, top_k=4, preferred_fund_slug=fb_slug),
        fb_slug,
    )
    traces.append(
        AgentTraceStep(
            agent="rag_agent",
            reasoning_brief="First retrieval pass across indexed RAG chunks.",
            tools=["vector.search(top_k=4)"],
            replanned=False,
            outcome=f"hits={len(first_hits)}",
        )
    )

    best_score = first_hits[0]["score"] if first_hits else -1.0
    hits = first_hits
    replanned = False
    if best_score < 0.1 or len(first_hits) < 2:
        hits = _prefer_slug_hits(
            search_chunks(
                session,
                get_embedder(),
                f"{query} expense ratio exit load nav",
                top_k=5,
                preferred_fund_slug=fb_slug,
            ),
            fb_slug,
        )
        replanned = True
        traces.append(
            AgentTraceStep(
                agent="rag_agent",
                reasoning_brief="Initial retrieval weak; reformulated query and retried.",
                tools=["vector.search(retry_query, top_k=5)"],
                replanned=True,
                outcome=f"retry_hits={len(hits)}",
            )
        )

    if not hits:
        return AgentResult(
            response_text=(
                "I could not find reliable fund data for that yet. I can still help with advisor booking, "
                "or you can rephrase the question."
            ),
            payload={"sources": [], "confidence": "low"},
            traces=traces,
        )

    top = _rerank_and_trim_hits(query, hits, top_k=3, preferred_fund_slug=fb_slug)
    sources: list[str] = []
    for h in top:
        url = str(h.get("source_url", "")).strip()
        if url and url not in sources:
            sources.append(url)
        if len(sources) >= 2:
            break
    response = _two_sentences(_heuristic_answer(query, top, fund_page_url=fb_url))
    src_block = _format_sources(sources)
    if src_block:
        response = f"{response}\n\n{src_block}"
    if replanned:
        response = "I refined the search once to improve relevance.\n\n" + response
    _cache_set(query, response, sources[:2])
    return AgentResult(
        response_text=_compact(response, max_len=520),
        payload={"sources": sources[:1], "confidence": "medium"},
        traces=traces,
    )
