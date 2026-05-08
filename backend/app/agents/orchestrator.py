"""Orchestrator agent coordinating specialist agents."""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.agents.email_agent import draft_advisor_email
from app.agents.memory_agent import (
    clear_pending_schedule_confirm,
    clear_pending_scheduling_clarify,
    get_pending_schedule_confirm,
    get_pending_scheduling_clarify,
    load_context,
    save_fact,
)
from app.agents.rag_agent import answer_faq
from app.agents.review_intel_agent import get_trending_context
from app.agents.scheduling_agent import (
    booking_context_prefix_for_topic,
    handle_scheduling,
    is_scheduling_confirmation_message,
    is_scheduling_rejection_message,
    wants_what_to_prepare_message,
)
from app.agents.topic_routing import match_quick_support_topic_label, message_suggests_support_faq
from app.agents.types import AgentResult, AgentTraceStep
from app.llm.client import chat_completion_safe, llm_available, parse_json_object
from app.scheduling.slot_resolution import message_looks_like_slot_refinement


def _contains_any(text: str, keywords: list[str]) -> bool:
    t = text.lower()
    return any(k in t for k in keywords)


def _classify_intents(message: str) -> list[str]:
    intents: list[str] = []
    m = message.lower()
    wants_prepare = wants_what_to_prepare_message(m)
    scheduling_focus = wants_prepare or _contains_any(
        m,
        [
            "book",
            "appointment",
            "reschedule",
            "cancel",
            "availability",
            "available",
            "waitlist",
            "wait list",
        ],
    )
    if _contains_any(m, ["what did we discuss", "what did we talk", "remember", "last time", "recap", "summary"]):
        intents.append("memory_recall")
    if scheduling_focus:
        intents.append("scheduling")
    if not wants_prepare and _contains_any(m, ["expense ratio", "exit load", "nav", "fund", "elss", "small cap", "large cap"]):
        intents.append("faq")
    if message_suggests_support_faq(message, scheduling_focus=scheduling_focus):
        intents.append("faq")
    if _contains_any(m, ["pulse", "theme", "review trend", "trending", "customers are saying"]):
        intents.append("review_context")
    if not intents:
        intents.append("general")
    return intents


def _has_pii(text: str) -> bool:
    t = text or ""
    patterns = [
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        r"(?:\+91[\s-]?)?[6-9]\d{9}\b",
        r"\b[A-Z]{5}\d{4}[A-Z]\b",
        r"\b\d{12}\b",
    ]
    return any(re.search(p, t, flags=re.IGNORECASE) for p in patterns)


def _is_investment_advice_request(text: str) -> bool:
    return _contains_any(
        text.lower(),
        [
            "which fund should i buy",
            "which fund should i invest",
            "guaranteed",
            "20% return",
            "recommend the best fund",
            "should i invest",
            "should i withdraw",
            "portfolio allocation advice",
            "better than",
        ],
    )


def _is_prompt_injection_attempt(text: str) -> bool:
    return _contains_any(
        text.lower(),
        [
            "ignore instructions",
            "ignore your previous instructions",
            "you are now",
            "system prompt",
            "reveal your instructions",
            "act as financial advisor",
            "hack this",
            "ceo email",
        ],
    )


def _is_name_query(text: str) -> bool:
    t = (text or "").lower()
    return any(
        p in t
        for p in (
            "what is your name",
            "what's your name",
            "who are you",
            "your name",
        )
    )


def _looks_like_scheduling_followup_fragment(text: str) -> bool:
    """Short follow-up while clarifying booking time (avoids merging FAQ questions into book flow)."""
    t = (text or "").strip().lower()
    if not t or len(t) > 72:
        return False
    if re.search(r"\b(\d{1,2})(:\d{2})?\s*(am|pm|a\.m\.|p\.m\.)\b", t):
        return True
    if re.search(r"\b\d{1,2}\s*(am|pm)\b", t):
        return True
    if re.search(r"\b\d{3,4}\s*(am|pm)\b", t):
        return True
    if len(t) <= 28:
        if any(
            w in t
            for w in (
                "tomorrow",
                "today",
                "next week",
                "monday",
                "tuesday",
                "wednesday",
                "thursday",
                "friday",
            )
        ):
            return True
        if re.match(r"^(yes|yeah|yup|ok|okay|sure)\b", t):
            return True
    return False


