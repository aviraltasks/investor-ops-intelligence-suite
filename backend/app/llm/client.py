"""Groq-first, Gemini-fallback chat completions via HTTP (httpx)."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

import httpx


@dataclass
class LLMResponse:
    text: str
    provider: str  # groq | gemini | none
    error: str = ""


def llm_available() -> bool:
    # Keep automated tests deterministic even when developer machine has live API keys.
    if os.getenv("PYTEST_CURRENT_TEST") and (os.getenv("ENABLE_LLM_IN_PYTEST") or "").strip().lower() not in {
        "1",
        "true",
        "yes",
    }:
        return False
    return bool((os.getenv("GROQ_API_KEY") or "").strip() or (os.getenv("GEMINI_API_KEY") or "").strip())


def _groq_model() -> str:
    return os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()


def _gemini_model() -> str:
    return os.getenv("GEMINI_MODEL", "gemini-2.0-flash").strip()


def _candidate_gemini_models() -> list[str]:
    primary = _gemini_model()
    # Include safe fallbacks so a misconfigured model ID doesn't disable all LLM usage.
    candidates = [
        primary,
        "gemini-2.0-flash",
        "gemini-1.5-flash",
    ]
    out: list[str] = []
    seen: set[str] = set()
    for m in candidates:
        t = (m or "").strip()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _call_groq(messages: list[dict[str, str]], *, temperature: float) -> str:
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("missing GROQ_API_KEY")
    payload = {
        "model": _groq_model(),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 4096,
    }
    with httpx.Client(timeout=90.0) as client:
        r = client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
        )
        r.raise_for_status()
        data = r.json()
    return str(data["choices"][0]["message"]["content"]).strip()


def _call_gemini(messages: list[dict[str, str]], *, temperature: float) -> str:
    key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("missing GEMINI_API_KEY")
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    user = "\n\n".join(m["content"] for m in messages if m["role"] == "user")
    combined = (system + "\n\n---\n\nUSER:\n" + user).strip()
    last_err = "gemini_unknown"
    for model in _candidate_gemini_models():
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        body = {
            "contents": [{"role": "user", "parts": [{"text": combined}]}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": 4096},
        }
        try:
            with httpx.Client(timeout=90.0) as client:
                r = client.post(url, params={"key": key}, json=body)
                r.raise_for_status()
                data = r.json()
            cands = data.get("candidates") or []
            if not cands:
                raise RuntimeError("gemini_empty_candidates")
            parts = (cands[0].get("content") or {}).get("parts") or []
            if not parts:
                raise RuntimeError("gemini_empty_parts")
            text = str(parts[0].get("text", "")).strip()
            if not text:
                raise RuntimeError("gemini_empty_text")
            return text
        except Exception as e:
            last_err = f"{type(e).__name__}:{e}"
            continue
    raise RuntimeError(last_err)


def chat_completion(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.25,
) -> LLMResponse:
    """
    Try Groq (OpenAI-compatible chat completions), then Gemini generateContent.
    Returns provider \"none\" and empty text if no keys are configured or both providers fail.
    """
    if not llm_available():
        return LLMResponse("", "none", "llm_keys_missing")

    groq_key = (os.getenv("GROQ_API_KEY") or "").strip()
    gem_key = (os.getenv("GEMINI_API_KEY") or "").strip()
    errors: list[str] = []

    if groq_key:
        try:
            return LLMResponse(_call_groq(messages, temperature=temperature), "groq")
        except Exception as e:
            errors.append(f"groq:{type(e).__name__}:{e}")
            if not gem_key:
                return LLMResponse("", "none", "; ".join(errors))

    if gem_key:
        try:
            return LLMResponse(_call_gemini(messages, temperature=temperature), "gemini")
        except Exception as e:
            errors.append(f"gemini:{type(e).__name__}:{e}")
            return LLMResponse("", "none", "; ".join(errors))

    return LLMResponse("", "none", "; ".join(errors) if errors else "llm_provider_unavailable")


def chat_completion_safe(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.25,
) -> LLMResponse:
    """Never raises; returns provider \"none\" on total failure."""
    if not llm_available():
        return LLMResponse("", "none", "llm_keys_missing")
    try:
        return chat_completion(messages, temperature=temperature)
    except Exception as e:
        return LLMResponse("", "none", f"chat_completion_safe:{type(e).__name__}:{e}")


def parse_json_object(text: str) -> dict | None:
    """Extract a JSON object from model output (handles optional markdown fences)."""
    raw = text.strip()
    if "```" in raw:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw, re.IGNORECASE)
        if m:
            raw = m.group(1).strip()
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            return None
        try:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
