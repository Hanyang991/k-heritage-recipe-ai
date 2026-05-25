"""Tests for :class:`MockEmbeddingAdapter` — deterministic hash embedder."""

from __future__ import annotations

import math

import pytest

from app.services.embeddings.mock import MockEmbeddingAdapter


def test_mock_embedder_returns_unit_norm_vectors() -> None:
    adapter = MockEmbeddingAdapter(dimension=64)
    [vec] = adapter.embed(["음식디미방"])
    assert vec.dimension == 64
    assert len(vec.values) == 64
    norm = math.sqrt(sum(x * x for x in vec.values))
    assert math.isclose(norm, 1.0, abs_tol=1e-9)


def test_mock_embedder_is_deterministic_within_process() -> None:
    adapter = MockEmbeddingAdapter(dimension=32)
    a = adapter.embed(["음식디미방"])[0].values
    b = adapter.embed(["음식디미방"])[0].values
    assert a == b


def test_mock_embedder_is_deterministic_across_instances() -> None:
    # Same dimension + same text → same vector across separate instances.
    a = MockEmbeddingAdapter(dimension=16).embed(["쑥"])[0].values
    b = MockEmbeddingAdapter(dimension=16).embed(["쑥"])[0].values
    assert a == b


def test_mock_embedder_different_text_produces_different_vector() -> None:
    adapter = MockEmbeddingAdapter(dimension=128)
    a = adapter.embed(["음식디미방"])[0].values
    b = adapter.embed(["음식 디미방"])[0].values  # added whitespace
    # Should be different because hash input differs.
    assert a != b


def test_mock_embedder_batches_preserve_order() -> None:
    adapter = MockEmbeddingAdapter(dimension=32)
    texts = ["alpha", "beta", "gamma", "delta"]
    batch = adapter.embed(texts)
    individual = [adapter.embed([t])[0] for t in texts]
    assert [v.values for v in batch] == [v.values for v in individual]


def test_mock_embedder_dimension_property_matches_constructor() -> None:
    for dim in (8, 64, 768, 1024):
        adapter = MockEmbeddingAdapter(dimension=dim)
        assert adapter.dimension == dim


def test_mock_embedder_rejects_non_positive_dimension() -> None:
    with pytest.raises(ValueError, match="dimension must be positive"):
        MockEmbeddingAdapter(dimension=0)
    with pytest.raises(ValueError, match="dimension must be positive"):
        MockEmbeddingAdapter(dimension=-4)


def test_mock_embedder_handles_empty_string() -> None:
    # Empty string is a valid input; should still produce a unit-norm vector
    # (the hash chain handles zero-byte seed without crashing).
    adapter = MockEmbeddingAdapter(dimension=16)
    [vec] = adapter.embed([""])
    assert len(vec.values) == 16
    norm = math.sqrt(sum(x * x for x in vec.values))
    assert math.isclose(norm, 1.0, abs_tol=1e-9)


def test_mock_embedder_handles_empty_batch() -> None:
    adapter = MockEmbeddingAdapter(dimension=16)
    assert adapter.embed([]) == []
