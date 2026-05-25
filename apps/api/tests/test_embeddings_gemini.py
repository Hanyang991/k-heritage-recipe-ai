"""Tests for :class:`GeminiEmbeddingAdapter` and the gemini factory branch."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services.embeddings import get_embedding_adapter
from app.services.embeddings.gemini import (
    GeminiEmbeddingAdapter,
    GeminiEmbeddingAPIError,
    _parse_values,
)
from app.services.embeddings.mock import MockEmbeddingAdapter


def _make_response(status: int, body: dict | str) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    if isinstance(body, str):
        resp.text = body
        resp.json = MagicMock(side_effect=ValueError("not json"))
    else:
        resp.text = json.dumps(body)
        resp.json = MagicMock(return_value=body)
    return resp


def _single_payload(values: list[float]) -> dict[str, Any]:
    return {"embedding": {"values": values}}


def _batch_payload(vectors: list[list[float]]) -> dict[str, Any]:
    return {"embeddings": [{"values": v} for v in vectors]}


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_gemini_embedding_rejects_empty_api_key() -> None:
    with pytest.raises(ValueError, match="GEMINI_API_KEY is required"):
        GeminiEmbeddingAdapter(api_key="")


def test_gemini_embedding_rejects_non_positive_dimension() -> None:
    with pytest.raises(ValueError, match="dimension must be positive"):
        GeminiEmbeddingAdapter(api_key="key", dimension=0)


def test_gemini_embedding_rejects_non_positive_batch_size() -> None:
    with pytest.raises(ValueError, match="max_batch_size must be positive"):
        GeminiEmbeddingAdapter(api_key="key", max_batch_size=0)


def test_gemini_embedding_dimension_property() -> None:
    adapter = GeminiEmbeddingAdapter(api_key="key", dimension=512)
    assert adapter.dimension == 512


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_gemini_embedding_single_input_uses_single_endpoint() -> None:
    with patch("app.services.embeddings.gemini.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value = _make_response(200, _single_payload([0.1] * 4))
        adapter = GeminiEmbeddingAdapter(api_key="api-key", dimension=4)
        out = adapter.embed(["hello"])
    assert len(out) == 1
    assert out[0].values == [0.1] * 4
    call = client.post.call_args
    assert ":embedContent" in call.args[0]
    assert "text-embedding-004" in call.args[0]
    assert call.kwargs["params"] == {"key": "api-key"}
    body_sent = call.kwargs["json"]
    assert body_sent["content"]["parts"][0]["text"] == "hello"
    assert body_sent["taskType"] == "RETRIEVAL_DOCUMENT"
    assert body_sent["outputDimensionality"] == 4


def test_gemini_embedding_multi_input_uses_batch_endpoint() -> None:
    with patch("app.services.embeddings.gemini.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value = _make_response(200, _batch_payload([[0.1] * 4, [0.2] * 4]))
        adapter = GeminiEmbeddingAdapter(api_key="api-key", dimension=4)
        out = adapter.embed(["a", "b"])
    assert [v.values[0] for v in out] == [0.1, 0.2]
    call = client.post.call_args
    assert ":batchEmbedContents" in call.args[0]
    body_sent = call.kwargs["json"]
    assert len(body_sent["requests"]) == 2
    assert body_sent["requests"][0]["content"]["parts"][0]["text"] == "a"
    assert body_sent["requests"][1]["content"]["parts"][0]["text"] == "b"


def test_gemini_embedding_chunks_oversize_batches() -> None:
    # max_batch_size=2, 5 inputs → 3 round trips of size 2, 2, 1
    # (the 1-input chunk uses the single endpoint).
    responses = [
        _make_response(200, _batch_payload([[0.1] * 4, [0.2] * 4])),
        _make_response(200, _batch_payload([[0.3] * 4, [0.4] * 4])),
        _make_response(200, _single_payload([0.5] * 4)),
    ]
    with patch("app.services.embeddings.gemini.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.post.side_effect = responses
        adapter = GeminiEmbeddingAdapter(api_key="api-key", dimension=4, max_batch_size=2)
        out = adapter.embed(["a", "b", "c", "d", "e"])
    assert client.post.call_count == 3
    assert [v.values[0] for v in out] == [0.1, 0.2, 0.3, 0.4, 0.5]


def test_gemini_embedding_empty_input_returns_empty_list() -> None:
    adapter = GeminiEmbeddingAdapter(api_key="api-key", dimension=4)
    with patch("app.services.embeddings.gemini.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        out = adapter.embed([])
    assert out == []
    client.post.assert_not_called()


# ---------------------------------------------------------------------------
# Failure → graceful degrade to mock fallback
# ---------------------------------------------------------------------------


def test_gemini_embedding_falls_back_on_non_200() -> None:
    fallback = MockEmbeddingAdapter(dimension=4)
    with patch("app.services.embeddings.gemini.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value = _make_response(429, {"error": "rate-limited"})
        adapter = GeminiEmbeddingAdapter(api_key="api-key", dimension=4, fallback=fallback)
        out = adapter.embed(["hello"])
    assert out[0].values == fallback.embed(["hello"])[0].values


def test_gemini_embedding_falls_back_on_transport_error() -> None:
    fallback = MockEmbeddingAdapter(dimension=4)
    with patch("app.services.embeddings.gemini.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.post.side_effect = httpx.ConnectError("dns")
        adapter = GeminiEmbeddingAdapter(api_key="api-key", dimension=4, fallback=fallback)
        out = adapter.embed(["hello"])
    assert out[0].values == fallback.embed(["hello"])[0].values


def test_gemini_embedding_falls_back_on_non_json() -> None:
    fallback = MockEmbeddingAdapter(dimension=4)
    with patch("app.services.embeddings.gemini.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value = _make_response(200, "not-json")
        adapter = GeminiEmbeddingAdapter(api_key="api-key", dimension=4, fallback=fallback)
        out = adapter.embed(["hello"])
    assert out[0].values == fallback.embed(["hello"])[0].values


def test_gemini_embedding_falls_back_on_wrong_dimension() -> None:
    fallback = MockEmbeddingAdapter(dimension=4)
    with patch("app.services.embeddings.gemini.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        # Single-input path returns wrong-size values.
        client.post.return_value = _make_response(
            200,
            _single_payload([0.1, 0.2]),  # 2 dims, expected 4
        )
        adapter = GeminiEmbeddingAdapter(api_key="api-key", dimension=4, fallback=fallback)
        out = adapter.embed(["hello"])
    assert out[0].values == fallback.embed(["hello"])[0].values


def test_gemini_embedding_falls_back_when_batch_count_mismatches() -> None:
    fallback = MockEmbeddingAdapter(dimension=4)
    with patch("app.services.embeddings.gemini.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value = _make_response(
            200,
            _batch_payload([[0.1] * 4]),  # only 1 embedding for 2 inputs
        )
        adapter = GeminiEmbeddingAdapter(api_key="api-key", dimension=4, fallback=fallback)
        out = adapter.embed(["a", "b"])
    assert len(out) == 2
    # Falls back to mock so vectors should match mock outputs for both inputs.
    assert out[0].values == fallback.embed(["a"])[0].values
    assert out[1].values == fallback.embed(["b"])[0].values


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def test_parse_values_rejects_empty_list() -> None:
    with pytest.raises(GeminiEmbeddingAPIError, match="missing or empty"):
        _parse_values([], dimension=4, index=0)


def test_parse_values_rejects_non_list() -> None:
    with pytest.raises(GeminiEmbeddingAPIError, match="missing or empty"):
        _parse_values(None, dimension=4, index=2)


def test_parse_values_rejects_non_numeric_values() -> None:
    with pytest.raises(GeminiEmbeddingAPIError, match="non-numeric"):
        _parse_values(["a", "b", "c", "d"], dimension=4, index=0)


def test_parse_values_rejects_wrong_dimension() -> None:
    with pytest.raises(GeminiEmbeddingAPIError, match="has 4 dims, expected 8"):
        _parse_values([0.1] * 4, dimension=8, index=0)


# ---------------------------------------------------------------------------
# Factory branch
# ---------------------------------------------------------------------------


def test_factory_returns_gemini_when_key_present(monkeypatch) -> None:
    from app.config import get_settings

    get_settings.cache_clear()
    get_embedding_adapter.cache_clear()
    monkeypatch.setenv("EMBEDDING_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "abc")
    try:
        adapter = get_embedding_adapter()
    finally:
        get_settings.cache_clear()
        get_embedding_adapter.cache_clear()
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert isinstance(adapter, GeminiEmbeddingAdapter)
    assert adapter.dimension == 768


def test_factory_degrades_to_mock_when_gemini_key_missing(monkeypatch) -> None:
    from app.config import get_settings

    get_settings.cache_clear()
    get_embedding_adapter.cache_clear()
    monkeypatch.setenv("EMBEDDING_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    try:
        adapter = get_embedding_adapter()
    finally:
        get_settings.cache_clear()
        get_embedding_adapter.cache_clear()
    assert isinstance(adapter, MockEmbeddingAdapter)
