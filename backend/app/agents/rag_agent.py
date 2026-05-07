"""RAG specialist agent for FAQ/fund queries (LLM plan + synthesize when keys are set)."""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.agents.types import AgentResult, AgentTraceStep
from app.llm.client import chat_completion_safe, llm_available, parse_json_object
from app.db.models import RagChunk
from app.rag.embed import get_embedder
from app.rag.search import search_chunks
from app.sources.manifest import FUND_SOURCES

_FAQ_ANSWER_CACHE: dict[str, tuple[str, list[str]]] = {}
_FAQ_CACHE_MAX = 300


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


def _rerank_and_trim_hits(query: str, hits: list[dict[str, Any]], top_k: int = 4) -> list[dict[str, Any]]:
    """Boost lexical overlap so final context stays tightly on-topic."""
    terms = _query_terms(query)
    if not hits:
        return []
    scored: list[tuple[float, dict[str, Any]]] = []
    for h in hits:
        base = float(h.get("score") or 0.0)
        hay = f"{h.get('source_url', '')} {h.get('content', '')}".lower()
        overlap = sum(1 for t in terms if t in hay)
        score = base + (0.06 * overlap)
        scored.append((score, h))
    scored.sort(key=lambda x: x[0], reverse=True)
    trimmed = [h for _, h in scored[: max(2, top_k)]]
    return trimmed


def _format_sources(urls: list[str]) -> str:
    if not urls:
        return ""
    # Keep citations concise and relevant for chat + TTS.
    top = urls[:2]
    return "Sources:\n" + "\n".join(f"- {u}" for u in top)


def _cache_get(query: str) -> tuple[str, list[str]] | None:
    return _FAQ_ANSWER_CACHE.get(query.strip().lower())


def _cache_set(query: str, answer: str, sources: list[str]) -> None:
    key = query.strip().lower()
    if not key:
        return
    if len(_FAQ_ANSWER_CACHE) >= _FAQ_CACHE_MAX:
        # simple FIFO-ish eviction (dict insertion order)
        oldest = next(iter(_FAQ_ANSWER_CACHE.keys()))
        _FAQ_ANSWER_CACHE.pop(oldest, None)
    _FAQ_ANSWER_CACHE[key] = (answer, sources[:2])


def _compact(text: str, *, max_len: int = 220) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    return t[:max_len].rstrip()


def _two_sentences(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "")).strip()
    if not t:
        return ""
    # Preserve list-style deterministic outputs as-is.
    if "\n-" in text:
        return text.strip()
    parts = re.split(r"(?<=[.!?])\s+", t)
    return " ".join(parts[:2]).strip()


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
    q = query.lower()
    if "exit load" in q:
        keys = ["exit load", "redeem", "redemption", "lock-in", "elss"]
    elif "nav" in q:
        keys = ["nav", "net asset value", "asset value"]
    elif "expense ratio" in q:
        keys = ["expense ratio", "expense", "%"]
    else:
        keys = _query_terms(query) or {"fund", "mutual"}
    snippets: list[str] = []
    seen: set[str] = set()
    for h in hits:
        for s in _sentences(str(h.get("content", ""))):
            low = s.lower()
            if not any(k in low for k in keys):
                continue
            if ("nav" in q or "exit load" in q or "expense ratio" in q) and not re.search(r"\d", s):
                continue
            s = s[:220].rstrip()
            if s in seen:
                continue
            seen.add(s)
            snippets.append(s)
            if len(snippets) >= limit:
                return snippets
    return snippets


