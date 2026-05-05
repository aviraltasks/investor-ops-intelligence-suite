"""Extract plain text from HTML pages and SEBI PDFs."""

from __future__ import annotations

import io
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from pypdf import PdfReader


def extract_text_from_html(html: str) -> str:
    # html.parser avoids native build deps such as lxml on local Windows.
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body
    if not main:
        return ""
    text = main.get_text("\n", strip=True)
    lines = [ln for ln in (line.strip() for line in text.splitlines()) if ln]
    return "\n".join(lines)


def extract_text_from_bytes(url: str, data: bytes) -> str:
    path = urlparse(url).path.lower()
    if path.endswith(".pdf"):
        reader = PdfReader(io.BytesIO(data))
        parts: list[str] = []
        for page in reader.pages[:40]:
            t = page.extract_text() or ""
            if t.strip():
                parts.append(t.strip())
        return "\n\n".join(parts)
    return extract_text_from_html(data.decode("utf-8", errors="ignore"))
