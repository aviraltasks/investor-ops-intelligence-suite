"""RAG specialist agent for FAQ/fund queries (LLM plan + synthesize when keys are set)."""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.agents.types import AgentResult, AgentTraceStep
from app.llm.client import chat_completion_safe, llm_available, parse_json_object
from app.rag.embed import get_embedder
from app.rag.search import search_chunks


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
                outcome=f"planned_queries={queries}",
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
                        "answer rules: conversational, concise, no raw chunk dumping, no ellipses from excerpts, "
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
                outcome="answer_ready",
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
            # Non-LLM/parse fallback: concise summary instead of chunk dumps.
            answer_body = (
                "I found related information, but I cannot confidently extract an exact value from the indexed text for this query. "
                "Please rephrase with a specific fund and metric, or I can help book an advisor session."
            )
        answer = answer_body.strip()
        src_block = _format_sources(used_urls)
        if src_block:
            answer = f"{answer}\n\n{src_block}"
        return AgentResult(
            response_text=answer,
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
    response = (
        "I found relevant information in the knowledge base, but cannot confidently synthesize a precise final value without LLM support. "
        "Please enable LLM keys for high-quality synthesized FAQ responses."
    )
    src_block = _format_sources(sources)
    if src_block:
        response = f"{response}\n\n{src_block}"
    if replanned:
        response = "I refined the search once to improve relevance.\n\n" + response
    return AgentResult(
        response_text=response,
        payload={"sources": sources[:2], "confidence": "medium"},
        traces=traces,
    )
