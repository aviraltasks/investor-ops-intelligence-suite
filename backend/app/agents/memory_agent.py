"""Memory agent: load/save lightweight conversation memory facts."""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import delete, desc, select
from sqlalchemy.orm import Session

from app.db.models import Booking, MemoryFact
from app.agents.types import AgentTraceStep

PENDING_SCHEDULE_CONFIRM_KEY = "pending_schedule_confirm"


def _normalized_user_name(user_name: str) -> str:
    return (user_name or "").strip() or "User"


def _scrub_pii(value: str) -> str:
    cleaned = value
    # Email addresses.
    cleaned = re.sub(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "[redacted-email]", cleaned)
    # Indian and generic phone numbers.
    cleaned = re.sub(r"(?:\+91[\s-]?)?[6-9]\d{9}\b", "[redacted-phone]", cleaned)
    # PAN-like patterns.
    cleaned = re.sub(r"\b[A-Z]{5}\d{4}[A-Z]\b", "[redacted-id]", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def load_context(session: Session, session_id: str, user_name: str) -> tuple[dict, AgentTraceStep]:
    normalized_user = _normalized_user_name(user_name)
    session_facts = list(
        session.scalars(
            select(MemoryFact).where(MemoryFact.session_id == session_id).order_by(desc(MemoryFact.created_at)).limit(8)
        )
    )
    user_facts = list(
        session.scalars(
            select(MemoryFact)
            .where(MemoryFact.user_name == normalized_user)
            .order_by(desc(MemoryFact.created_at))
            .limit(12)
        )
    )
    booking = session.scalar(
        select(Booking).where(Booking.session_id == session_id).order_by(desc(Booking.created_at)).limit(1)
    )
    pending_user_booking = session.scalar(
        select(Booking)
        .where(Booking.customer_name == normalized_user)
        .where(Booking.status.in_(["tentative", "confirmed", "waitlisted"]))
        .order_by(desc(Booking.created_at))
        .limit(1)
    )
    recent_topics = []
    for fact in user_facts:
        if fact.key != "last_user_message":
            continue
        if not fact.value:
            continue
        recent_topics.append(fact.value[:120])
        if len(recent_topics) >= 3:
            break
    ctx = {
        "recent_facts": [{"key": f.key, "value": f.value} for f in session_facts],
        "recent_user_facts": [{"key": f.key, "value": f.value, "session_id": f.session_id} for f in user_facts],
        "recent_topics": recent_topics,
        "is_returning_user": len(user_facts) > len(session_facts),
        "latest_booking_code": booking.booking_code if booking else None,
        "latest_booking_topic": booking.topic if booking else None,
        "pending_booking_code": pending_user_booking.booking_code if pending_user_booking else None,
        "pending_booking_status": pending_user_booking.status if pending_user_booking else None,
        "pending_booking_topic": pending_user_booking.topic if pending_user_booking else None,
    }
    trace = AgentTraceStep(
        agent="memory_agent",
        reasoning_brief="Loaded session + cross-session memory and pending booking context.",
        tools=["db.select(memory_facts)", "db.select(bookings by session/user)"],
        outcome="context_loaded",
    )
    return ctx, trace


def get_pending_schedule_confirm(session: Session, session_id: str) -> dict[str, Any] | None:
    """Latest JSON payload for two-phase book/cancel/reschedule (SCRIPT_FLOW)."""
    fact = session.scalar(
        select(MemoryFact)
        .where(MemoryFact.session_id == session_id)
        .where(MemoryFact.key == PENDING_SCHEDULE_CONFIRM_KEY)
        .order_by(desc(MemoryFact.created_at))
        .limit(1)
    )
    if not fact or not fact.value:
        return None
    try:
        out = json.loads(fact.value)
        return out if isinstance(out, dict) else None
    except json.JSONDecodeError:
        return None


def save_pending_schedule_confirm(session: Session, session_id: str, user_name: str, payload: dict[str, Any]) -> None:
    normalized_user = _normalized_user_name(user_name)
    session.add(
        MemoryFact(
            session_id=session_id,
            user_name=normalized_user,
            key=PENDING_SCHEDULE_CONFIRM_KEY,
            value=json.dumps(payload),
        )
    )
    session.commit()


def clear_pending_schedule_confirm(session: Session, session_id: str) -> None:
    session.execute(
        delete(MemoryFact).where(MemoryFact.session_id == session_id).where(MemoryFact.key == PENDING_SCHEDULE_CONFIRM_KEY)
    )
    session.commit()


def save_fact(session: Session, session_id: str, user_name: str, key: str, value: str) -> AgentTraceStep:
    normalized_user = _normalized_user_name(user_name)
    safe_value = _scrub_pii(value)
    session.add(MemoryFact(session_id=session_id, user_name=normalized_user, key=key, value=safe_value))
    session.commit()
    return AgentTraceStep(
        agent="memory_agent",
        reasoning_brief="Persisted non-PII memory fact from current turn.",
        tools=["pii_scrubber", "db.insert(memory_facts)"],
        outcome="fact_saved_safe",
    )