def _heuristic_answer(query: str, hits: list[dict[str, Any]]) -> str:
    snippets = _extract_snippets(query, hits, limit=3)
    if snippets:
        q = query.lower()
        if "exit load" in q:
            intro = "From indexed fund sources, the key exit-load details are:"
        elif "nav" in q:
            intro = "From indexed fund sources, the key NAV details are:"
        elif "expense ratio" in q:
            intro = "From indexed sources, the key expense-ratio details are:"
        else:
            intro = "From available sources, the key facts are:"
        joined = "; ".join(_compact(s, max_len=120) for s in snippets[:2])
        return _two_sentences(f"{intro} {joined}.")
    return (
        "I found related sources, but I could not extract a precise value for this exact query from current indexed text. "
        "Please ask with fund name plus exact metric (for example, 'expense ratio of <fund>')."
    )


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
    if "expense ratio" in q:
        metric = "expense_ratio"
        metric_re = re.compile(r"expense ratio[^.\n]{0,80}?(\d+(?:\.\d+)?)\s*%", re.IGNORECASE)
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
        m = metric_re.search(text)
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
    if not any(k in q for k in ["exit load", "nav", "expense ratio", "compare", "vs", "versus", "difference", "between"]):
        return None
    hits = _rerank_and_trim_hits(query, search_chunks(session, get_embedder(), query, top_k=8), top_k=6)
    if not hits:
        return None

    cmp_ans = _deterministic_comparison_answer(query, hits)
    if cmp_ans:
        return cmp_ans

    if "exit load" in q:
        for h in hits:
            text = str(h.get("content", ""))
            m = re.search(r"exit load[^.\n]{0,120}?(\d+(?:\.\d+)?)\s*%([^.\n]{0,120})", text, re.IGNORECASE)
            if m:
                pct = m.group(1)
                tail = _compact(m.group(2), max_len=80)
                answer = _two_sentences(
                    f"The exit load is {pct}%{(' ' + tail) if tail else ''}. "
                    "Funds charge exit load to discourage short-term redemptions and maintain portfolio stability."
                )
                return answer, _collect_sources([h] + hits)

    if "nav" in q:
        for h in hits:
            text = str(h.get("content", ""))
            # Typical patterns: "NAV: 123.45" or "NAV is ₹123.45"
            m = re.search(r"\bnav\b[^0-9₹]{0,30}(?:₹\s*)?([0-9]+(?:\.[0-9]+)?)", text, re.IGNORECASE)
            if m:
                nav = m.group(1)
                answer = _two_sentences(f"The latest NAV found in our indexed sources is ₹{nav}.")
                return answer, _collect_sources([h] + hits)

    if "expense ratio" in q:
        for h in hits:
            text = str(h.get("content", ""))
            m = re.search(r"expense ratio[^.\n]{0,80}?(\d+(?:\.\d+)?)\s*%", text, re.IGNORECASE)
            if m:
                pct = m.group(1)
                answer = _two_sentences(f"The expense ratio found in our indexed sources is {pct}%.")
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


def _merge_hits(session: Session, queries: list[str], top_per: int = 4) -> list[dict[str, Any]]:
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for q in queries:
        for h in search_chunks(session, get_embedder(), q, top_k=top_per, layer=None):
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
        out = _compact(cached_answer, max_len=240)
        src_block = _format_sources(cached_sources)
        if src_block:
            out = f"{out}\n\n{src_block}"
        return AgentResult(response_text=out, payload={"sources": cached_sources[:2], "confidence": "high"}, traces=traces)

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
        out = _compact(answer_body, max_len=260)
        src_block = _format_sources(det_sources)
        if src_block:
            out = f"{out}\n\n{src_block}"
        return AgentResult(response_text=out, payload={"sources": det_sources[:2], "confidence": "high"}, traces=traces)

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
        out = _compact(answer_body, max_len=320)
        src_block = _format_sources(det_sources)
        if src_block:
            out = f"{out}\n\n{src_block}"
        return AgentResult(response_text=out, payload={"sources": det_sources[:2], "confidence": "high"}, traces=traces)

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

        hits = _merge_hits(session, queries)
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

        top = _rerank_and_trim_hits(query, hits, top_k=4)
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
            answer_body = _heuristic_answer(query, top)
        answer = _two_sentences(answer_body.strip())
        src_block = _format_sources(used_urls)
        if src_block:
            answer = f"{answer}\n\n{src_block}"
        _cache_set(query, answer_body, used_urls)
        return AgentResult(
            response_text=_compact(answer, max_len=520),
            payload={"sources": used_urls[:2], "confidence": "medium"},
            traces=traces,
        )

    # --- Deterministic fallback (no LLM keys) ---
    first_hits = search_chunks(session, get_embedder(), query, top_k=4)
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
        hits = search_chunks(session, get_embedder(), f"{query} expense ratio exit load nav", top_k=5)
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

    top = _rerank_and_trim_hits(query, hits, top_k=3)
    sources: list[str] = []
    for h in top:
        url = str(h.get("source_url", "")).strip()
        if url and url not in sources:
            sources.append(url)
        if len(sources) >= 2:
            break
    response = _two_sentences(_heuristic_answer(query, top))
    src_block = _format_sources(sources)
    if src_block:
        response = f"{response}\n\n{src_block}"
    if replanned:
        response = "I refined the search once to improve relevance.\n\n" + response
    _cache_set(query, response, sources[:2])
    return AgentResult(
        response_text=_compact(response, max_len=520),
        payload={"sources": sources[:2], "confidence": "medium"},
        traces=traces,
    )
