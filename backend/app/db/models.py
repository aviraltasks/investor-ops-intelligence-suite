"""ORM models for RAG, reviews, and pulse history."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RagChunk(Base):
    """Embedded text chunk for retrieval (Groww fund pages + SEBI + extras)."""

    __tablename__ = "rag_chunks"
    __table_args__ = (UniqueConstraint("source_url", "chunk_index", name="uq_rag_source_chunk"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False, index=True)
    layer: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    fund_slug: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    fund_display_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Review(Base):
    """Play Store review row (live fetch or CSV fallback)."""

    __tablename__ = "reviews"
    __table_args__ = (UniqueConstraint("external_id", name="uq_review_external_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    source: Mapped[str] = mapped_column(String(32), default="play_store")


class PulseRun(Base):
    """One generated pulse summary run."""

    __tablename__ = "pulse_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    mode: Mapped[str] = mapped_column(String(32), default="ml")  # ml | llm_fallback
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    date_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    date_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    analysis: Mapped[str] = mapped_column(Text, default="")
    actions_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    metrics_json: Mapped[dict] = mapped_column(JSON, default=dict)
    comparison_json: Mapped[dict] = mapped_column(JSON, default=dict)


class PulseTheme(Base):
    """Theme breakdown for a pulse run."""

    __tablename__ = "pulse_themes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pulse_run_id: Mapped[int] = mapped_column(Integer, index=True)
    rank: Mapped[int] = mapped_column(Integer, default=1)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    volume: Mapped[int] = mapped_column(Integer, default=0)
    quote: Mapped[str] = mapped_column(Text, default="")


class Booking(Base):
    """Phase-4 local booking lifecycle storage (Google sync in Phase 6)."""

    __tablename__ = "bookings"
    __table_args__ = (UniqueConstraint("booking_code", name="uq_booking_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(128), index=True)
    customer_name: Mapped[str] = mapped_column(String(128), default="User")
    topic: Mapped[str] = mapped_column(String(128), default="General support")
    date: Mapped[str] = mapped_column(String(16), default="")
    time_ist: Mapped[str] = mapped_column(String(32), default="")
    advisor: Mapped[str] = mapped_column(String(32), default="Advisor 1")
    booking_code: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="tentative")
    concern_summary: Mapped[str] = mapped_column(Text, default="")
    calendar_event_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sheet_row_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email_status: Mapped[str] = mapped_column(String(32), default="draft_queued")
    integration_meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class MemoryFact(Base):
    """Simple long-term memory facts linked to session/user."""

    __tablename__ = "memory_facts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(128), index=True)
    user_name: Mapped[str] = mapped_column(String(128), default="User")
    key: Mapped[str] = mapped_column(String(64), index=True)
    value: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class InteractionLog(Base):
    """Conversation interaction log for analytics graphing."""

    __tablename__ = "interaction_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(128), index=True)
    user_name: Mapped[str] = mapped_column(String(128), default="User")
    intent: Mapped[str] = mapped_column(String(32), index=True)  # faq | scheduling | review_context | general
    topic: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class AgentActivityLog(Base):
    """Per-step agent trace log for admin activity panel."""

    __tablename__ = "agent_activity_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(128), index=True)
    user_name: Mapped[str] = mapped_column(String(128), default="User")
    agent: Mapped[str] = mapped_column(String(64), index=True)
    reasoning_brief: Mapped[str] = mapped_column(Text, default="")
    tools_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    outcome: Mapped[str] = mapped_column(String(128), default="")
    query_summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class Subscriber(Base):
    """Pulse subscriber emails for admin send selection."""

    __tablename__ = "subscribers"
    __table_args__ = (UniqueConstraint("email", name="uq_subscriber_email"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    active: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
