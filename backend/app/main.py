"""FastAPI application entry."""

from __future__ import annotations

import csv
import logging
import os
import re
from datetime import datetime, timedelta
from io import StringIO
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, desc, func, or_, select
from sqlalchemy.orm import Session

from app.agents.orchestrator import handle_chat_turn
from app.agents.email_agent import draft_advisor_email
from app.agents.rag_agent import clear_faq_answer_cache
from app.config import get_google_doc_id, get_google_integrations_mode
from app.db.models import (
    AgentActivityLog,
    Booking,
    InteractionLog,
    PulseRun,
    PulseTheme,
    Review,
    Subscriber,
)
from app.db.session import get_session_factory, init_db
from app.integrations.google_doc_append import append_structured_pulse_to_google_doc
from app.integrations.service import send_booking_email_smtp, send_pulse_email_smtp, sync_booking_sheet
from app.ml.theme_pipeline import generate_pulse, get_latest_pulse, list_pulse_history
from app.pii_guard import contains_pii
from app.rag.embed import get_embedder
from app.rag.ingest_pipeline import rag_stats, run_full_ingest
from app.rag.search import search_chunks
from app.reviews.pipeline import refresh_reviews

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]

IST = ZoneInfo("Asia/Kolkata") if ZoneInfo else None


def _cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "http://localhost:3000")
    return [o.strip() for o in raw.split(",") if o.strip()]


class ComponentHealth(BaseModel):
    status: Literal["ok", "degraded", "not_configured", "error"] = "not_configured"
    detail: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"] = "ok"
    service: str = "investor-ops-api"
    version: str = Field(default="0.1.0")
    timestamp_ist: str
    components: dict[str, ComponentHealth]


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default-session"
    user_name: str = "User"


class ChatResponse(BaseModel):
    response: str
    traces: list[dict[str, Any]]
    payload: dict[str, Any] = Field(default_factory=dict)


class SubscriberIn(BaseModel):
    email: str


class SendPulseIn(BaseModel):
    emails: list[str] = Field(default_factory=list)


class BookingEmailSendIn(BaseModel):
    to_email: str = "advisor@example.com"


class SecureDetailsIn(BaseModel):
    phone: str
    email: str
    consent: bool


def _analytics_since_utc(range_key: str) -> datetime:
    now = datetime.utcnow()
    key = (range_key or "week").strip().lower()
    if key == "day":
        return now - timedelta(days=1)
    if key == "month":
        return now - timedelta(days=30)
    return now - timedelta(days=7)


def _admin_analytics_payload(session: Session, range_key: str) -> dict[str, Any]:
    since = _analytics_since_utc(range_key)
    # Themes: show only the latest pulse in the selected window so historical labels
    # from older runs do not accumulate into misleading aggregates.
    latest_pulse_id = session.scalar(
        select(PulseRun.id)
        .where(PulseRun.generated_at >= since)
        .order_by(desc(PulseRun.generated_at), desc(PulseRun.id))
        .limit(1)
    )
    if latest_pulse_id is None:
        review_themes: list[dict[str, Any]] = []
    else:
        review_themes = [
            {"theme": row[0], "volume": int(row[1] or 0)}
            for row in session.execute(
                select(PulseTheme.label, PulseTheme.volume)
                .where(PulseTheme.pulse_run_id == latest_pulse_id)
                .order_by(PulseTheme.rank)
            ).all()
        ]
    appointments = [
        {"date": row[0], "count": int(row[1] or 0)}
        for row in session.execute(
            select(Booking.date, func.count())
            .where(Booking.created_at >= since)
            .group_by(Booking.date)
            .order_by(Booking.date)
        ).all()
    ]
    booking_topics = [
        {"topic": row[0], "count": int(row[1] or 0)}
        for row in session.execute(
            select(Booking.topic, func.count())
            .where(Booking.created_at >= since)
            .group_by(Booking.topic)
            .order_by(desc(func.count()))
        ).all()
    ]
    faq_topics = [
        {"topic": row[0], "count": int(row[1] or 0)}
        for row in session.execute(
            select(InteractionLog.topic, func.count())
            .where(InteractionLog.intent == "faq", InteractionLog.created_at >= since)
            .group_by(InteractionLog.topic)
            .order_by(desc(func.count()))
        ).all()
    ]
    return {
        "range": range_key,
        "review_themes": review_themes,
        "appointments_booked": appointments,
        "booking_topics": booking_topics,
        "faq_topics": faq_topics,
    }


