"""Character-based chunking with overlap."""

from __future__ import annotations


def chunk_text(
    text: str,
    max_chars: int = 900,
    overlap: int = 120,
) -> list[str]:
    """Split cleaned text into overlapping windows for embedding."""
    t = " ".join(text.split())
    if not t:
        return []
    if len(t) <= max_chars:
        return [t]
    chunks: list[str] = []
    start = 0
    while start < len(t):
        end = min(len(t), start + max_chars)
        piece = t[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(t):
            break
        start = max(0, end - overlap)
    return chunks
