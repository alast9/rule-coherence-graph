"""Tests for embedding providers."""

from __future__ import annotations

from rcg.providers.embedding import HashingEmbeddingProvider, cosine


def test_hashing_determinism() -> None:
    emb = HashingEmbeddingProvider()
    a = emb.embed(["deploy to production without tests"])[0]
    b = emb.embed(["deploy to production without tests"])[0]
    assert a == b


def test_hashing_dimension() -> None:
    emb = HashingEmbeddingProvider(dim=128)
    vec = emb.embed(["hello world"])[0]
    assert len(vec) == 128
    assert emb.model_id == "hashing-128"


def test_hashing_normalized() -> None:
    emb = HashingEmbeddingProvider()
    vec = emb.embed(["alpha beta gamma alpha"])[0]
    norm = sum(v * v for v in vec) ** 0.5
    assert abs(norm - 1.0) < 1e-9


def test_similar_vs_dissimilar_cosine_ordering() -> None:
    emb = HashingEmbeddingProvider()
    base = emb.embed(["deploy to production after running the tests"])[0]
    similar = emb.embed(["deploy to production after running the tests now"])[0]
    different = emb.embed(["encrypt all customer data at rest"])[0]
    assert cosine(base, similar) > cosine(base, different)


def test_cosine_zero_vector() -> None:
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0