def _format_pulse_for_doc(pulse: dict[str, Any]) -> str:
    lines = [
        f"Pulse #{pulse.get('pulse_id')} — generated {pulse.get('generated_at')}",
        f"Reviews sampled: {pulse.get('review_count')} | date range: {pulse.get('date_from')} → {pulse.get('date_to')}",
        "",
        str(pulse.get("analysis", "")).strip(),
        "",
        "Top themes:",
    ]
    for t in pulse.get("top_themes") or []:
        lines.append(f"- {t.get('label')} (n={t.get('volume')}): {str(t.get('quote', ''))[:280]}")
    lines.append("")
    lines.append("Actions:")
    for i, a in enumerate(pulse.get("actions") or [], start=1):
        lines.append(f"{i}. {a}")
    lines.append("")
    return "\n".join(lines)


def _topic_from_message(message: str) -> str:
    words = re.findall(r"[A-Za-z][A-Za-z0-9\-]*", message)
    if not words:
        return "general"
    return " ".join(words[:4]).lower()


def _faq_topic_bucket(message: str) -> str:
    t = (message or "").lower()
    if "exit load" in t:
        return "Exit Load"
    if "expense ratio" in t or re.search(r"\bter\b", t):
        return "Expense Ratio"
    if re.search(r"\bnav\b", t):
        return "NAV"
    if re.search(r"\baum\b", t):
        return "AUM"
    if "lock-in" in t or "lockin" in t:
        return "Lock-in Period"
    if "tax" in t or "elss" in t or "80c" in t:
        return "Tax & ELSS"
    if "compare" in t:
        return "Fund Comparison"
    if "book" in t or "appointment" in t or "schedule" in t:
        return "Booking"
    return "General"


# Exact labels produced by _faq_topic_bucket (and stored for new FAQ rows).
_CANONICAL_FAQ_TOPIC_LABELS: frozenset[str] = frozenset(
    {
        "Exit Load",
        "Expense Ratio",
        "NAV",
        "AUM",
        "Lock-in Period",
        "Tax & ELSS",
        "Fund Comparison",
        "Booking",
        "General",
    }
)


def _remap_legacy_faq_topic_column(stored: str) -> str:
    """Map pre-bucketing interaction_logs.topic snippets to canonical FAQ labels.

    Legacy values were often `_topic_from_message` (first ~4 words). Original user text is not
    stored, so we use substring heuristics aligned with `_faq_topic_bucket`.
    """
    raw = (stored or "").strip()
    if not raw:
        return "General"
    for c in _CANONICAL_FAQ_TOPIC_LABELS:
        if raw.lower() == c.lower():
            return c
    bucket = _faq_topic_bucket(raw)
    if bucket != "General":
        return bucket
    t = raw.lower()
    if re.search(r"\bexit\b", t):
        return "Exit Load"
    if "expense" in t or "expence" in t or re.search(r"\bter\b", t):
        return "Expense Ratio"
    if re.search(r"\bnav\b", t):
        return "NAV"
    if re.search(r"\baum\b", t):
        return "AUM"
    if "lock-in" in t or "lockin" in t:
        return "Lock-in Period"
    if "tax" in t or "elss" in t or "80c" in t:
        return "Tax & ELSS"
    if "compare" in t or "versus" in t or re.search(r"\bvs\b", t):
        return "Fund Comparison"
    if "book" in t or "appointment" in t or "schedule" in t:
        return "Booking"
    return "General"