def _fresh_booking_resets_clarify(text: str) -> bool:
    """User sent a full booking request; drop stale rolling clarify from earlier errors."""
    raw = (text or "").strip()
    if len(raw) < 22:
        return False
    m = raw.lower()
    if "book" not in m and "appointment" not in m:
        return False
    return any(
        p in m
        for p in (
            "book me",
            "book an",
            "book a ",
            "book appointment",
            "book slot",
            "appointment for",
            "for kyc",
            "for sip",
            "book kyc",
        )
    )


def _is_brief_greeting(text: str) -> bool:
    t = re.sub(r"\s+", " ", (text or "").lower()).strip()
    return t in {
        "hi",
        "hi there",
        "hello",
        "hello there",
        "hey",
        "hey there",
        "good morning",
        "good afternoon",
        "good evening",
        "thanks",
        "thank you",
        "thankyou",
        "ok",
        "okay",
    }


def _compact_reply(text: str, *, max_len: int = 200) -> str:
    body = (text or "").strip()
    if not body:
        return ""
    parts = body.split("\n\nSources:\n", 1)
    # Preserve two-line memory reminder style messages as-is for continuity UX.
    if "Quick reminder:" in parts[0]:
        pre = parts[0].strip()
        if len(pre) <= max_len + 120:
            concise = pre
        else:
            concise = pre[: max_len + 120].rstrip()
        if len(parts) == 2 and parts[1].strip():
            lines = [ln for ln in parts[1].splitlines() if ln.strip()]
            if lines:
                concise += "\n\nSources:\n" + lines[0]
        return concise
    if re.search(r"Learn more:\s*https?://", parts[0], flags=re.IGNORECASE):
        raw = parts[0].strip()
        lines = [ln.rstrip() for ln in raw.splitlines()]
        tail = next((ln for ln in reversed(lines) if ln.lower().startswith("learn more:")), "")
        head_lines = [ln for ln in lines if not ln.lower().startswith("learn more:")]
        head = "\n".join(head_lines).strip()
        head_one = re.sub(r"\s+", " ", head).strip()
        if len(head_one) <= max_len + 160:
            concise = f"{head}\n\n{tail}".strip() if tail else head
        else:
            concise = f"{head_one[:max_len].rstrip()}…\n\n{tail}".strip() if tail else head_one[:max_len]
        if len(parts) == 2 and parts[1].strip():
            src_lines = [ln for ln in parts[1].splitlines() if ln.strip()]
            if src_lines:
                concise += "\n\nSources:\n" + src_lines[0]
        return concise
    main = re.sub(r"\s+", " ", parts[0]).strip()
    sentences = re.split(r"(?<=[.!?])\s+", main)
    concise = " ".join(sentences[:2]).strip()[:max_len].rstrip()
    if len(parts) == 2 and parts[1].strip():
        lines = [ln for ln in parts[1].splitlines() if ln.strip()]
        if lines:
            concise += "\n\nSources:\n" + lines[0]
    return concise


def _should_skip_memory_fact(message: str) -> bool:
    t = re.sub(r"\s+", " ", (message or "").lower()).strip()
    if not t:
        return True
    # Ignore likely bot-echo captures from voice mode.
    echo_markers = (
        "i provide factual mutual fund information",
        "i do not provide investment advice",
        "help schedule advisor appointments",
        "mandatory advisor appointments",
    )
    return any(m in t for m in echo_markers)


