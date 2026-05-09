"""Scheduling specialist: book, reschedule, cancel, prepare, availability, waitlist (PRD + SCRIPT_FLOW)."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import random
import re
import string
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.memory_agent import (
    clear_last_fulfilled_booking,
    clear_pending_schedule_confirm,
    clear_pending_scheduling_clarify,
    get_last_fulfilled_booking,
    get_pending_schedule_confirm,
    save_last_fulfilled_booking,
    save_pending_schedule_confirm,
    save_pending_scheduling_clarify,
)
from app.agents.types import AgentResult, AgentTraceStep
from app.db.models import Booking
from app.config import get_booking_max_days_ahead
from app.integrations.service import sync_booking_cancelled, sync_booking_created
from app.llm.client import chat_completion_safe, llm_available
from app.scheduling.slot_resolution import resolve_booking_slot

TOPICS = [
    "KYC & Onboarding",
    "SIP & Mandates",
    "Statements & Tax Documents",
    "Withdrawals & Timelines",
    "Account Changes & Nominee Updates",
]

SEBI_INVESTOR_EDU = "https://investor.sebi.gov.in/"

_PREPARE_CHECKLISTS: dict[str, str] = {
    "KYC & Onboarding": f"""For a KYC & Onboarding session, it helps to have:
- Your PAN card details ready
- Aadhaar or address proof accessible
- Bank account details for linking
- About 15 minutes of uninterrupted time

Learn more: {SEBI_INVESTOR_EDU}""",
    "SIP & Mandates": f"""For SIP & Mandates, consider having:
- Your current SIP details if any
- Bank mandate or auto-pay setup information
- Your investment timeline in mind

Learn more: {SEBI_INVESTOR_EDU}""",
    "Statements & Tax Documents": f"""For Statements & Tax Documents, keep handy:
- The financial year you need statements for
- Your portfolio overview
- Any specific tax forms you're looking for

Learn more: {SEBI_INVESTOR_EDU}""",
    "Withdrawals & Timelines": f"""For Withdrawals & Timelines, it helps to know:
- Which investment you're looking to withdraw from
- Your expected timeline
- Any lock-in periods that may apply

Learn more: {SEBI_INVESTOR_EDU}""",
    "Account Changes & Nominee Updates": f"""For Account Changes & Nominee updates, have ready:
- Current nominee details if updating
- New details you want to change
- ID proof for verification