def normalize_legacy_faq_interaction_topics(session: Session) -> int:
    """Update FAQ interaction_logs rows whose topic is not a canonical bucket label. Idempotent."""
    rows = list(session.scalars(select(InteractionLog).where(InteractionLog.intent == "faq")).all())
    updated = 0
    for row in rows:
        new_topic = _remap_legacy_faq_topic_column(row.topic)
        if new_topic != row.topic:
            row.topic = new_topic
            updated += 1
    if updated:
        session.commit()
    return updated


def _looks_like_bot_generated_text(message: str) -> bool:
    t = re.sub(r"\s+", " ", (message or "").lower()).strip()
    if not t:
        return False
    bot_markers = (
        "i provide factual mutual fund",
        "i do not provide investment advice",
        "help schedule advisor appointments",
        "mandatory advisor appointments",
        "welcome back",
        "quick reminder: your booking",
    )
    return any(m in t for m in bot_markers)


# Topics are `_topic_from_message` (first ~4 words). Prefixes align with `_looks_like_bot_generated_text`.
_BOT_ECHO_FAQ_TOPIC_PREFIXES: tuple[str, ...] = (
    "i provide factual mutual",
    "i do not provide",
    "help schedule advisor appointments",
    "mandatory advisor appointments",
    "welcome back",
    "quick reminder your booking",
)


def purge_bot_echo_faq_interaction_logs(session: Session) -> int:
    """Remove historical FAQ rows logged before bot-echo guard (assistant copy pasted as user message)."""
    stmt = delete(InteractionLog).where(
        InteractionLog.intent == "faq",
        or_(*(InteractionLog.topic.startswith(p) for p in _BOT_ECHO_FAQ_TOPIC_PREFIXES)),
    )
    result = session.execute(stmt)
    return int(result.rowcount or 0)