def handle_chat_turn(session: Session, session_id: str, user_name: str, message: str) -> AgentResult:
    traces: list[AgentTraceStep] = []
    payload: dict[str, Any] = {}

    mem_ctx, mem_trace = load_context(session, session_id, user_name)
    traces.append(mem_trace)
    trend_ctx, trend_trace = get_trending_context(session)
    traces.append(trend_trace)

    sanitized_message = (message or "").strip()
    if not sanitized_message:
        return AgentResult(
            response_text="Please share your question or request, and I will help right away.",
            traces=[
                *traces,
                AgentTraceStep(
                    agent="orchestrator",
                    reasoning_brief="Detected empty input and asked user to provide a valid prompt.",
                    tools=["input_guard"],
                    outcome="empty_input",
                ),
            ],
            payload={"intents": ["general"]},
        )

    pending_confirm = get_pending_schedule_confirm(session, session_id)
    pc_snapshot = pending_confirm
    if (
        pc_snapshot
        and str(pc_snapshot.get("kind") or "") == "book"
        and not is_scheduling_confirmation_message(sanitized_message)
        and not is_scheduling_rejection_message(sanitized_message)
        and message_looks_like_slot_refinement(sanitized_message)
    ):
        clear_pending_schedule_confirm(session, session_id)
        sanitized_message = f"{booking_context_prefix_for_topic(str(pc_snapshot.get('topic') or ''))}{sanitized_message}".strip()
        traces.append(
            AgentTraceStep(
                agent="orchestrator",
                reasoning_brief="User sent a new date/time while a booking preview was pending — cleared confirm state and re-parsed slot.",
                tools=["scheduling.slot_refinement"],
                outcome="booking_slot_refinement",
            )
        )
        pending_confirm = None

    force_scheduling_confirm_reply = bool(pending_confirm) and (
        is_scheduling_confirmation_message(sanitized_message)
        or is_scheduling_rejection_message(sanitized_message)
    )

    clarify_snapshot = get_pending_scheduling_clarify(session, session_id)
    if clarify_snapshot and _fresh_booking_resets_clarify(sanitized_message):
        clear_pending_scheduling_clarify(session, session_id)
        clarify_snapshot = None
    if (
        clarify_snapshot
        and not pending_confirm
        and _looks_like_scheduling_followup_fragment(sanitized_message)
    ):
        rt = str(clarify_snapshot.get("rolling_text") or "").strip()
        if rt:
            # Keep newest slot phrase first so parser prioritizes latest user correction
            # (e.g., old "7:00 AM" + new "5:00 PM Monday" should honor 5:00 PM Monday).
            sanitized_message = f"{sanitized_message} {rt}".strip()
            traces.append(
                AgentTraceStep(
                    agent="orchestrator",
                    reasoning_brief="Merged slot follow-up with prior booking utterance while prioritizing latest user time/date correction.",
                    tools=["scheduling.clarify_merge"],
                    outcome="scheduling_context_merge",
                )
            )

    if _has_pii(sanitized_message):
        return AgentResult(
            response_text=(
                "I cannot process personal details in chat. Please use the secure booking page to share phone/email."
            ),
            traces=[
                *traces,
                AgentTraceStep(
                    agent="orchestrator",
                    reasoning_brief="Detected sensitive personal information and blocked it from chat handling.",
                    tools=["pii_guard", "secure_page_redirect"],
                    outcome="pii_blocked",
                ),
            ],
            payload={"intents": ["safety"], "safe_redirect": "/secure/[bookingCode]"},
        )

    if _is_prompt_injection_attempt(sanitized_message):
        return AgentResult(
            response_text=(
                "I cannot follow instruction overrides or share restricted information. I can still help with FAQs and booking support."
            ),
            traces=[
                *traces,
                AgentTraceStep(
                    agent="orchestrator",
                    reasoning_brief="Blocked prompt-injection style request and stayed within assistant constraints.",
                    tools=["prompt_injection_guard"],
                    outcome="injection_refused",
                ),
            ],
            payload={"intents": ["safety"]},
        )

    if _is_investment_advice_request(sanitized_message):
        return AgentResult(
            response_text=(
                "I cannot provide investment recommendations or guaranteed return advice. I can share factual fund data or help you book an advisor session."
            ),
            traces=[
                *traces,
                AgentTraceStep(
                    agent="orchestrator",
                    reasoning_brief="Detected investment advice request and returned policy-safe refusal with alternatives.",
                    tools=["investment_advice_guard"],
                    outcome="advice_refused",
                ),
            ],
            payload={"intents": ["safety"]},
        )

    if _is_name_query(sanitized_message):
        return AgentResult(
            response_text="I am Finn, your mutual-fund support and advisor-scheduling assistant.",
            traces=[
                *traces,
                AgentTraceStep(
                    agent="orchestrator",
                    reasoning_brief="Handled identity query directly with concise assistant introduction.",
                    tools=["identity_reply"],
                    outcome="identity_answer",
                ),
            ],
            payload={"intents": ["general"]},
        )

    quick_topic = match_quick_support_topic_label(sanitized_message)
    if quick_topic:
        return AgentResult(
            response_text=(
                f"Got it — {quick_topic}. Do you want 1) quick checklist, 2) issue troubleshooting, or 3) book an advisor call?"
            ),
            traces=[
                *traces,
                AgentTraceStep(
                    agent="orchestrator",
                    reasoning_brief="Detected quick-topic help prompt and asked concise clarification instead of broad RAG synthesis.",
                    tools=["quick_topic_clarifier"],
                    outcome="clarification_prompt",
                ),
            ],
            payload={"intents": ["general"], "quick_topic": quick_topic, "status": "needs_topic_action_choice"},
        )

    allowed = {"faq", "scheduling", "memory_recall", "review_context", "general"}
    intent_trace: AgentTraceStep | None = None
    if force_scheduling_confirm_reply:
        intents = ["scheduling"]
        intent_trace = AgentTraceStep(
            agent="orchestrator",
            reasoning_brief="SCRIPT/PRD: pending schedule confirmation — user said yes/no; scheduling agent must handle it.",
            tools=["confirmation_gate", "memory.pending_schedule_confirm"],
            outcome="intents=[scheduling]_confirm_reply",
        )
    elif llm_available():
        ctx_blob = json.dumps(
            {
                "recent_topics": mem_ctx.get("recent_topics", []),
                "pending_booking": mem_ctx.get("pending_booking_code"),
                "pending_status": mem_ctx.get("pending_booking_status"),
                "top_pulse_theme": trend_ctx.get("top_theme"),
            },
            default=str,
        )[:1800]
        route = chat_completion_safe(
            [
                {
                    "role": "system",
                    "content": (
                        "You are Finn's orchestrator (Groww-style fintech assistant). "
                        'Output ONLY valid JSON: {"intents":["..."],"reasoning":"one or two sentences"}. '
                        "Allowed intent strings (1-3): faq, scheduling, memory_recall, review_context, general. "
                        "faq=fund/MF concepts plus account ops (KYC, onboarding, SIP/mandates, statements/tax docs, withdrawals); "
                        "scheduling=book/cancel/reschedule/availability/waitlist/what_to_prepare; "
                        "memory_recall=recap/what we discussed; review_context=pulse/themes/reviews; "
                        "general=greeting or small talk. Never output investment advice."
                    ),
                },
                {
                    "role": "user",
                    "content": f"user_name={user_name}\nCONTEXT_JSON={ctx_blob}\nMESSAGE={sanitized_message}",
                },
            ],
            temperature=0.1,
        )
        obj = parse_json_object(route.text) if route.text else None
        reasoning = ""
        intents: list[str] = []
        if isinstance(obj, dict):
            reasoning = str(obj.get("reasoning", "") or "").strip()[:500]
            raw = obj.get("intents")
            if isinstance(raw, list):
                intents = [str(x).strip().lower() for x in raw if str(x).strip().lower() in allowed]
        if not intents:
            intents = _classify_intents(sanitized_message)
            intent_trace = AgentTraceStep(
                agent="orchestrator",
                reasoning_brief="LLM routing missing or unparsable; used keyword intent fallback.",
                tools=["intent_fallback(keyword)", "memory_context", "pulse_context"],
                outcome=f"intents={intents}",
            )
        else:
            tool = f"llm.{route.provider}" if route.provider != "none" else "llm.none"
            intent_trace = AgentTraceStep(
                agent="orchestrator",
                reasoning_brief=reasoning or "LLM classified intents using memory and pulse context.",
                tools=[tool, "memory_context", "pulse_context"],
                outcome=f"intents={intents}",
            )
            wants_prepare = wants_what_to_prepare_message(sanitized_message.lower())
            sch_focus = wants_prepare or _contains_any(
                sanitized_message.lower(),
                [
                    "book",
                    "appointment",
                    "reschedule",
                    "cancel",
                    "availability",
                    "available",
                    "waitlist",
                    "wait list",
                ],
            )
            if "faq" not in intents and message_suggests_support_faq(sanitized_message, scheduling_focus=sch_focus):
                intents.insert(0, "faq")
    else:
        intents = _classify_intents(sanitized_message)
        intent_trace = AgentTraceStep(
            agent="orchestrator",
            reasoning_brief="No LLM API keys configured; routed via keyword intent classifier.",
            tools=["intent_classifier(keyword)", "memory_context", "pulse_context"],
            outcome=f"intents={intents}",
        )

    if "faq" in intents and "general" in intents:
        intents = [i for i in intents if i != "general"]

    payload["intents"] = intents
    if intent_trace:
        traces.append(intent_trace)

    responses: list[str] = []
    booking_code: str | None = None

    for intent in intents:
        if intent == "faq":
            rag = answer_faq(session, sanitized_message)
            traces.extend(rag.traces)
            responses.append(rag.response_text)
            payload["sources"] = rag.payload.get("sources", [])
        elif intent == "memory_recall":
            topics = mem_ctx.get("recent_topics", [])
            pending_code = mem_ctx.get("pending_booking_code")
            if topics:
                recall = "Here is what we discussed recently: " + "; ".join(topics[:3]) + "."
            else:
                recall = "I do not have enough prior discussion context yet for this user."
            if pending_code:
                recall += f" You also have an active booking ({pending_code}) in {mem_ctx.get('pending_booking_status')} status."
            responses.append(recall)
        elif intent == "scheduling":
            sch = handle_scheduling(session, session_id, user_name, sanitized_message)
            traces.extend(sch.traces)
            responses.append(sch.response_text)
            payload.update(sch.payload)
            booking_code = sch.payload.get("booking_code")
        elif intent == "review_context":
            top = trend_ctx.get("top_theme")
            if top:
                responses.append(f"Latest customer trend: {top}.")
            else:
                responses.append("I can generate a pulse once review data is refreshed.")
        else:
            top = trend_ctx.get("top_theme")
            memory_prefix = ""
            if mem_ctx.get("is_returning_user") and mem_ctx.get("recent_topics"):
                memory_prefix = f"Welcome back {user_name or 'there'}! Last time we discussed {mem_ctx['recent_topics'][0]}. "
            mlow = sanitized_message.lower()
            show_pulse_teaser = bool(top) and _contains_any(
                mlow,
                [
                    "trend",
                    "trending",
                    "pulse",
                    "review theme",
                    "what are people",
                    "customers saying",
                    "customers are saying",
                ],
            )
            if show_pulse_teaser and top:
                responses.append(
                    f"{memory_prefix}Hi {user_name or 'there'}! I notice '{top}' is trending this week. I can help with fund FAQs or booking."
                )
            else:
                responses.append(
                    f"{memory_prefix}Hi {user_name or 'there'}! I can help with mutual fund FAQs and advisor appointment scheduling."
                )
            pending_code = mem_ctx.get("pending_booking_code")
            if pending_code:
                responses.append(
                    f"Quick reminder: your booking {pending_code} is currently {mem_ctx.get('pending_booking_status')}."
                )

    if booking_code:
        email = draft_advisor_email(session, booking_code)
        traces.extend(email.traces)
        payload["advisor_email_draft"] = email.payload

    # Save memory fact for continuity.
    if not _should_skip_memory_fact(sanitized_message):
        fact_value = sanitized_message[:300]
        traces.append(save_fact(session, session_id, user_name or "User", "last_user_message", fact_value))

    final_text = "\n\n".join([r for r in responses if r]).strip()
    if not final_text:
        final_text = "I can help with FAQs, booking, or review trends. What would you like to do?"

    if llm_available() and len([r for r in responses if r]) > 1:
        bundle = "\n\n---\n\n".join(f"SECTION_{i+1}:\n{r}" for i, r in enumerate(responses) if r)
        syn = chat_completion_safe(
            [
                {
                    "role": "system",
                    "content": (
                        "You are Finn. Merge SECTION_* blocks into ONE cohesive chat reply. "
                        "Preserve all factual details (booking codes, dates, times, URLs from RAG). "
                        "Do not contradict specialists. No investment advice."
                    ),
                },
                {
                    "role": "user",
                    "content": f"ORIGINAL_USER_MESSAGE:\n{sanitized_message}\n\nSPECIALIST_OUTPUTS:\n{bundle}",
                },
            ],
            temperature=0.3,
        )
        if syn.provider != "none" and syn.text.strip():
            final_text = syn.text.strip()
            traces.append(
                AgentTraceStep(
                    agent="orchestrator",
                    reasoning_brief="Merged multiple specialist outputs with LLM into a single user-facing reply.",
                    tools=[f"llm.{syn.provider}", "response_synthesizer"],
                    outcome="synthesized",
                )
            )

    # Keep default UX concise for chat/voice while preserving source line if present.
    final_text = _compact_reply(final_text)
    payload["debug"] = {
        "clarification_prompt_count": sum(1 for t in traces if "clarification_prompt" in (t.outcome or "")),
        "fallback_answer_count": sum(
            1
            for t in traces
            if "fallback" in (t.outcome or "") or "llm_error" in (t.outcome or "")
        ),
        "trace_count": len(traces),
    }

    return AgentResult(response_text=final_text, payload=payload, traces=traces)
