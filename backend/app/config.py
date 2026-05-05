"""Application settings from environment variables."""

from __future__ import annotations

import os
from functools import lru_cache


def reset_settings() -> None:
    """Clear cached settings (used in tests)."""
    get_database_url.cache_clear()


@lru_cache
def get_database_url() -> str:
    """SQLAlchemy URL. Defaults to local SQLite for dev/tests."""
    return os.getenv("DATABASE_URL", "sqlite:///./data/investor_ops.db")


def get_embedding_model_name() -> str:
    return os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")


def get_play_store_app_id() -> str:
    return os.getenv("PLAY_STORE_APP_ID", "com.nextbillion.groww")


def get_reviews_fallback_csv() -> str | None:
    return os.getenv("REVIEWS_FALLBACK_CSV")


def get_google_integrations_mode() -> str:
    """Integration mode: mock (default) or live."""
    return os.getenv("GOOGLE_INTEGRATIONS_MODE", "mock").strip().lower()


def get_google_calendar_id() -> str | None:
    return os.getenv("GOOGLE_CALENDAR_ID")


def get_google_sheet_id() -> str | None:
    return os.getenv("GOOGLE_SHEET_ID")


def get_google_doc_id() -> str | None:
    """Target Google Doc for pulse append (service account must have edit access)."""
    raw = os.getenv("GOOGLE_DOC_ID")
    return raw.strip() if raw else None