def _is_valid_india_phone(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    return len(digits) == 10 and digits[0] in {"6", "7", "8", "9"}


def _is_valid_email(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$", value.strip()))


def _smtp_configured() -> bool:
    return bool((os.getenv("GMAIL_SMTP_USER") or "").strip() and (os.getenv("GMAIL_APP_PASSWORD") or "").strip())


def _log_chat_artifacts(session: Session, req: ChatRequest, result: Any) -> None:
    intents = result.payload.get("intents", []) if isinstance(result.payload, dict) else []
    if not intents:
        intents = ["general"]
    base_topic = str(result.payload.get("topic") or _topic_from_message(req.message))
    is_bot_echo = _looks_like_bot_generated_text(req.message)
    for intent in intents:
        # Skip FAQ-topic analytics for bot-echoed assistant text captured as user input.
        if str(intent) == "faq" and is_bot_echo:
            continue
        topic = _faq_topic_bucket(req.message) if str(intent) == "faq" else base_topic
        session.add(
            InteractionLog(
                session_id=req.session_id,
                user_name=req.user_name,
                intent=str(intent),
                topic=topic,
            )
        )
    for t in result.traces:
        # Guard DB column limits: outcome is String(128) in AgentActivityLog.
        outcome = str(t.outcome or "")[:120]
        session.add(
            AgentActivityLog(
                session_id=req.session_id,
                user_name=req.user_name,
                agent=t.agent,
                reasoning_brief=t.reasoning_brief,
                tools_json=t.tools or [],
                outcome=outcome,
                query_summary=req.message[:240],
            )
        )
    try:
        session.commit()
    except Exception:
        # Logging should never break chat responses.
        session.rollback()


def _now_ist_iso() -> str:
    if IST is not None:
        return datetime.now(IST).isoformat(timespec="seconds")
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def build_health_payload(app_version: str) -> dict[str, Any]:
    groq = bool(os.getenv("GROQ_API_KEY"))
    gemini = bool(os.getenv("GEMINI_API_KEY"))
    database_url = bool(os.getenv("DATABASE_URL"))

    llm_status: Literal["ok", "degraded", "not_configured"]
    if groq:
        llm_status = "ok"
    elif gemini:
        llm_status = "degraded"
    else:
        llm_status = "not_configured"

    components = {
        "api": ComponentHealth(status="ok", detail="FastAPI up"),
        "database": ComponentHealth(status="ok" if database_url else "not_configured"),
        "llm": ComponentHealth(status=llm_status),
        "vector_store": ComponentHealth(status="ok", detail="RAG chunks table enabled"),
        "google_calendar": ComponentHealth(status="ok" if os.getenv("GOOGLE_CALENDAR_ID") else "not_configured"),
        "google_sheets": ComponentHealth(status="ok" if os.getenv("GOOGLE_SHEET_ID") else "not_configured"),
        "gmail_smtp": ComponentHealth(
            status="ok" if (os.getenv("GMAIL_SMTP_USER") and os.getenv("GMAIL_APP_PASSWORD")) else "not_configured"
        ),
    }

    overall: Literal["ok", "degraded"] = "ok" if llm_status != "not_configured" else "degraded"
    payload = HealthResponse(status=overall, version=app_version, timestamp_ist=_now_ist_iso(), components=components)
    return payload.model_dump()


app = FastAPI(
    title="Investor Ops & Intelligence Suite API",
    version="0.2.0",
    description="Backend scaffold + phase-2 data pipeline primitives.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    log = logging.getLogger(__name__)
    try:
        with _db() as session:
            removed = purge_bot_echo_faq_interaction_logs(session)
            session.commit()
        if removed > 0:
            log.info("Purged %s bot-echo FAQ interaction_logs row(s)", removed)
    except Exception:
        log.exception("interaction_logs bot-echo purge failed (non-fatal)")


def _db() -> Session:
    SessionLocal = get_session_factory()
    return SessionLocal()


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse.model_validate(build_health_payload(app.version))


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Investor Ops API — use GET /health"}


@app.post("/api/data/ingest")
def ingest_data() -> dict[str, int]:
    with _db() as session:
        return run_full_ingest(session)


@app.get("/api/data/stats")
def data_stats() -> dict[str, int]:
    with _db() as session:
        return rag_stats(session)


@app.get("/api/data/search")
def data_search(
    q: str = Query(..., min_length=2),
    layer: str | None = Query(default=None),
    top_k: int = Query(default=5, ge=1, le=20),
) -> dict[str, Any]:
    with _db() as session:
        hits = search_chunks(session, get_embedder(), q, top_k=top_k, layer=layer)
    return {"query": q, "count": len(hits), "results": hits}


@app.post("/api/reviews/refresh")
def reviews_refresh(limit: int = Query(default=200, ge=10, le=1000)) -> dict[str, Any]:
    with _db() as session:
        return refresh_reviews(session, limit=limit)


@app.post("/api/pulse/generate")
def pulse_generate(sample_size: int = Query(default=500, ge=50, le=5000)) -> dict[str, Any]:
    try:
        with _db() as session:
            return generate_pulse(session, sample_size=sample_size)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/pulse/latest")
def pulse_latest() -> dict[str, Any]:
    with _db() as session:
        pulse = get_latest_pulse(session)
    if pulse is None:
        return {"message": "No pulse generated yet."}
    return pulse


@app.get("/api/pulse/history")
def pulse_history(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
    with _db() as session:
        rows = list_pulse_history(session, limit=limit)
    return {"count": len(rows), "items": rows}


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    req.message = (req.message or "").strip()[:2000]
    req.user_name = (req.user_name or "User").strip()[:128]
    req.session_id = (req.session_id or "default-session").strip()[:128]
    if contains_pii(req.message):
        return ChatResponse(
            response=(
                "For your security, please do not share personal details like Aadhaar, PAN, phone, or email here. "
                "For account-specific help, please use the secure booking page."
            ),
            traces=[
                {
                    "agent": "orchestrator",
                    "reasoning_brief": "Blocked message at API boundary because sensitive personal information was detected.",
                    "tools": ["chat.pii_precheck", "secure_page_redirect"],
                    "replanned": False,
                    "outcome": "pii_blocked_pre_agent",
                }
            ],
            payload={"intents": ["safety"], "safe_redirect": "/secure/[bookingCode]"},
        )
    try:
        with _db() as session:
            result = handle_chat_turn(session, req.session_id, req.user_name, req.message)
            _log_chat_artifacts(session, req, result)
        return ChatResponse(
            response=result.response_text,
            traces=[t.model_dump() for t in result.traces],
            payload=result.payload,
        )
    except Exception:
        # Keep the chat API resilient: never leak raw 500s to the client for recoverable runtime issues.
        return ChatResponse(
            response="I hit a temporary issue processing that request. Please try once more.",
            traces=[
                {
                    "agent": "orchestrator",
                    "reasoning_brief": "Caught unexpected runtime error and returned safe fallback response.",
                    "tools": ["chat.fallback_guard"],
                    "replanned": False,
                    "outcome": "runtime_fallback",
                }
            ],
            payload={"status": "runtime_fallback"},
        )


@app.get("/api/admin/analytics")
def admin_analytics(range: str = Query(default="week")) -> dict[str, Any]:
    with _db() as session:
        return _admin_analytics_payload(session, range)


@app.get("/api/admin/export/analytics.csv")
def admin_export_analytics_csv(range: str = Query(default="week")) -> Response:
    with _db() as session:
        data = _admin_analytics_payload(session, range)
    buf = StringIO()
    w = csv.writer(buf)
    w.writerow(["section", "key", "value"])
    w.writerow(["meta", "range", data["range"]])
    w.writerow(["meta", "generated_at_utc", datetime.utcnow().isoformat(timespec="seconds")])
    for row in data["review_themes"]:
        w.writerow(["review_theme", row["theme"], row["volume"]])
    for row in data["appointments_booked"]:
        w.writerow(["appointment_by_booking_date", row.get("date") or "", row["count"]])
    for row in data["booking_topics"]:
        w.writerow(["booking_topic", row.get("topic") or "", row["count"]])
    for row in data["faq_topics"]:
        w.writerow(["faq_topic", row.get("topic") or "", row["count"]])
    body = buf.getvalue()
    filename = f"analytics-{range}.csv"
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/admin/pulse/append-doc")
def admin_append_pulse_to_google_doc() -> dict[str, Any]:
    if get_google_integrations_mode() != "live":
        return {
            "ok": False,
            "message": "Set GOOGLE_INTEGRATIONS_MODE=live and grant the service account edit access to the doc.",
        }
    doc_id = (get_google_doc_id() or "").strip()
    if not doc_id:
        return {"ok": False, "message": "Set GOOGLE_DOC_ID to the master document ID."}
    with _db() as session:
        latest = get_latest_pulse(session)
    if latest is None:
        return {"ok": False, "message": "no pulse generated"}
    return append_structured_pulse_to_google_doc(doc_id, latest)


@app.post("/api/admin/cache/faq/clear")
def admin_clear_faq_cache() -> dict[str, Any]:
    cleared = clear_faq_answer_cache()
    return {
        "ok": True,
        "cleared_entries": cleared,
        "scope": "current_process",
        "note": "FAQ cache is in-memory per API process. Restarting the service also clears it.",
    }


@app.post("/api/admin/maintenance/normalize-faq-topics")
def admin_normalize_faq_topics() -> dict[str, Any]:
    """One-shot: rewrite legacy FAQ rows (pre-bucketing topic snippets) to canonical labels."""
    with _db() as session:
        n = normalize_legacy_faq_interaction_topics(session)
    return {"ok": True, "rows_updated": n}


@app.get("/api/admin/bookings")
def admin_bookings() -> dict[str, Any]:
    with _db() as session:
        rows = list(session.scalars(select(Booking).order_by(desc(Booking.created_at)).limit(500)))
    return {
        "count": len(rows),
        "items": [
            {
                "booking_code": b.booking_code,
                "customer_name": b.customer_name,
                "topic": b.topic,
                "date": b.date,
                "time_ist": b.time_ist,
                "advisor": b.advisor,
                "status": b.status,
                "email_status": b.email_status,
                "concern_summary": b.concern_summary,
            }
            for b in rows
        ],
    }


@app.post("/api/admin/bookings/{booking_code}/email/preview")
def admin_booking_email_preview(booking_code: str) -> dict[str, Any]:
    with _db() as session:
        result = draft_advisor_email(session, booking_code)
    return {"ok": True, "draft": result.payload.get("draft_text", ""), "payload": result.payload}


@app.post("/api/admin/bookings/{booking_code}/email/send")
def admin_booking_email_send(booking_code: str, req: BookingEmailSendIn) -> dict[str, Any]:
    with _db() as session:
        b = session.scalar(select(Booking).where(Booking.booking_code == booking_code))
        if not b:
            return {"ok": False, "message": "booking not found"}
        draft_res = draft_advisor_email(session, booking_code)
        draft_text = str((draft_res.payload or {}).get("draft_text") or "").strip()
        if not draft_text:
            draft_text = (
                f"Booking {b.booking_code}\n"
                f"Customer: {b.customer_name}\n"
                f"Topic: {b.topic}\n"
                f"Slot: {b.date} {b.time_ist} IST\n"
                f"Advisor: {b.advisor}\n"
                f"Concern: {b.concern_summary}\n"
            )
        if _smtp_configured():
            smtp = send_booking_email_smtp(
                to_email=req.to_email,
                subject=f"Advisor briefing: {b.booking_code} ({b.topic})",
                body=draft_text,
            )
            if not smtp.ok:
                return {"ok": False, "message": smtp.detail}
            send_detail = smtp.detail
            send_mode = "smtp_live"
        else:
            send_detail = "smtp not configured; simulated send"
            send_mode = "mock_send"
        b.email_status = "sent"
        meta = dict(b.integration_meta or {})
        meta["email_sent_to"] = req.to_email
        meta["email_send_detail"] = send_detail
        meta["email_send_mode"] = send_mode
        sheet_sync = sync_booking_sheet(b)
        meta["email_sheet_sync"] = sheet_sync
        b.integration_meta = meta
        session.commit()
    return {
        "ok": True,
        "booking_code": booking_code,
        "to_email": req.to_email,
        "status": "sent",
        "detail": send_detail,
        "mode": send_mode,
    }


@app.get("/api/admin/agent-activity")
def admin_agent_activity(limit: int = Query(default=100, ge=1, le=1000)) -> dict[str, Any]:
    with _db() as session:
        rows = list(
            session.scalars(select(AgentActivityLog).order_by(desc(AgentActivityLog.created_at)).limit(limit))
        )
    return {
        "count": len(rows),
        "items": [
            {
                "timestamp": r.created_at.isoformat(timespec="seconds"),
                "session_id": r.session_id,
                "user_name": r.user_name,
                "agent": r.agent,
                "reasoning_brief": r.reasoning_brief,
                "tools": r.tools_json,
                "outcome": r.outcome,
                "query_summary": r.query_summary,
            }
            for r in rows
        ],
    }


@app.post("/api/subscribers")
def create_subscriber(req: SubscriberIn) -> dict[str, Any]:
    email = req.email.strip().lower()
    if "@" not in email:
        return {"ok": False, "message": "invalid email"}
    with _db() as session:
        existing = session.scalar(select(Subscriber).where(Subscriber.email == email))
        if existing:
            if existing.active != 1:
                existing.active = 1
                session.commit()
            return {"ok": True, "message": "already subscribed", "email": email}
        session.add(Subscriber(email=email, active=1))
        session.commit()
    return {"ok": True, "message": "subscribed", "email": email}


@app.get("/api/admin/subscribers")
def admin_subscribers() -> dict[str, Any]:
    with _db() as session:
        rows = list(session.scalars(select(Subscriber).where(Subscriber.active == 1).order_by(Subscriber.created_at)))
    return {"count": len(rows), "items": [{"email": r.email, "id": r.id} for r in rows]}


@app.post("/api/admin/pulse/send")
def admin_send_pulse(req: SendPulseIn) -> dict[str, Any]:
    with _db() as session:
        latest = get_latest_pulse(session)
    if latest is None:
        return {"ok": False, "message": "no pulse generated"}
    recipients = [e.strip().lower() for e in req.emails if e.strip()]
    if not recipients:
        return {"ok": False, "message": "no recipients selected"}
    if not _smtp_configured():
        return {
            "ok": True,
            "pulse_id": latest["pulse_id"],
            "sent_count": len(recipients),
            "failed_count": 0,
            "recipients": recipients,
            "failed": [],
            "mode": "mock_send",
        }
    subject = f"Groww Weekly Pulse #{latest['pulse_id']}"
    body = _format_pulse_for_doc(latest)
    sent: list[str] = []
    failed: list[dict[str, str]] = []
    for to_email in recipients:
        smtp = send_pulse_email_smtp(to_email=to_email, subject=subject, body=body)
        if smtp.ok:
            sent.append(to_email)
        else:
            failed.append({"email": to_email, "detail": smtp.detail})
    return {
        "ok": len(sent) > 0 and len(failed) == 0,
        "pulse_id": latest["pulse_id"],
        "sent_count": len(sent),
        "failed_count": len(failed),
        "recipients": sent,
        "failed": failed,
        "mode": "smtp_live",
    }


@app.get("/api/secure/{booking_code}")
def secure_booking_lookup(booking_code: str) -> dict[str, Any]:
    code = booking_code.strip().upper()
    with _db() as session:
        booking = session.scalar(select(Booking).where(Booking.booking_code == code))
    if not booking:
        return {"ok": False, "message": "invalid booking code"}
    details = dict((booking.integration_meta or {}).get("secure_details") or {})
    return {
        "ok": True,
        "booking": {
            "booking_code": booking.booking_code,
            "customer_name": booking.customer_name,
            "topic": booking.topic,
            "date": booking.date,
            "time_ist": booking.time_ist,
            "advisor": booking.advisor,
            "status": booking.status,
            "concern_summary": booking.concern_summary,
        },
        "secure_details": details,
    }


@app.post("/api/secure/{booking_code}/details")
def secure_booking_update_details(booking_code: str, req: SecureDetailsIn) -> dict[str, Any]:
    code = booking_code.strip().upper()
    if not _is_valid_india_phone(req.phone):
        return {"ok": False, "message": "phone must be valid +91 format"}
    if not _is_valid_email(req.email):
        return {"ok": False, "message": "email is invalid"}
    if req.consent is not True:
        return {"ok": False, "message": "consent is required"}
    with _db() as session:
        booking = session.scalar(select(Booking).where(Booking.booking_code == code))
        if not booking:
            return {"ok": False, "message": "invalid booking code"}
        meta = dict(booking.integration_meta or {})
        secure = {
            "phone": req.phone.strip(),
            "email": req.email.strip().lower(),
            "consent": True,
            "submitted_at": _now_ist_iso(),
            "sheet_columns_updated": ["K", "L"],
        }
        meta["secure_details"] = secure
        booking.integration_meta = meta
        session.commit()
    return {"ok": True, "message": "details saved", "booking_code": code, "secure_details": secure}
