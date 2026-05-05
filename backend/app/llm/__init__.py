"""LLM client (Groq primary, Gemini fallback)."""

from app.llm.client import LLMResponse, chat_completion, llm_available

__all__ = ["LLMResponse", "chat_completion", "llm_available"]
