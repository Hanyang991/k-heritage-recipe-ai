"""Vertex AI text-embedding REST adapter (``EMBEDDING_PROVIDER=live``).

Calls Google Vertex AI's publisher-model ``:predict`` endpoint to embed
batches of strings. We hit the REST surface directly with ``httpx``
rather than pulling in ``google-cloud-aiplatform`` (heavy ``grpcio`` +
auth chain) — same pattern as :class:`GeminiLLMAdapter` (PR #39) and
the trend-side ``LLMExpansionCandidateProvider`` (PR #14).

Endpoint:
    POST https://{location}-aiplatform.googleapis.com/v1/projects/{project}
        /locations/{location}/publishers/google/models/{model}:predict

Request body::

    {
      "instances": [
        {"content": "<text 1>", "task_type": "RETRIEVAL_DOCUMENT"},
        {"content": "<text 2>", "task_type": "RETRIEVAL_DOCUMENT"}
      ],
      "parameters": {"autoTruncate": true, "outputDimensionality": 768}
    }

Response body::

    {
      "predictions": [
        {"embeddings": {"values": [...], "statistics": {...}}},
        ...
      ],
      "metadata": {...}
    }

**Auth** — Vertex AI does NOT support the simple ``?key=`` query param
that Gemini's ``generativelanguage.googleapis.com`` accepts. Every
request needs an ``Authorization: Bearer <oauth2-token>`` header, where
the token is issued for the
``https://www.googleapis.com/auth/cloud-platform`` scope. Tokens are
short-lived (~1 hour), so we accept a ``token_provider`` callable rather
than a static string — production uses the GCE / Cloud Run metadata
server via ``google.auth``, dev uses ``GOOGLE_OAUTH_ACCESS_TOKEN``.

**Failure isolation** — any non-200, parse error, or schema violation
escalates to :class:`MockEmbeddingAdapter` so the indexer keeps making
progress instead of bombing the whole sync run. Mirrors the Gemini
adapter's "graceful degrade to mock" contract.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import httpx

from app.services.embeddings.base import EmbeddingAdapter, EmbeddingVector
from app.services.embeddings.mock import MockEmbeddingAdapter

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "text-embedding-005"
_DEFAULT_LOCATION = "us-central1"
_DEFAULT_TASK_TYPE = "RETRIEVAL_DOCUMENT"
_DEFAULT_TIMEOUT_SECONDS = 30.0
_DEFAULT_DIMENSION = 768
_DEFAULT_MAX_BATCH = 5  # Vertex caps RETRIEVAL_DOCUMENT batches at 5/instance.


class VertexEmbeddingAPIError(RuntimeError):
    """Raised on any Vertex AI embedding transport / parse / schema failure."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class VertexAIEmbeddingAdapter(EmbeddingAdapter):
    """Live Vertex AI embedding adapter with mock fallback.

    The constructor takes plain config values (project / location /
    model / dimension) and a ``token_provider`` callable. The callable
    is invoked once per request so callers can plug in their own
    short-lived-token refresh logic without subclassing.

    ``embed`` splits oversize batches into ``max_batch_size`` chunks
    transparently — Vertex's documented limit for
    ``RETRIEVAL_DOCUMENT`` is 5 instances per request, so callers can
    pass a full source's worth of docs and trust the adapter to chunk.
    """

    def __init__(
        self,
        project_id: str,
        *,
        location: str = _DEFAULT_LOCATION,
        model: str = _DEFAULT_MODEL,
        dimension: int = _DEFAULT_DIMENSION,
        task_type: str = _DEFAULT_TASK_TYPE,
        token_provider: Callable[[], str],
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
        max_batch_size: int = _DEFAULT_MAX_BATCH,
        fallback: EmbeddingAdapter | None = None,
    ) -> None:
        if not project_id:
            raise ValueError(
                "VERTEX_PROJECT_ID is required when EMBEDDING_PROVIDER=live. "
                "Set the env var or switch to EMBEDDING_PROVIDER=mock."
            )
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        if max_batch_size <= 0:
            raise ValueError("max_batch_size must be positive")
        self._project_id = project_id
        self._location = location
        self._model = model
        self._dimension = dimension
        self._task_type = task_type
        self._token_provider = token_provider
        self._timeout = timeout
        self._max_batch_size = max_batch_size
        self._fallback = fallback or MockEmbeddingAdapter(dimension=dimension)

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: list[str]) -> list[EmbeddingVector]:
        if not texts:
            return []
        try:
            out: list[EmbeddingVector] = []
            for start in range(0, len(texts), self._max_batch_size):
                chunk = texts[start : start + self._max_batch_size]
                out.extend(self._embed_chunk(chunk))
            return out
        except VertexEmbeddingAPIError as exc:
            logger.warning(
                "vertex embed failed (%s); falling back to mock embedder",
                exc,
            )
            return self._fallback.embed(texts)

    # ------------------------------------------------------------ transport

    def _embed_chunk(self, texts: list[str]) -> list[EmbeddingVector]:
        url = (
            f"https://{self._location}-aiplatform.googleapis.com/v1/projects/"
            f"{self._project_id}/locations/{self._location}/publishers/google/"
            f"models/{self._model}:predict"
        )
        body: dict[str, Any] = {
            "instances": [{"content": t, "task_type": self._task_type} for t in texts],
            "parameters": {
                "autoTruncate": True,
                "outputDimensionality": self._dimension,
            },
        }
        token = self._token_provider()
        if not token:
            raise VertexEmbeddingAPIError("token_provider returned empty token")
        headers = {"Authorization": f"Bearer {token}"}
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(url, json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise VertexEmbeddingAPIError(f"transport error: {exc}") from exc
        if resp.status_code != 200:
            raise VertexEmbeddingAPIError(
                f"Vertex AI returned {resp.status_code}: {resp.text[:300]}",
                status_code=resp.status_code,
            )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise VertexEmbeddingAPIError(f"non-JSON Vertex AI response: {exc}") from exc
        return _parse_predictions(payload, expected_count=len(texts), dimension=self._dimension)


def _parse_predictions(
    payload: Any,
    *,
    expected_count: int,
    dimension: int,
) -> list[EmbeddingVector]:
    """Extract ``predictions[*].embeddings.values`` from a Vertex response."""
    if not isinstance(payload, dict):
        raise VertexEmbeddingAPIError("non-object Vertex AI response")
    predictions = payload.get("predictions")
    if not isinstance(predictions, list):
        raise VertexEmbeddingAPIError("predictions missing or not an array")
    if len(predictions) != expected_count:
        raise VertexEmbeddingAPIError(
            f"expected {expected_count} predictions, got {len(predictions)}"
        )
    out: list[EmbeddingVector] = []
    for i, p in enumerate(predictions):
        if not isinstance(p, dict):
            raise VertexEmbeddingAPIError(f"prediction {i} is not an object")
        emb = p.get("embeddings")
        if not isinstance(emb, dict):
            raise VertexEmbeddingAPIError(f"prediction {i} missing 'embeddings' object")
        values = emb.get("values")
        if not isinstance(values, list) or not values:
            raise VertexEmbeddingAPIError(f"prediction {i} 'embeddings.values' missing or empty")
        try:
            floats = [float(v) for v in values]
        except (TypeError, ValueError) as exc:
            raise VertexEmbeddingAPIError(
                f"prediction {i} contains non-numeric values: {exc}"
            ) from exc
        if len(floats) != dimension:
            raise VertexEmbeddingAPIError(
                f"prediction {i} has {len(floats)} dims, expected {dimension}"
            )
        out.append(EmbeddingVector(values=floats, dimension=dimension))
    return out