Learn more: {SEBI_INVESTOR_EDU}""",
}

_PREPARE_TOPIC_PROMPT = (
    "Happy to help. Which topic should I prepare you for: "
    "1) KYC, 2) SIP, 3) Statements/Tax, 4) Withdrawals, 5) Account/Nominee? "
    "Reply with name or number."
)


def wants_what_to_prepare_message(msg: str) -> bool:
    """SCRIPT_FLOW Flow 6 — route to scheduling (not FAQ)."""
    m = msg.lower()
    phrases = (
        "what to prepare",
        "what should i prepare",
        "what do i prepare",
        "what should i bring",
        "what to bring",
        "what do i bring",
        "how should i prepare",
        "what to have ready",
        "prepare for my appointment",
        "prepare for the appointment",
        "prepare for advisor",
        "prepare for my session",
        "appointment checklist",
        "session checklist",
        "what do i need for my session",
        "what documents do i need",
        "what should i have ready",
    )
    if any(p in m for p in phrases):
        return True
    if "prepare" in m and any(
        x in m for x in ("appointment", "session", "advisor", "meeting", "call with advisor")
    ):
        return True
    return False


def _extract_booking_code(text: str) -> str | None:
    """Waitlist codes GRW-W-XXXX must match before plain GRW-XXXX."""
    u = text.upper()
    m = re.search(r"\bGRW-W-[A-Z0-9]{4}\b", u)
    if m:
        return m.group(0)
    m = re.search(r"\bGRW-[A-Z0-9]{4}\b", u)
    return m.group(0) if m else None


def _extract_topic(text: str) -> str:
    t = text.lower()
    if "kyc" in t:
        return TOPICS[0]
    if "sip" in t or "mandate" in t:
        return TOPICS[1]
    if "statement" in t or "tax" in t:
        return TOPICS[2]
    if "withdraw" in t:
        return TOPICS[3]
    if "nominee" in t or "account change" in t:
        return TOPICS[4]
    return "General support"


def booking_context_prefix_for_topic(topic: str) -> str:
    """Seed natural-language book utterances when user refines slot after a preview."""
    t = (topic or "").strip()
    by_topic = {
        TOPICS[0]: "book kyc ",
        TOPICS[1]: "book sip ",
        TOPICS[2]: "book statements ",
        TOPICS[3]: "book withdrawal ",
        TOPICS[4]: "book nominee ",
    }
    return by_topic.get(t, "book slot ")


def message_signals_new_scheduling_request(message: str) -> bool:
    """User is explicitly starting or changing a scheduling action (vs. ambient slot-like text after a completed booking)."""
    m = re.sub(r"\s+", " ", (message or "").lower()).strip()
    if not m:
        return False
    if m.startswith("book") or m.startswith("cancel"):
        return True
    needles = (
        " book ",
        "booking",
        "schedule",
        "appointment",
        "reschedule",
        "cancel ",
        "cancel my",
        "waitlist",
        "wait list",
        "availability",
        "available slot",
        "advisor call",
        "advisor session",
        "meet with",
        "another appointment",
        "another booking",
        "new appointment",
        "new booking",
        "different time",
        "change the time",
        "change my booking",
        "move my",
        "pick a ",
        " slot ",
        "join the waitlist",
    )
    return any(n in m for n in needles)


def _time_plain_for_display(time_ist: str) -> str:
    s = (time_ist or "").strip()
    raw = s[:-4].strip() if s.endswith(" IST") else s
    m = re.match(r"^(\d{1,2}):(\d{2})$", raw)
    if not m:
        return raw
    hh = int(m.group(1))
    mm = int(m.group(2))
    suffix = "AM" if hh < 12 else "PM"
    hh12 = hh % 12 or 12
    return f"{hh12}:{mm:02d} {suffix}"


def _extract_time_ist(text: str) -> tuple[str, str] | None:
    slot, reason = resolve_booking_slot(text, max_days_ahead=get_booking_max_days_ahead())
    return slot if reason == "ok" else None


def _extract_time_ist_with_reason(text: str) -> tuple[tuple[str, str] | None, str]:
    return resolve_booking_slot(text, max_days_ahead=get_booking_max_days_ahead())


def _wants_reschedule(msg: str) -> bool:
    m = msg.lower()
    if "reschedule" in m:
        return True
    return bool(re.search(r"\b(move|change)\b.+\b(appointment|booking|session|slot)\b", m))


def _topic_from_numeric_or_name(text: str) -> str | None:
    """Map user reply like '2' or 'sip' to a canonical TOPICS entry."""
    raw = text.strip().lower()
    if raw in ("1", "one", "first", "kyc"):
        return TOPICS[0]
    if raw in ("2", "two", "second", "sip", "mandate"):
        return TOPICS[1]
    if raw in ("3", "three", "third", "statement", "tax"):
        return TOPICS[2]
    if raw in ("4", "four", "fourth", "withdraw", "withdrawal"):
        return TOPICS[3]
    if raw in ("5", "five", "fifth", "nominee", "account change"):
        return TOPICS[4]
    for topic in TOPICS:
        if topic.lower() in raw:
            return topic
        head = topic.split("&")[0].strip().lower()
        if len(head) > 3 and head in raw:
            return topic
    return None


def _resolve_booking_for_prepare(session: Session, session_id: str, message: str) -> Booking | None:
    code = _extract_booking_code(message)
    if code and not code.startswith("GRW-W-"):
        b = session.scalar(select(Booking).where(Booking.booking_code == code))
        if b and b.status in ("tentative", "confirmed"):
            return b
    return session.scalar(
        select(Booking)
        .where(Booking.session_id == session_id)
        .where(Booking.status.in_(["tentative", "confirmed"]))
        .order_by(Booking.created_at.desc())
        .limit(1)
    )


def _dedicated_waitlist_request(msg: str) -> bool:
    """User asks to join waitlist (not a normal book with a valid slot)."""
    m = msg.lower()
    if "cancel" in m or "reschedule" in m or "availability" in m or "available" in m:
        return False
    if "waitlist" in m or "wait list" in m or "wait-listed" in m:
        return True
    if "join" in m and "wait" in m:
        return True
    if "add me" in m and ("waitlist" in m or "wait list" in m):
        return True
    return False


def _booking_card_payload_row(b: Booking) -> dict[str, Any]:
    """Chat UI booking strip: needs code + slot fields (not only on happy-path confirm)."""
    return {
        "booking_code": b.booking_code,
        "date": b.date,
        "time_ist": b.time_ist,
        "topic": b.topic,
        "advisor": b.advisor,
    }


def _llm_polish_scheduling_reply(*, user_message: str, draft: str, payload: dict[str, Any], action: str) -> str:
    if not llm_available():
        return draft
    slim = {k: v for k, v in payload.items() if k != "integration_sync"}
    facts = json.dumps({"action": action, "facts": slim}, default=str)[:2400]
    res = chat_completion_safe(
        [
            {
                "role": "system",
                "content": (
                    "You are Finn's scheduling voice. Rewrite DRAFT in warm, concise English for chat. "
                    "Keep every factual detail from FACTS_JSON (booking codes, dates, times, IST labels, advisor names, slot lists). "
                    "Do not invent or remove facts."
                ),
            },
            {
                "role": "user",
                "content": f"DRAFT:\n{draft}\n\nFACTS_JSON:\n{facts}\n\nUSER_MESSAGE:\n{user_message}",
            },
        ],
        temperature=0.35,
    )
    if res.provider != "none" and res.text.strip():
        return res.text.strip()
    return draft


def _new_booking_code(session: Session) -> str:
    while True:
        code = "GRW-" + "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(4))
        exists = session.scalar(select(func.count()).select_from(Booking).where(Booking.booking_code == code))
        if not exists:
            return code


def _new_waitlist_code(session: Session) -> str:
    while True:
        code = "GRW-W-" + "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(4))
        exists = session.scalar(select(func.count()).select_from(Booking).where(Booking.booking_code == code))
        if not exists:
            return code


def _resolve_booking_for_reschedule(session: Session, session_id: str, message: str) -> Booking | None:
    code = _extract_booking_code(message)
    if code and not code.startswith("GRW-W-"):
        return session.scalar(select(Booking).where(Booking.booking_code == code))
    return session.scalar(
        select(Booking)
        .where(Booking.session_id == session_id)
        .where(Booking.status.in_(["tentative", "confirmed"]))
        .order_by(Booking.created_at.desc())
        .limit(1)
    )


def _waitlist_booking_response(
    *,
    session: Session,
    session_id: str,
    user_name: str,
    message: str,
    topic: str,
    traces: list[AgentTraceStep],
) -> AgentResult:
    code = _new_waitlist_code(session)
    advisor_idx = (session.scalar(select(func.count()).select_from(Booking)) or 0) % 5 + 1
    advisor = f"Advisor {advisor_idx}"
    booking = Booking(
        session_id=session_id,
        customer_name=user_name or "User",
        topic=topic,
        date="TBD",
        time_ist="As available (IST weekdays)",
        advisor=advisor,
        booking_code=code,
        status="waitlisted",
        concern_summary=message[:400],
    )
    session.add(booking)
    session.flush()
    sync = sync_booking_created(booking)
    booking.calendar_event_id = (sync.get("calendar") or {}).get("reference")
    booking.sheet_row_ref = (sync.get("sheets") or {}).get("reference")
    booking.email_status = "draft_queued"
    booking.integration_meta = sync
    session.commit()
    traces.append(
        AgentTraceStep(
            agent="scheduling_agent",
            reasoning_brief="Created waitlist entry with GRW-W code, calendar waitlist hold, sheet row, advisor draft queue.",
            tools=[
                "waitlist_code_generator",
                "db.insert(bookings.status=waitlisted)",
                "calendar.create_waitlist_hold",
                "sheets.upsert_row",
                "gmail.queue_draft",
            ],
            outcome="waitlisted",
        )
    )
    payload: dict[str, Any] = {
        "booking_code": code,
        "topic": topic,
        "status": "waitlisted",
        "date": booking.date,
        "time_ist": booking.time_ist,
        "advisor": advisor,
        "integration_sync": sync,
    }
    draft = (
        f"I'm sorry — there aren't confirmed slots matching that preference right now. "
        f"I've added you to the waitlist. Your waitlist code is {code}. "
        f"I'll create a waitlist calendar hold and notify the advisor team. "
        f"You can try a different weekday time (Mon–Fri, 9 AM–6 PM IST) anytime, or check back. Anything else?"
    )
    polished = _llm_polish_scheduling_reply(
        user_message=message, draft=draft, payload=payload, action="waitlist"
    )
    if polished != draft:
        traces.append(
            AgentTraceStep(
                agent="scheduling_agent",
                reasoning_brief="Polished waitlist confirmation with LLM while preserving code and facts.",
                tools=["llm.naturalize_scheduling_reply"],
                outcome="llm_voice",
            )
        )
    return AgentResult(response_text=polished, payload=payload, traces=traces)


def is_scheduling_confirmation_message(message: str) -> bool:
    """Explicit yes / confirm (SCRIPT_FLOW — short replies only)."""
    raw = (message or "").strip().lower()
    raw = re.sub(r"[^\w\s']", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    if not raw or len(raw) > 64:
        return False
    exact = {
        "yes",
        "yeah",
        "yep",
        "sure",
        "ok",
        "okay",
        "confirm",
        "confirmed",
        "please confirm",
        "go ahead",
        "please do",
        "lock it in",
        "proceed",
        "sounds good",
        "absolutely",
        "definitely",
        "do it",
    }
    if raw in exact:
        return True
    if any(raw.startswith(s + " ") for s in ("yes", "yeah", "yep", "sure", "ok", "okay", "confirm", "go", "please")):
        return True
    if "lock it in" in raw:
        return True
    return False


def is_scheduling_rejection_message(message: str) -> bool:
    """Decline pending action; do not treat 'cancel my booking GRW-…' as a bare reject."""
    raw = (message or "").strip().lower()
    raw = re.sub(r"[^\w\s']", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    if not raw or len(raw) > 56:
        return False
    if "grw" in raw.replace(" ", ""):
        return False
    if raw in ("no", "nope", "nah", "cancel", "stop"):
        return True
    prefixes = (
        "no ",
        "nope ",
        "don't ",
        "do not ",
        "dont ",
        "never mind",
        "nevermind",
        "forget it",
        "changed my mind",
    )
    return any(raw.startswith(p) for p in prefixes)


def _execute_confirmed_book(
    session: Session,
    session_id: str,
    user_name: str,
    message: str,
    pending: dict[str, Any],
    traces: list[AgentTraceStep],
) -> AgentResult:
    topic = str(pending.get("topic", "General support"))
    date_str = str(pending["date"])
    time_ist = str(pending["time_ist"])
    advisor_idx = int(pending["advisor_idx"])
    concern = str(pending.get("concern_summary", ""))[:400]

    conflict = session.scalar(
        select(Booking)
        .where(Booking.date == date_str)
        .where(Booking.time_ist == time_ist)
        .where(Booking.status.in_(["tentative", "confirmed", "waitlisted"]))
        .limit(1)
    )
    if conflict:
        clear_pending_schedule_confirm(session, session_id)
        return AgentResult(
            response_text=(
                f"That slot was just taken (booking {conflict.booking_code}). "
                "Please pick another time and we can try again."
            ),
            traces=traces
            + [
                AgentTraceStep(
                    agent="scheduling_agent",
                    reasoning_brief="Confirm failed: slot conflict after confirmation step.",
                    tools=["db.select(bookings)"],
                    outcome="book_confirm_conflict",
                )
            ],
            payload={"status": "conflict", **_booking_card_payload_row(conflict)},
        )

    code = _new_booking_code(session)
    booking = Booking(
        session_id=session_id,
        customer_name=user_name or "User",
        topic=topic,
        date=date_str,
        time_ist=time_ist,
        advisor=f"Advisor {advisor_idx}",
        booking_code=code,
        status="tentative",
        concern_summary=concern,
    )
    session.add(booking)
    session.flush()
    sync = sync_booking_created(booking)
    booking.calendar_event_id = (sync.get("calendar") or {}).get("reference")
    booking.sheet_row_ref = (sync.get("sheets") or {}).get("reference")
    booking.email_status = "draft_queued"
    booking.integration_meta = sync
    session.commit()
    clear_pending_schedule_confirm(session, session_id)
    save_last_fulfilled_booking(
        session,
        session_id,
        user_name or "User",
        {
            "date": date_str,
            "time_ist": time_ist,
            "booking_code": code,
            "kind": "book",
            "topic": topic,
            "advisor": f"Advisor {advisor_idx}",
        },
    )
    traces.append(
        AgentTraceStep(
            agent="scheduling_agent",
            reasoning_brief="User confirmed — created booking, integrations, cleared pending confirm.",
            tools=[
                "confirmation_gate",
                "db.insert(bookings)",
                "calendar.create_hold",
                "sheets.upsert_row",
            ],
            outcome="booked_tentative",
        )
    )
    out_payload: dict[str, Any] = {
        "booking_code": code,
        "topic": topic,
        "date": date_str,
        "time_ist": time_ist,
        "advisor": f"Advisor {advisor_idx}",
        "status": "tentative",
        "integration_sync": sync,
    }
    draft = (
        f"You're all set. Booking Code: {code}. Date: {date_str}, Time: {_time_plain_for_display(time_ist)} IST, "
        f"Topic: {topic}, Advisor: Advisor {advisor_idx}. "
        "Please visit the secure page and enter your booking code to share contact details when ready."
    )
    polished = _llm_polish_scheduling_reply(user_message=message, draft=draft, payload=out_payload, action="book")
    if polished != draft:
        traces.append(
            AgentTraceStep(
                agent="scheduling_agent",
                reasoning_brief="Polished post-confirm booking message with LLM.",
                tools=["llm.naturalize_scheduling_reply"],
                outcome="llm_voice",
            )
        )
    return AgentResult(response_text=polished, payload=out_payload, traces=traces)


def _execute_confirmed_cancel(
    session: Session, session_id: str, message: str, pending: dict[str, Any], traces: list[AgentTraceStep]
) -> AgentResult:
    code = str(pending["booking_code"])
    booking = session.scalar(select(Booking).where(Booking.booking_code == code))
    if booking is None:
        clear_pending_schedule_confirm(session, session_id)
        traces.append(
            AgentTraceStep(
                agent="scheduling_agent",
                reasoning_brief="Confirm cancel failed: booking row missing.",
                tools=["confirmation_gate", "db.select(bookings)"],
                outcome="cancel_confirm_missing",
            )
        )
        return AgentResult(
            response_text="I could not find that booking anymore, so nothing was cancelled.",
            traces=traces,
            payload={"status": "cancel_not_found"},
        )
    if booking.status == "cancelled":
        clear_pending_schedule_confirm(session, session_id)
        traces.append(
            AgentTraceStep(
                agent="scheduling_agent",
                reasoning_brief="Booking already cancelled at confirm step.",
                tools=["db.select(bookings)"],
                outcome="already_cancelled",
            )
        )
        return AgentResult(
            response_text=f"Booking {booking.booking_code} is already cancelled.",
            payload={"booking_code": booking.booking_code, "status": "already_cancelled"},
            traces=traces,
        )
    booking.status = "cancelled"
    sync = sync_booking_cancelled(booking)
    booking.integration_meta = sync
    session.commit()
    clear_pending_schedule_confirm(session, session_id)
    clear_last_fulfilled_booking(session, session_id)
    traces.append(
        AgentTraceStep(
            agent="scheduling_agent",
            reasoning_brief="User confirmed — cancelled booking and cleared pending confirm.",
            tools=["confirmation_gate", "calendar.cancel_hold", "sheets.upsert_row"],
            outcome="cancelled",
        )
    )
    pl_payload = {"booking_code": booking.booking_code, "status": "cancelled", "integration_sync": sync}
    draft = f"Your booking {booking.booking_code} is cancelled. Anything else I can help with?"
    polished = _llm_polish_scheduling_reply(user_message=message, draft=draft, payload=pl_payload, action="cancel")
    if polished != draft:
        traces.append(
            AgentTraceStep(
                agent="scheduling_agent",
                reasoning_brief="Polished cancellation confirmation with LLM.",
                tools=["llm.naturalize_scheduling_reply"],
                outcome="llm_voice",
            )
        )
    return AgentResult(response_text=polished, payload=pl_payload, traces=traces)


def _execute_confirmed_reschedule(
    session: Session,
    session_id: str,
    user_name: str,
    message: str,
    pending: dict[str, Any],
    traces: list[AgentTraceStep],
) -> AgentResult:
    code = str(pending["booking_code"])
    date_str = str(pending["new_date"])
    time_ist = str(pending["new_time"])
    old_date = str(pending["old_date"])
    old_time = str(pending["old_time"])
    booking = session.scalar(select(Booking).where(Booking.booking_code == code))
    if booking is None or booking.status == "cancelled":
        clear_pending_schedule_confirm(session, session_id)
        return AgentResult(
            response_text="That booking is no longer active, so I could not apply the reschedule.",
            traces=traces,
            payload={"status": "reschedule_confirm_stale"},
        )
    conflict = session.scalar(
        select(Booking)
        .where(Booking.date == date_str)
        .where(Booking.time_ist == time_ist)
        .where(Booking.status.in_(["tentative", "confirmed", "waitlisted"]))
        .where(Booking.booking_code != booking.booking_code)
        .limit(1)
    )
    if conflict:
        clear_pending_schedule_confirm(session, session_id)
        return AgentResult(
            response_text=(
                f"That slot is now held by {conflict.booking_code}. Say reschedule again with a different time."
            ),
            traces=traces,
            payload={"status": "conflict", **_booking_card_payload_row(conflict)},
        )
    sync_cancel = sync_booking_cancelled(booking)
    booking.calendar_event_id = None
    booking.date = date_str
    booking.time_ist = time_ist
    booking.status = "tentative"
    meta = dict(booking.integration_meta or {})
    meta["rescheduled_from"] = {"date": old_date, "time_ist": old_time, "calendar_cancel": sync_cancel}
    booking.integration_meta = meta
    session.flush()
    sync_new = sync_booking_created(booking)
    booking.calendar_event_id = (sync_new.get("calendar") or {}).get("reference")
    booking.sheet_row_ref = (sync_new.get("sheets") or {}).get("reference")
    meta = dict(booking.integration_meta or {})
    meta["reschedule_calendar"] = sync_new
    booking.integration_meta = meta
    session.commit()
    clear_pending_schedule_confirm(session, session_id)
    save_last_fulfilled_booking(
        session,
        session_id,
        user_name or "User",
        {
            "date": date_str,
            "time_ist": time_ist,
            "booking_code": booking.booking_code,
            "kind": "reschedule",
            "topic": booking.topic,
            "advisor": booking.advisor,
        },
    )
    traces.append(
        AgentTraceStep(
            agent="scheduling_agent",
            reasoning_brief="User confirmed — applied reschedule (calendar swap, same booking code).",
            tools=["confirmation_gate", "calendar.cancel_hold", "calendar.create_hold", "sheets.upsert_row"],
            outcome="rescheduled",
        )
    )
    out_payload: dict[str, Any] = {
        "booking_code": booking.booking_code,
        "topic": booking.topic,
        "date": date_str,
        "time_ist": time_ist,
        "advisor": booking.advisor,
        "status": "tentative",
        "previous_date": old_date,
        "previous_time_ist": old_time,
        "integration_sync": meta,
    }
    draft = (
        f"Done — booking {booking.booking_code} is moved from {old_date} {_time_plain_for_display(old_time)} IST to {date_str} at {_time_plain_for_display(time_ist)} IST. "
        f"Topic: {booking.topic}, {booking.advisor}. Anything else?"
    )
    polished = _llm_polish_scheduling_reply(
        user_message=message, draft=draft, payload=out_payload, action="reschedule"
    )
    if polished != draft:
        traces.append(
            AgentTraceStep(
                agent="scheduling_agent",
                reasoning_brief="Polished reschedule confirmation with LLM.",
                tools=["llm.naturalize_scheduling_reply"],
                outcome="llm_voice",
            )
        )
    return AgentResult(response_text=polished, payload=out_payload, traces=traces)


def handle_scheduling(session: Session, session_id: str, user_name: str, message: str) -> AgentResult:
    traces: list[AgentTraceStep] = []
    msg = message.lower()
    pending_now = get_pending_schedule_confirm(session, session_id)

    if pending_now and is_scheduling_rejection_message(message):
        clear_pending_schedule_confirm(session, session_id)
        traces.append(
            AgentTraceStep(
                agent="scheduling_agent",
                reasoning_brief="User declined pending schedule confirmation; cleared pending state.",
                tools=["confirmation_gate"],
                outcome="confirmation_declined",
            )
        )
        return AgentResult(
            response_text="Understood — I have not made any change to your calendar or booking.",
            payload={"status": "confirmation_declined"},
            traces=traces,
        )

    if pending_now and is_scheduling_confirmation_message(message):
        kind = str(pending_now.get("kind", ""))
        if kind == "book":
            return _execute_confirmed_book(session, session_id, user_name or "User", message, pending_now, traces)
        if kind == "cancel":
            return _execute_confirmed_cancel(session, session_id, message, pending_now, traces)
        if kind == "reschedule":
            return _execute_confirmed_reschedule(
                session, session_id, user_name or "User", message, pending_now, traces
            )
        clear_pending_schedule_confirm(session, session_id)
        traces.append(
            AgentTraceStep(
                agent="scheduling_agent",
                reasoning_brief="Stale pending confirm payload cleared.",
                tools=["confirmation_gate"],
                outcome="pending_stale",
            )
        )
        return AgentResult(
            response_text="That confirmation request expired. Please tell me again what you would like to book, cancel, or reschedule.",
            traces=traces,
            payload={"status": "pending_stale"},
        )

    if _wants_reschedule(msg):
        booking = _resolve_booking_for_reschedule(session, session_id, message)
        if booking is None:
            return AgentResult(
                response_text=(
                    "I can help you reschedule. Share your booking code (GRW- plus four characters, e.g. GRW-A7K2), "
                    "or book a session first if you don't have one yet."
                ),
                traces=[
                    AgentTraceStep(
                        agent="scheduling_agent",
                        reasoning_brief="Reschedule requested but no active GRW booking found for code or session.",
                        tools=["db.select(bookings)"],
                        outcome="reschedule_no_booking",
                    )
                ],
                payload={"status": "needs_booking_code"},
            )
        if booking.status == "cancelled":
            return AgentResult(
                response_text=(
                    "This booking was previously cancelled, so I can't reschedule it. "
                    "Would you like to book a fresh appointment instead?"
                ),
                traces=[
                    AgentTraceStep(
                        agent="scheduling_agent",
                        reasoning_brief="SCRIPT_FLOW: reschedule rejected — booking already cancelled.",
                        tools=["db.select(bookings)"],
                        outcome="reschedule_rejected_cancelled",
                    )
                ],
                payload={"booking_code": booking.booking_code, "status": "cancelled"},
            )
        if booking.booking_code.startswith("GRW-W-"):
            return AgentResult(
                response_text=(
                    f"{booking.booking_code} is a waitlist entry, not a confirmed appointment. "
                    "Say cancel with that code to remove it, or book a weekday slot (Mon–Fri, 9 AM–6 PM IST) when you have one."
                ),
                traces=[
                    AgentTraceStep(
                        agent="scheduling_agent",
                        reasoning_brief="Reschedule not applicable to waitlist-only codes.",
                        tools=["db.select(bookings)"],
                        outcome="reschedule_not_for_waitlist",
                    )
                ],
                payload={"booking_code": booking.booking_code, "status": "waitlisted"},
            )

        slot, slot_reason = _extract_time_ist_with_reason(message)
        if slot is None:
            traces.append(
                AgentTraceStep(
                    agent="scheduling_agent",
                    reasoning_brief="Reschedule intent: found booking; need valid new weekday IST slot.",
                    tools=["db.select(bookings)", "time_parser"],
                    outcome="reschedule_needs_new_slot",
                )
            )
            followup = "What new weekday time should I move it to (Mon–Fri, 9:00 AM–6:00 PM IST)?"
            if slot_reason == "missing_date":
                followup = (
                    "I got the time, but I still need the date. "
                    "Please share a weekday date with time (example: tomorrow 5 pm IST)."
                )
            elif slot_reason == "outside_hours":
                followup = "That time is outside advisor hours. Please share a weekday slot between 9:00 AM and 6:00 PM IST."
            elif slot_reason == "weekend":
                followup = "I can only schedule on weekdays. Please share a Mon–Fri date and time in IST."
            elif slot_reason == "ambiguous_time":
                followup = "Please share a specific time and date (example: tomorrow at 10 am IST)."
            elif slot_reason == "past_time":
                followup = "That looks like a past slot. Please share a future weekday date and time in IST."
            return AgentResult(
                response_text=(
                f"Found booking {booking.booking_code} ({booking.topic}, {booking.date} {_time_plain_for_display(booking.time_ist)} IST). "
                f"{followup}"
                ),
                payload={
                    "booking_code": booking.booking_code,
                    "topic": booking.topic,
                    "date": booking.date,
                    "time_ist": booking.time_ist,
                    "advisor": booking.advisor,
                    "status": booking.status,
                },
                traces=traces,
            )

        date_str, time_ist = slot
        if booking.date == date_str and booking.time_ist == time_ist:
            return AgentResult(
                response_text=(
                    f"You're already scheduled for {date_str} at {_time_plain_for_display(time_ist)} IST under {booking.booking_code}. "
                    "Tell me a different weekday time if you want to move it."
                ),
                traces=[
                    AgentTraceStep(
                        agent="scheduling_agent",
                        reasoning_brief="Reschedule requested to same slot — no calendar change.",
                        tools=["time_parser"],
                        outcome="reschedule_noop_same_slot",
                    )
                ],
                payload={"booking_code": booking.booking_code, "status": "unchanged"},
            )

        conflict = session.scalar(
            select(Booking)
            .where(Booking.date == date_str)
            .where(Booking.time_ist == time_ist)
            .where(Booking.status.in_(["tentative", "confirmed", "waitlisted"]))
            .where(Booking.booking_code != booking.booking_code)
            .limit(1)
        )
        if conflict:
            return AgentResult(
                response_text=(
                    f"That slot is already held by booking {conflict.booking_code}. "
                    "Pick another weekday time, or reschedule that booking instead."
                ),
                traces=[
                    AgentTraceStep(
                        agent="scheduling_agent",
                        reasoning_brief="Reschedule blocked by another booking in the same session at target slot.",
                        tools=["db.select(bookings)"],
                        outcome="reschedule_slot_conflict",
                    )
                ],
                payload={"status": "conflict", **_booking_card_payload_row(conflict)},
            )

        old_date, old_time = booking.date, booking.time_ist
        save_pending_schedule_confirm(
            session,
            session_id,
            user_name or "User",
            {
                "kind": "reschedule",
                "booking_code": booking.booking_code,
                "new_date": date_str,
                "new_time": time_ist,
                "old_date": old_date,
                "old_time": old_time,
            },
        )
        traces.append(
            AgentTraceStep(
                agent="scheduling_agent",
                reasoning_brief="SCRIPT/PRD: reschedule preview saved — no calendar change until user confirms yes.",
                tools=["confirmation_gate", "memory.pending_schedule_confirm"],
                outcome="awaiting_reschedule_confirm",
            )
        )
        out_payload: dict[str, Any] = {
            "booking_code": booking.booking_code,
            "topic": booking.topic,
            "date": date_str,
            "time_ist": time_ist,
            "advisor": booking.advisor,
            "status": "awaiting_confirmation",
            "previous_date": old_date,
            "previous_time_ist": old_time,
        }
        draft = (
            f"Please confirm reschedule: {booking.booking_code} from {old_date} {_time_plain_for_display(old_time)} IST "
            f"to {date_str} {_time_plain_for_display(time_ist)} IST ({booking.topic}). Reply yes or no."
        )
        polished = _llm_polish_scheduling_reply(
            user_message=message, draft=draft, payload=out_payload, action="reschedule"
        )
        if polished != draft:
            traces.append(
                AgentTraceStep(
                    agent="scheduling_agent",
                    reasoning_brief="Polished reschedule confirmation prompt with LLM.",
                    tools=["llm.naturalize_scheduling_reply"],
                    outcome="llm_voice",
                )
            )
        return AgentResult(response_text=polished, payload=out_payload, traces=traces)

    # --- Cancel ---
    if "cancel" in msg:
        code = _extract_booking_code(message)
        if code:
            booking = session.scalar(select(Booking).where(Booking.booking_code == code))
        else:
            booking = session.scalar(
                select(Booking).where(Booking.session_id == session_id).order_by(Booking.created_at.desc()).limit(1)
            )
        if booking is None:
            return AgentResult(
                response_text="I could not find a booking to cancel. Share your booking code (GRW-… or GRW-W-…) and I will check.",
                traces=[
                    AgentTraceStep(
                        agent="scheduling_agent",
                        reasoning_brief="Cancel requested but no booking found for session/code.",
                        tools=["db.select(bookings)"],
                        outcome="no_booking",
                    )
                ],
            )
        if booking.status == "cancelled":
            return AgentResult(
                response_text=f"Booking {booking.booking_code} is already cancelled.",
                payload={"booking_code": booking.booking_code, "status": "already_cancelled"},
                traces=[
                    AgentTraceStep(
                        agent="scheduling_agent",
                        reasoning_brief="Cancellation requested for an already-cancelled booking.",
                        tools=["db.select(bookings)"],
                        outcome="already_cancelled",
                    )
                ],
            )
        save_pending_schedule_confirm(
            session,
            session_id,
            user_name or "User",
            {"kind": "cancel", "booking_code": booking.booking_code},
        )
        traces.append(
            AgentTraceStep(
                agent="scheduling_agent",
                reasoning_brief="SCRIPT/PRD: cancel preview — awaiting explicit yes before status change.",
                tools=["confirmation_gate", "memory.pending_schedule_confirm"],
                outcome="awaiting_cancel_confirm",
            )
        )
        pl_payload = {
            "booking_code": booking.booking_code,
            "status": "awaiting_confirmation",
            "topic": booking.topic,
            "date": booking.date,
            "time_ist": booking.time_ist,
        }
        draft = (
            f"Please confirm cancellation for {booking.booking_code} ({booking.topic}, {booking.date} {_time_plain_for_display(booking.time_ist)} IST). "
            "Reply yes or no."
        )
        polished = _llm_polish_scheduling_reply(
            user_message=message, draft=draft, payload=pl_payload, action="cancel"
        )
        if polished != draft:
            traces.append(
                AgentTraceStep(
                    agent="scheduling_agent",
                    reasoning_brief="Polished cancel confirmation prompt with LLM.",
                    tools=["llm.naturalize_scheduling_reply"],
                    outcome="llm_voice",
                )
            )
        return AgentResult(response_text=polished, payload=pl_payload, traces=traces)

    # --- Dedicated waitlist join (PRD / SCRIPT_FLOW edge: no matching slots) ---
    slot_for_waitlist_gate = _extract_time_ist(message)
    if _dedicated_waitlist_request(message) and not (
        slot_for_waitlist_gate is not None and "book" in msg and "waitlist" not in msg
    ):
        topic = _extract_topic(message)
        return _waitlist_booking_response(
            session=session,
            session_id=session_id,
            user_name=user_name or "User",
            message=message,
            topic=topic,
            traces=traces,
        )

    # --- What to prepare (SCRIPT_FLOW Flow 6; PRD scheduling intent) ---
    if wants_what_to_prepare_message(msg):
        booking = _resolve_booking_for_prepare(session, session_id, message)
        topic_from_msg = _extract_topic(message)
        topic_choice = _topic_from_numeric_or_name(message)
        topic: str | None = None
        if booking and booking.topic and booking.topic in _PREPARE_CHECKLISTS:
            topic = booking.topic
        elif topic_from_msg in _PREPARE_CHECKLISTS:
            topic = topic_from_msg
        elif topic_choice in _PREPARE_CHECKLISTS:
            topic = topic_choice

        if topic is None:
            traces.append(
                AgentTraceStep(
                    agent="scheduling_agent",
                    reasoning_brief="Prepare intent: no specific topic yet — asked user to pick from standard list (SCRIPT_FLOW 6).",
                    tools=["prepare.topic_prompt"],
                    outcome="prepare_needs_topic",
                )
            )
            return AgentResult(
                response_text=_PREPARE_TOPIC_PROMPT,
                payload={"status": "prepare_needs_topic"},
                traces=traces,
            )

        body = _PREPARE_CHECKLISTS[topic]
        traces.append(
            AgentTraceStep(
                agent="scheduling_agent",
                reasoning_brief=f"Delivered educational checklist for '{topic}' (not financial advice).",
                tools=["prepare.checklist_template", "db.select(bookings)?"],
                outcome="prepare_checklist",
            )
        )
        return AgentResult(
            response_text=body,
            payload={"prepare_topic": topic, "status": "prepare_ready"},
            traces=traces,
        )

    # --- Availability ---
    if "availability" in msg or "available" in msg:
        now = datetime.now()
        day1 = now + timedelta(days=1)
        day2 = now + timedelta(days=2)
        slots = [
            f"{day1.strftime('%Y-%m-%d')} at 10:00 IST",
            f"{day2.strftime('%Y-%m-%d')} at 15:00 IST",
        ]
        traces = [
            AgentTraceStep(
                agent="scheduling_agent",
                reasoning_brief="Availability intent detected; offered two near-term IST slots.",
                tools=["slot_generator(local_rules)"],
                outcome="slots_returned",
            )
        ]
        draft = "Here are available slots:\n- " + "\n- ".join(slots)
        polished = _llm_polish_scheduling_reply(
            user_message=message, draft=draft, payload={"slots": slots}, action="availability"
        )
        if polished != draft:
            traces.append(
                AgentTraceStep(
                    agent="scheduling_agent",
                    reasoning_brief="Polished availability reply with LLM while preserving slot list.",
                    tools=["llm.naturalize_scheduling_reply"],
                    outcome="llm_voice",
                )
            )
        return AgentResult(response_text=polished, payload={"slots": slots}, traces=traces)

    # --- Book new (or implicit path) ---
    topic = _extract_topic(message)
    slot, slot_reason = _extract_time_ist_with_reason(message)
    if slot is None:
        waitlist_hint = ""
        if not _dedicated_waitlist_request(message):
            waitlist_hint = (
                "\n\nIf no weekday slot works, say **join waitlist for KYC** (or your topic) and I will add you "
                "with a waitlist code (GRW-W-XXXX) and advisor hold per our process."
            )
        guidance = (
            "What weekday time works for you in IST (Mon–Fri, 9:00 AM–6:00 PM)? "
            "For example: tomorrow at 10 am IST."
        )
        if slot_reason == "missing_date":
            guidance = (
                "I got your time, but I need the date too. "
                "Please share weekday date + time in IST (example: tomorrow at 5 pm)."
            )
        elif slot_reason == "outside_hours":
            guidance = "That time is outside advisor hours. Please share a weekday slot between 9:00 AM and 6:00 PM IST."
        elif slot_reason == "weekend":
            guidance = "I can only book weekdays. Please share a Mon–Fri date and time in IST."
        elif slot_reason == "past_time":
            guidance = "That looks like a past slot. Please share a future weekday date and time in IST."
        elif slot_reason == "ambiguous_time":
            guidance = "Please share a specific weekday date and time in IST (example: tomorrow at 10 am)."
        elif slot_reason == "too_far_future":
            guidance = (
                f"That date is outside our booking window. Please pick a weekday within the next "
                f"{get_booking_max_days_ahead()} days."
            )
        save_pending_scheduling_clarify(
            session,
            session_id,
            user_name or "User",
            {"rolling_text": message.strip()},
        )
        return AgentResult(
            response_text=(guidance + waitlist_hint),
            traces=[
                AgentTraceStep(
                    agent="scheduling_agent",
                    reasoning_brief=f"Rejected scheduling input with reason={slot_reason}; asked targeted clarification.",
                    tools=["time_parser", "working_hours_guard", "weekday_guard"],
                    outcome="invalid_time_request",
                )
            ],
            payload={"status": "needs_time_clarification"},
        )
    clear_pending_scheduling_clarify(session, session_id)
    date_str, time_ist = slot

    last_done = get_last_fulfilled_booking(session, session_id)
    if (
        last_done
        and str(last_done.get("date") or "") == date_str
        and str(last_done.get("time_ist") or "") == time_ist
        and not message_signals_new_scheduling_request(message)
    ):
        code_hint = str(last_done.get("booking_code") or "your booking")
        return AgentResult(
            response_text=(
                f"That appointment time is already confirmed ({code_hint}). "
                "Say **book** if you want to schedule another call, or ask me anything else."
            ),
            traces=[
                AgentTraceStep(
                    agent="scheduling_agent",
                    reasoning_brief="Suppressed duplicate slot parse after fulfilled booking — no explicit new scheduling intent.",
                    tools=["memory.last_fulfilled_booking", "intent.guard"],
                    outcome="post_booking_slot_suppressed",
                )
            ],
            payload={
                "status": "post_booking_idle",
                "booking_code": last_done.get("booking_code"),
                "date": last_done.get("date"),
                "time_ist": last_done.get("time_ist"),
                "topic": last_done.get("topic"),
                "advisor": last_done.get("advisor"),
            },
        )

    conflict = session.scalar(
        select(Booking)
        .where(Booking.date == date_str)
        .where(Booking.time_ist == time_ist)
        .where(Booking.status.in_(["tentative", "confirmed", "waitlisted"]))
        .limit(1)
    )
    if conflict:
        return AgentResult(
            response_text=(
                f"You already have booking {conflict.booking_code} at {date_str} {time_ist}. "
                "Would you like to reschedule instead?"
            ),
            payload={"status": "conflict", **_booking_card_payload_row(conflict)},
            traces=[
                AgentTraceStep(
                    agent="scheduling_agent",
                    reasoning_brief="Duplicate slot in same session — suggest reschedule per SCRIPT_FLOW.",
                    tools=["db.select(bookings)"],
                    outcome="slot_conflict",
                )
            ],
        )
    advisor_idx = (session.scalar(select(func.count()).select_from(Booking)) or 0) % 5 + 1
    save_pending_schedule_confirm(
        session,
        session_id,
        user_name or "User",
        {
            "kind": "book",
            "topic": topic,
            "date": date_str,
            "time_ist": time_ist,
            "advisor_idx": advisor_idx,
            "concern_summary": message[:400],
        },
    )
    traces.append(
        AgentTraceStep(
            agent="scheduling_agent",
            reasoning_brief="SCRIPT/PRD: booking proposal stored — no DB row or calendar until user confirms yes.",
            tools=[
                "confirmation_gate",
                "memory.pending_schedule_confirm",
                "topic_parser",
                "time_parser",
            ],
            outcome="awaiting_book_confirm",
        )
    )
    out_payload = {
        "topic": topic,
        "date": date_str,
        "time_ist": time_ist,
        "advisor": f"Advisor {advisor_idx}",
        "status": "awaiting_confirmation",
    }
    draft = (
        f"Please confirm booking: {topic} on {date_str} at {_time_plain_for_display(time_ist)} IST with Advisor {advisor_idx}. "
        "Reply yes or no."
    )
    # Keep booking confirmation deterministic for user trust and predictable yes/no flow.
    return AgentResult(response_text=draft, payload=out_payload, traces=traces)
