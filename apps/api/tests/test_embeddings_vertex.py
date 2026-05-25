"""Tests for :class:`VertexAIEmbeddingAdapter` and the live factory branch."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services.embeddings import get_embedding_adapter
from app.services.embeddings.mock import MockEmbeddingAdapter
from app.services.embeddings.vertex import (
    VertexAIEmbeddingAdapter,
    VertexEmbeddingAPIError,
    _parse_predictions,
)


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


def _vertex_payload(vectors: list[list[float]]) -> dict[str, Any]:
    return {
        "predictions": [
            {"embeddings": {"values": v, "statistics": {"token_count": 4}}} for v in vectors
        ],
        "metadata": {"billableCharacterCount": 100},
    }


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_vertex_embedding_rejects_empty_project_id() -> None:
    with pytest.raises(ValueError, match="VERTEX_PROJECT_ID is required"):
        VertexAIEmbeddingAdapter(project_id="", token_provider=lambda: "tok")


def test_vertex_embedding_rejects_non_positive_dimension() -> None:
    with pytest.raises(ValueError, match="dimension must be positive"):
        VertexAIEmbeddingAdapter(
            project_id="proj",
            dimension=0,
            token_provider=lambda: "tok",
        )


def test_vertex_embedding_rejects_non_positive_batch_size() -> None:
    with pytest.raises(ValueError, match="max_batch_size must be positive"):
        VertexAIEmbeddingAdapter(
            project_id="proj",
            max_batch_size=0,
            token_provider=lambda: "tok",
        )


def test_vertex_embedding_dimension_property() -> None:
    adapter = VertexAIEmbeddingAdapter(
        project_id="proj",
        dimension=512,
        token_provider=lambda: "tok",
    )
    assert adapter.dimension == 512


# ---------------------------------------------------------------------------
# Successful happy path
# ---------------------------------------------------------------------------


def test_vertex_embedding_returns_vectors_on_success() -> None:
    vectors = [[0.1] * 4, [0.2] * 4]
    body = _vertex_payload(vectors)
    with patch("app.services.embeddings.vertex.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value = _make_response(200, body)
        adapter = VertexAIEmbeddingAdapter(
            project_id="proj",
            location="us-central1",
            model="text-embedding-005",
            dimension=4,
            token_provider=lambda: "tok",
        )
        out = adapter.embed(["a", "b"])
    assert len(out) == 2
    assert out[0].values == [0.1] * 4
    assert out[1].values == [0.2] * 4
    # Verify the URL and auth header.
    call = client.post.call_args
    assert "us-central1-aiplatform.googleapis.com" in call.args[0]
    assert "/projects/proj/" in call.args[0]
    assert "/models/text-embedding-005:predict" in call.args[0]
    assert call.kwargs["headers"]["Authorization"] == "Bearer tok"
    body_sent = call.kwargs["json"]
    assert body_sent["instances"][0]["task_type"] == "RETRIEVAL_DOCUMENT"
    assert body_sent["parameters"]["outputDimensionality"] == 4
    assert body_sent["parameters"]["autoTruncate"] is True


def test_vertex_embedding_chunks_oversize_batches() -> None:
    # max_batch_size=2, 5 inputs → 3 round trips of size 2, 2, 1.
    responses = [
        _make_response(200, _vertex_payload([[0.1] * 4, [0.2] * 4])),
        _make_response(200, _vertex_payload([[0.3] * 4, [0.4] * 4])),
        _make_response(200, _vertex_payload([[0.5] * 4])),
    ]
    with patch("app.services.embeddings.vertex.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.post.side_effect = responses
        adapter = VertexAIEmbeddingAdapter(
            project_id="proj",
            dimension=4,
            max_batch_size=2,
            token_provider=lambda: "tok",
        )
        out = adapter.embed(["a", "b", "c", "d", "e"])
    assert client.post.call_count == 3
    assert [v.values[0] for v in out] == [0.1, 0.2, 0.3, 0.4, 0.5]


def test_vertex_embedding_empty_input_returns_empty_list() -> None:
    adapter = VertexAIEmbeddingAdapter(
        project_id="proj",
        dimension=4,
        token_provider=lambda: "tok",
    )
    with patch("app.services.embeddings.vertex.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        out = adapter.embed([])
    assert out == []
    client.post.assert_not_called()


# ---------------------------------------------------------------------------
# Failure → graceful degrade to mock fallback
# ---------------------------------------------------------------------------


def test_vertex_embedding_falls_back_on_non_200() -> None:
    fallback = MockEmbeddingAdapter(dimension=4)
    with patch("app.services.embeddings.vertex.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value = _make_response(500, {"error": "oops"})
        adapter = VertexAIEmbeddingAdapter(
            project_id="proj",
            dimension=4,
            token_provider=lambda: "tok",
            fallback=fallback,
        )
        out = adapter.embed(["hello"])
    assert len(out) == 1
    assert out[0].values == fallback.embed(["hello"])[0].values


def test_vertex_embedding_falls_back_on_transport_error() -> None:
    fallback = MockEmbeddingAdapter(dimension=4)
    with patch("app.services.embeddings.vertex.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.post.side_effect = httpx.ConnectError("dns")
        adapter = VertexAIEmbeddingAdapter(
            project_id="proj",
            dimension=4,
            token_provider=lambda: "tok",
            fallback=fallback,
        )
        out = adapter.embed(["hello"])
    assert len(out) == 1
    assert out[0].values == fallback.embed(["hello"])[0].values


def test_vertex_embedding_falls_back_on_non_json() -> None:
    fallback = MockEmbeddingAdapter(dimension=4)
    with patch("app.services.embeddings.vertex.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value = _make_response(200, "not-json")
        adapter = VertexAIEmbeddingAdapter(
            project_id="proj",
            dimension=4,
            token_provider=lambda: "tok",
            fallback=fallback,
        )
        out = adapter.embed(["hello"])
    assert len(out) == 1
    assert out[0].values == fallback.embed(["hello"])[0].values


def test_vertex_embedding_falls_back_on_empty_token() -> None:
    fallback = MockEmbeddingAdapter(dimension=4)
    adapter = VertexAIEmbeddingAdapter(
        project_id="proj",
        dimension=4,
        token_provider=lambda: "",
        fallback=fallback,
    )
    with patch("app.services.embeddings.vertex.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        out = adapter.embed(["hello"])
    # Token provider returned empty before the HTTP layer was reached.
    client.post.assert_not_called()
    assert out[0].values == fallback.embed(["hello"])[0].values


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def test_parse_predictions_rejects_non_object_payload() -> None:
    with pytest.raises(VertexEmbeddingAPIError, match="non-object"):
        _parse_predictions([], expected_count=1, dimension=4)


def test_parse_predictions_rejects_missing_predictions() -> None:
    with pytest.raises(VertexEmbeddingAPIError, match="predictions missing"):
        _parse_predictions({"metadata": {}}, expected_count=1, dimension=4)


def test_parse_predictions_rejects_wrong_count() -> None:
    with pytest.raises(VertexEmbeddingAPIError, match="expected 2 predictions"):
        _parse_predictions(
            _vertex_payload([[0.1] * 4]),
            expected_count=2,
            dimension=4,
        )


def test_parse_predictions_rejects_wrong_dimension() -> None:
    with pytest.raises(VertexEmbeddingAPIError, match="has 4 dims, expected 8"):
        _parse_predictions(
            _vertex_payload([[0.1] * 4]),
            expected_count=1,
            dimension=8,
        )


def test_parse_predictions_rejects_missing_embeddings() -> None:
    payload = {"predictions": [{"foo": "bar"}]}
    with pytest.raises(VertexEmbeddingAPIError, match="missing 'embeddings'"):
        _parse_predictions(payload, expected_count=1, dimension=4)


def test_parse_predictions_rejects_non_numeric_values() -> None:
    payload = {"predictions": [{"embeddings": {"values": ["not", "a", "number", "x"]}}]}
    with pytest.raises(VertexEmbeddingAPIError, match="non-numeric"):
        _parse_predictions(payload, expected_count=1, dimension=4)


# ---------------------------------------------------------------------------
# Factory degrade behaviour
# ---------------------------------------------------------------------------


def test_factory_returns_mock_when_provider_is_mock(monkeypatch) -> None:
    from app.config import get_settings

    get_settings.cache_clear()
    get_embedding_adapter.cache_clear()
    monkeypatch.setenv("EMBEDDING_PROVIDER", "mock")
    try:
        adapter = get_embedding_adapter()
    finally:
        get_settings.cache_clear()
        get_embedding_adapter.cache_clear()
    assert isinstance(adapter, MockEmbeddingAdapter)


def test_factory_degrades_to_mock_when_project_missing(monkeypatch) -> None:
    from app.config import get_settings

    get_settings.cache_clear()
    get_embedding_adapter.cache_clear()
    monkeypatch.setenv("EMBEDDING_PROVIDER", "live")
    monkeypatch.delenv("VERTEX_PROJECT_ID", raising=False)
    monkeypatch.setenv("GOOGLE_OAUTH_ACCESS_TOKEN", "tok")
    try:
        adapter = get_embedding_adapter()
    finally:
        get_settings.cache_clear()
        get_embedding_adapter.cache_clear()
        monkeypatch.delenv("GOOGLE_OAUTH_ACCESS_TOKEN", raising=False)
    assert isinstance(adapter, MockEmbeddingAdapter)


def test_factory_degrades_to_mock_when_token_missing(monkeypatch) -> None:
    from app.config import get_settings

    get_settings.cache_clear()
    get_embedding_adapter.cache_clear()
    monkeypatch.setenv("EMBEDDING_PROVIDER", "live")
    monkeypatch.setenv("VERTEX_PROJECT_ID", "proj")
    monkeypatch.delenv("GOOGLE_OAUTH_ACCESS_TOKEN", raising=False)
    try:
        adapter = get_embedding_adapter()
    finally:
        get_settings.cache_clear()
        get_embedding_adapter.cache_clear()
        monkeypatch.delenv("VERTEX_PROJECT_ID", raising=False)
    assert isinstance(adapter, MockEmbeddingAdapter)


def test_factory_returns_vertex_when_fully_configured(monkeypatch) -> None:
    from app.config import get_settings

    get_settings.cache_clear()
    get_embedding_adapter.cache_clear()
    monkeypatch.setenv("EMBEDDING_PROVIDER", "live")
    monkeypatch.setenv("VERTEX_PROJECT_ID", "proj")
    monkeypatch.setenv("GOOGLE_OAUTH_ACCESS_TOKEN", "tok")
    try:
        adapter = get_embedding_adapter()
    finally:
        get_settings.cache_clear()
        get_embedding_adapter.cache_clear()
        monkeypatch.delenv("VERTEX_PROJECT_ID", raising=False)
        monkeypatch.delenv("GOOGLE_OAUTH_ACCESS_TOKEN", raising=False)
    assert isinstance(adapter, VertexAIEmbeddingAdapter)
