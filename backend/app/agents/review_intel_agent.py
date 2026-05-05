"""Review intelligence agent adapter for latest pulse context."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.agents.types import AgentTraceStep
from app.ml.theme_pipeline import get_latest_pulse


def get_trending_context(session: Session) -> tuple[dict, AgentTraceStep]:
    pulse = get_latest_pulse(session)
    if not pulse:
        return (
            {"top_theme": None, "pulse_id": None},
            AgentTraceStep(
                agent="review_intelligence_agent",
                reasoning_brief="No pulse exists yet; skip trending context.",
                tools=["db.select(pulse_runs)"],
                outcome="no_pulse",
            ),
        )
    top = pulse["top_themes"][0]["label"] if pulse.get("top_themes") else None
    return (
        {"top_theme": top, "pulse_id": pulse["pulse_id"], "pulse": pulse},
        AgentTraceStep(
            agent="review_intelligence_agent",
            reasoning_brief="Loaded latest pulse to inform proactive greeting and email context.",
            tools=["db.select(pulse_runs)", "db.select(pulse_themes)"],
            outcome="pulse_context_loaded",
        ),
    )
