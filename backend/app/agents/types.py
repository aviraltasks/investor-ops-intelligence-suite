"""Shared types for agent orchestration traces."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AgentTraceStep(BaseModel):
    agent: str
    reasoning_brief: str
    tools: list[str] = Field(default_factory=list)
    replanned: bool = False
    outcome: str = ""


class AgentResult(BaseModel):
    response_text: str
    payload: dict[str, Any] = Field(default_factory=dict)
    traces: list[AgentTraceStep] = Field(default_factory=list)
