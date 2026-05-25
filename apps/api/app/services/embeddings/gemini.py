"""Gemini-backed :class:`EmbeddingAdapter` for ``EMBEDDING_PROVIDER=gemini``.

Google AI Studio's Generative Language API exposes a free-tier
embedding model (``text-embedding-004``) alongside the chat models we
already call from :class:`GeminiLLMAdapter` (PR #39). The same
``GEMINI_API_KEY`` authenticates both, so wiring this adapter adds
**zero new credentials** — operators get a fully-free vector-search
path (Gemini embeddings + pgvector storage) without provisioning
Vertex AI or any other GCP resource.

Endpoint shape (REST, called directly with ``httpx`` to avoid the
``google-generativeai`` SDK's grpcio + auth chain — same pattern as
``GeminiLLMAdapter``):

    POST https://generativelanguage.googleapis.com/v1beta/models/
        text-embedding-004:embedContent?key=<API_KEY>

Single-instance request body::

    {
      "model": "models/text-embedding-004",
      "content": {"parts": [{"text": "<text>"}]},
      "taskType": "RETRIEVAL_DOCUMENT",
      "outputDimensionality": 768
    }

Single-instance response body::

    {
      "embedding": {"values": [..., ..., ...]}
    }

For multi-instance requests the API also exposes ``:batchEmbedContents``
which accepts a ``requests`` array of the same shape and returns
``{"embeddings": [{"values": ...}, ...]}``. We use the batch endpoint
whenever the caller passes more than one input so the round-trip cost
stays close to single-call.

**Auth** — Gemini uses the simple ``?key=`` query-param auth (no OAuth,
no service account). We install the same ``install_httpx_key_redaction``
filter as the LLM adapter so the key never leaks into ``httpx`` access
logs.

**Failure isolation** — any non-200, parse error, or schema violation
escalates to :class:`MockEmbeddingAdapter` so the indexer keeps making
progress instead of bombing the whole sync run. Matches the Vertex
embedding adapter's graceful-degrade contract.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.services.embeddings.base import EmbeddingAdapter, EmbeddingVector
from app.services.embeddings.mock import MockEmbeddingAdapter
from app.services.trends._httpx_log_redact import (
    install_httpx_key_redaction,
    redact_key_in_url,
)

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "text-embedding-004"
_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"
_DEFAULT_TASK_TYPE = "RETRIEVAL_DOCUMENT"
_DEFAULT_TIMEOUT_SECONDS = 30.0
_DEFAULT_DIMENSION = 768
# text-embedding-004 accepts up to 100 contents per :batchEmbedContents
# call. 50 keeps individual round-trips comfortably under both the
# request-size and per-minute rate limits on the free tier (1500 RPD /
# 100 RPM as of 2025-05).
_DEFAULT_MAX_BATCH = 50

_SINGLE_PATH = "/v1beta/models/{model}:embedContent"
_BATCH_PATH = "/v1beta/models/{model}:batchEmbedContents"


class GeminiEmbeddingAPIError(RuntimeError):
    """Raised on any Gemini embeddings transport / parse / schema failure."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class GeminiEmbeddingAdapter(EmbeddingAdapter):
    """Live Gemini embedding adapter with mock fallback.

    Same ``httpx``-direct contract as :class:`GeminiLLMAdapter`. The
    free tier (Google AI Studio key) covers ~1500 requests/day at
    ~100 requests/minute — adequate for periodic batch indexing of
    heritage corpora at the scale this project deals with (4 sources
    × ~10k–100k docs).

    Batching: ``embed`` transparently splits oversize inputs into
    ``max_batch_size`` chunks and calls ``:batchEmbedContents`` for
    each chunk. A single-input ``embed`` call uses the cheaper
    ``:embedContent`` endpoint instead.
    """

    def __init__(
        self,
        api_key: str,
        *,
        model: str = _DEFAULT_MODEL,
        base_url: str = _DEFAULT_BASE_URL,
        dimension: int = _DEFAULT_DIMENSION,
        task_type: str = _DEFAULT_TASK_TYPE,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
        max_batch_size: int = _DEFAULT_MAX_BATCH,
        fallback: EmbeddingAdapter | None = None,
    ) -> None:
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY is required when EMBEDDING_PROVIDER=gemini. "
                "Set the env var or switch to EMBEDDING_PROVIDER=mock."
            )
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        if max_batch_size <= 0:
            raise ValueError("max_batch_size must be positive")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._dimension = dimension
        self._task_type = task_type
        self._timeout = timeout
        self._max_batch_size = max_batch_size
        self._fallback = fallback or MockEmbeddingAdapter(dimension=dimension)
        # Strip ``?key=...`` from httpx access logs — see PR #29.
        install_httpx_key_redaction()

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
                if len(chunk) == 1:
                    out.append(self._embed_single(chunk[0]))
                else:
                    out.extend(self._embed_batch(chunk))
            return out
        except GeminiEmbeddingAPIError as exc:
            logger.warning(
                "gemini embed failed (%s); falling back to mock embedder",
                redact_key_in_url(str(exc)),
            )
            return self._fallback.embed(texts)

    # ------------------------------------------------------------ transport

    def _embed_single(self, text: str) -> EmbeddingVector:
        url = f"{self._base_url}{_SINGLE_PATH.format(model=self._model)}"
        body: dict[str, Any] = {
            "model": f"models/{self._model}",
            "content": {"parts": [{"text": text}]},
            "taskType": self._task_type,
            "outputDimensionality": self._dimension,
        }
        payload = self._post(url, body)
        embedding = payload.get("embedding")
        if not isinstance(embedding, dict):
            raise GeminiEmbeddingAPIError("response missing 'embedding' object")
        return _parse_values(embedding.get("values"), dimension=self._dimension, index=0)

    def _embed_batch(self, texts: list[str]) -> list[EmbeddingVector]:
        url = f"{self._base_url}{_BATCH_PATH.format(model=self._model)}"
        body: dict[str, Any] = {
            "requests": [
                {
                    "model": f"models/{self._model}",
                    "content": {"parts": [{"text": t}]},
                    "taskType": self._task_type,
                    "outputDimensionality": self._dimension,
                }
                for t in texts
            ],
        }
        payload = self._post(url, body)
        embeddings = payload.get("embeddings")
        if not isinstance(embeddings, list):
            raise GeminiEmbeddingAPIError("response missing 'embeddings' array")
        if len(embeddings) != len(texts):
            raise GeminiEmbeddingAPIError(
                f"expected {len(texts)} embeddings, got {len(embeddings)}"
            )
        out: list[EmbeddingVector] = []
        for i, emb in enumerate(embeddings):
            if not isinstance(emb, dict):
                raise GeminiEmbeddingAPIError(f"embedding {i} is not an object")
            out.append(_parse_values(emb.get("values"), dimension=self._dimension, index=i))
        return out

    def _post(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(url, json=body, params={"key": self._api_key})
        except httpx.HTTPError as exc:
            raise GeminiEmbeddingAPIError(f"transport error: {exc}") from exc
        if resp.status_code != 200:
            raise GeminiEmbeddingAPIError(
                f"Gemini returned {resp.status_code}: {resp.text[:300]}",
                status_code=resp.status_code,
            )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise GeminiEmbeddingAPIError(f"non-JSON Gemini response: {exc}") from exc
        if not isinstance(payload, dict):
            raise GeminiEmbeddingAPIError("non-object Gemini response")
        return payload


def _parse_values(values: Any, *, dimension: int, index: int) -> EmbeddingVector:
    """Validate the ``values`` list and box it into an :class:`EmbeddingVector`."""
    if not isinstance(values, list) or not values:
        raise GeminiEmbeddingAPIError(f"embedding {index} 'values' missing or empty")
    try:
        floats = [float(v) for v in values]
    except (TypeError, ValueError) as exc:
        raise GeminiEmbeddingAPIError(
            f"embedding {index} contains non-numeric values: {exc}"
        ) from exc
    if len(floats) != dimension:
        raise GeminiEmbeddingAPIError(
            f"embedding {index} has {len(floats)} dims, expected {dimension}"
        )
    return EmbeddingVector(values=floats, dimension=dimension)
