"""RAG specialist agent for FAQ/fund queries (LLM plan + synthesize when keys are set)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.agents.types import AgentResult, AgentTraceStep
from app.llm.client import chat_completion_safe, llm_available, parse_json_object
from app.rag.embed import get_embedder
from app.rag.search import search_chunks


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

        top = hits[:6]
        context_blocks = []
        sources: list[str] = []
        for h in top:
            url = str(h.get("source_url", ""))
            if url and url not in sources:
                sources.append(url)
            context_blocks.append(f"URL: {url}\nEXCERPT:\n{str(h.get('content', ''))[:900]}")
        context = "\n\n---\n\n".join(context_blocks)

        ans_res = chat_completion_safe(
            [
                {
                    "role": "system",
                    "content": (
                        "You are Finn. Answer the user using ONLY the excerpts. "
                        "If excerpts are insufficient, say so honestly. "
                        "Do not invent fund facts. Cite sources by listing their URLs at the end on one line "
                        'starting exactly with "Sources: " then comma-separated URLs you relied on.'
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
        answer = (
            ans_res.text.strip()
            if ans_res.provider != "none" and ans_res.text.strip()
            else (
                "Here is what I found from the current knowledge base:\n"
                + "\n".join(f"- {h['content'][:160]}..." for h in top[:3])
                + "\n\nSources: "
                + ", ".join(sources)
            )
        )
        if sources and "Sources:" not in answer:
            answer = answer.rstrip() + "\n\nSources: " + ", ".join(sources)
        return AgentResult(
            response_text=answer,
            payload={"sources": sources, "confidence": "medium"},
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

    top = hits[:3]
    snippets = []
    sources = []
    for h in top:
        snippets.append(f"- {h['content'][:160]}...")
        if h["source_url"] not in sources:
            sources.append(h["source_url"])

    response = (
        "Here is what I found from the current knowledge base:\n"
        + "\n".join(snippets)
        + "\n\nSources: "
        + ", ".join(sources)
    )
    if replanned:
        response = "I refined the search once to improve relevance.\n\n" + response
    return AgentResult(
        response_text=response,
        payload={"sources": sources, "confidence": "medium"},
        traces=traces,
    )
