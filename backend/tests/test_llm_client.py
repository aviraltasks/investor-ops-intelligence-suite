"""Unit tests for LLM JSON parsing (no network)."""

from __future__ import annotations

from app.llm import client as llm_client
from app.llm.client import parse_json_object


def test_parse_json_object_plain() -> None:
    assert parse_json_object('{"intents":["faq"],"reasoning":"test"}') == {
        "intents": ["faq"],
        "reasoning": "test",
    }


def test_parse_json_object_fenced() -> None:
    raw = '```json\n{"a":1}\n```'
    assert parse_json_object(raw) == {"a": 1}


def test_parse_json_object_embedded() -> None:
    raw = 'Here you go: {"x": true} thanks'
    assert parse_json_object(raw) == {"x": True}


def test_gemini_model_default_when_env_missing(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    assert llm_client._gemini_model() == "gemini-2.5-flash-lite"
