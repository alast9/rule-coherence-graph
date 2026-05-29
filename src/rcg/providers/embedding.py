"""Embedding providers for semantic recall.

The semantic detector embeds rule text and uses cosine similarity to find
candidate pairs worth sending to an (expensive) LLM judge. Two providers are
offered:

* :class:`HashingEmbeddingProvider` — dependency-free, deterministic, captures
  *lexical* overlap only. It is a stand-in so the pipeline runs offline; real
  semantic recall needs a true embedding model.
* :class:`SentenceTransformerEmbeddingProvider` — wraps ``sentence_transformers``
  (install the ``embeddings`` extra) for genuine semantic embeddings.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol, runtime_checkable

_TOKEN_RE = re.compile(r"\w+")


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Turns text into fixed-dimension vectors."""

    model_id: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two equal-length vectors (0.0 if either is zero)."""
    if len(a) != len(b):
        raise ValueError("vectors must have equal length")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class HashingEmbeddingProvider:
    """Deterministic, dependency-free hashing embedder.

    Tokenizes on ``\\w+`` (lowercased), hashes each token into one of ``dim``
    buckets (incrementing the bucket), then L2-normalizes the vector. This
    captures *lexical* overlap between texts; it does not understand synonyms or
    paraphrase. For real semantic recall use
    :class:`SentenceTransformerEmbeddingProvider`.
    """

    def __init__(self, dim: int = 256) -> None:
        if dim <= 0:
            raise ValueError("dim must be positive")
        self.dim = dim
        self.model_id = f"hashing-{dim}"

    def _bucket(self, token: str) -> int:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") % self.dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vec = [0.0] * self.dim
            for token in _TOKEN_RE.findall(text.lower()):
                vec[self._bucket(token)] += 1.0
            norm = math.sqrt(sum(v * v for v in vec))
            if norm > 0.0:
                vec = [v / norm for v in vec]
            vectors.append(vec)
        return vectors


class SentenceTransformerEmbeddingProvider:
    """Real semantic embeddings via ``sentence_transformers``.

    Requires the optional ``embeddings`` extra::

        pip install 'rule-coherence-graph[embeddings]'
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        try:
            from sentence_transformers import (  # type: ignore[import-not-found]
                SentenceTransformer,
            )
        except ImportError as exc:  # pragma: no cover - exercised only without extra
            raise ImportError(
                "SentenceTransformerEmbeddingProvider requires 'sentence-transformers'. "
                "Install the embeddings extra: pip install 'rule-coherence-graph[embeddings]'"
            ) from exc
        self._model = SentenceTransformer(model_name)
        self.model_id = f"sentence-transformers/{model_name}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        encoded = self._model.encode(texts, normalize_embeddings=True)
        return [list(map(float, row)) for row in encoded]
