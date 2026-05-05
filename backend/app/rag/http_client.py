"""Shared HTTP client for scraping."""

from __future__ import annotations

import httpx

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
}


def new_client(timeout: float = 45.0) -> httpx.Client:
    return httpx.Client(headers=DEFAULT_HEADERS, timeout=timeout, follow_redirects=True)
