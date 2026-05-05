"""Embedding backends with lightweight default for stability."""

from __future__ import annotations

import hashlib
from threading import Lock
from typing import Protocol, runtime_checkable

import numpy as np

from app.config import get_embedding_model_name


@runtime_checkable
class Embedder(Protocol):
    embedding_dim: int

    def encode(self, texts: list[str]) -> np.ndarray:
        """Return float32 matrix shape (len(texts), dim)."""


class HashEmbedder:
    """Fast, dependency-light embedder for local/dev pipelines.

    Uses hashing trick with signed buckets and l2-normalization.
    """

    def __init__(self, embedding_dim: int = 384) -> None:
        self.embedding_dim = embedding_dim

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.embedding_dim), dtype=np.float32)
        mat = np.zeros((len(texts), self.embedding_dim), dtype=np.float32)
        for i, text in enumerate(texts):
            words = text.lower().split()
            if not words:
                continue
            for w in words:
                h = hashlib.md5(w.encode("utf-8")).hexdigest()
                bucket = int(h[:8], 16) % self.embedding_dim
                sign = 1.0 if int(h[8:10], 16) % 2 == 0 else -1.0
                mat[i, bucket] += sign
            norm = np.linalg.norm(mat[i])
            if norm > 0:
                mat[i] /= norm
        return mat


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str | None = None) -> None:
        from sentence_transformers import SentenceTransformer

        name = model_name or get_embedding_model_name()
        self._model = SentenceTransformer(name)
        v = self._model.get_sentence_embedding_dimension()
        self.embedding_dim = int(v)

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.embedding_dim), dtype=np.float32)
        emb = self._model.encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return np.asarray(emb, dtype=np.float32)


_embedder: Embedder | None = None
_lock = Lock()


def _build_default_embedder() -> Embedder:
    model = get_embedding_model_name().strip().lower()
    if model in {"hash", "local-hash", ""}:
        return HashEmbedder()
    if model.startswith("sentence-transformers/"):
        try:
            return SentenceTransformerEmbedder(model)
        except Exception:
            return HashEmbedder()
    return HashEmbedder()


def get_embedder() -> Embedder:
    global _embedder
    with _lock:
        if _embedder is None:
            _embedder = _build_default_embedder()
        return _embedder


def set_embedder(embedder: Embedder | None) -> None:
    """Test hook."""
    global _embedder
    _embedder = embedder
