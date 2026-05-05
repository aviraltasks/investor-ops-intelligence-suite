"""Email drafting specialist agent (HITL draft content only)."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.types import AgentResult, AgentTraceStep
from app.db.models import Booking
from app.llm.client import chat_completion_safe, llm_available, parse_json_object
from app.ml.theme_pipeline import get_latest_pulse


def draft_advisor_email(session: Session, booking_code: str) -> AgentResult:
    booking = session.scalar(select(Booking).where(Booking.booking_code == booking_code))
    if not booking:
        return AgentResult(
            response_text="I could not find the booking for email drafting.",
            traces=[
                AgentTraceStep(
                    agent="email_drafting_agent",
                    reasoning_brief="Booking code not found for draft.",
                    tools=["db.select(bookings)"],
                    outcome="booking_missing",
                )
            ],
        )
    pulse = get_latest_pulse(session)
    top_theme = None
    if pulse and pulse.get("top_themes"):
        top_theme = pulse["top_themes"][0]["label"]

    facts = {
        "booking_code": booking.booking_code,
        "topic": booking.topic,
        "date": booking.date,
        "time_ist": booking.time_ist,
        "advisor": booking.advisor,
        "customer_name": booking.customer_name,
        "concern_summary": booking.concern_summary,
        "top_review_theme": top_theme,
        "pulse_id": pulse.get("pulse_id") if pulse else None,
    }
    template_body = (
        f"## Booking details\n{booking.booking_code} | {booking.topic} | {booking.date} {booking.time_ist} | {booking.advisor}\n\n"
        f"## User concern\n{booking.concern_summary}\n\n"
        f"## Market / sentiment context\nTop review theme: '{top_theme or 'not available yet'}'."
    )
    body = template_body
    tools = ["db.select(bookings)", "db.select(pulse_runs)"]
    reasoning = "Composed 3-section advisor briefing draft using booking + latest pulse context."

    if llm_available():
        res = chat_completion_safe(
            [
                {
                    "role": "system",
                    "content": (
                        "You draft a professional internal email to a financial advisor. "
                        "Output valid JSON only with keys: subject, booking_details, user_concern, market_context. "
                        "Each value is one concise paragraph in plain English. "
                        "booking_details must include booking code, date, time IST, advisor, topic, customer name. "
                        "market_context must tie to the provided top_review_theme when present; otherwise say data is not yet available. "
                        "Do not invent facts beyond FACTS_JSON."
                    ),
                },
                {
                    "role": "user",
                    "content": f"FACTS_JSON:\n{json.dumps(facts, default=str)[:3500]}",
                },
            ],
            temperature=0.35,
        )
        if res.provider != "none" and res.text.strip():
            tools.append(f"llm.{res.provider}")
            obj = parse_json_object(res.text)
            if isinstance(obj, dict):
                subj = str(obj.get("subject") or "Advisor briefing").strip()
                b = str(obj.get("booking_details") or "").strip()
                u = str(obj.get("user_concern") or "").strip()
                m = str(obj.get("market_context") or "").strip()
                if b and u and m:
                    body = f"Subject: {subj}\n\n## Booking details\n{b}\n\n## User concern\n{u}\n\n## Market / sentiment context\n{m}"
                    reasoning = "Generated 3-section advisor email via LLM from booking + pulse facts (HITL-ready)."

    return AgentResult(
        response_text="Prepared advisor email draft for HITL review.",
        payload={"booking_code": booking.booking_code, "draft_text": body},
        traces=[
            AgentTraceStep(
                agent="email_drafting_agent",
                reasoning_brief=reasoning,
                tools=tools,
                outcome="draft_ready",
            )
        ],
    )
