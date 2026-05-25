"""Embedding adapter factory.

Mock vs live is selected by :attr:`Settings.embedding_provider`:

* ``mock`` (default) — :class:`MockEmbeddingAdapter`. No network I/O,
  deterministic across processes. Used for tests, local dev, and as
  the graceful-degrade target when a live provider is requested but
  its required credentials aren't provisioned.
* ``gemini`` — :class:`GeminiEmbeddingAdapter` calling Google AI
  Studio's ``text-embedding-004`` REST endpoint with the existing
  ``GEMINI_API_KEY`` (free tier, no new credentials). Missing key
  degrades to mock with a one-time warning, matching the LLM /
  heritage "missing key → mock fallback" contract.
* ``live`` — :class:`VertexAIEmbeddingAdapter` calling Google Vertex
  AI's publisher-model ``:predict`` endpoint with
  ``text-embedding-005``. Requires ``VERTEX_PROJECT_ID`` and an OAuth
  access token (typically from a service account or the GCE/Cloud Run
  metadata server). If either is missing, the factory transparently
  degrades to the mock embedder.

Token acquisition for ``live`` is intentionally NOT bundled here:
production code should pass a ``token_provider`` that uses
``google.auth.transport`` against the metadata server, while local
dev / CI can set ``GOOGLE_OAUTH_ACCESS_TOKEN`` to a freshly minted
token from ``gcloud auth print-access-token``. The factory reads that
env var by default so the live adapter is usable end-to-end without
extra wiring.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache

from app.config import get_settings
from app.services.embeddings.base import EmbeddingAdapter, EmbeddingVector
from app.services.embeddings.gemini import (
    GeminiEmbeddingAdapter,
    GeminiEmbeddingAPIError,
)
from app.services.embeddings.mock import MockEmbeddingAdapter
from app.services.embeddings.vertex import (
    VertexAIEmbeddingAdapter,
    VertexEmbeddingAPIError,
)

logger = logging.getLogger(__name__)

_TOKEN_ENV_VAR = "GOOGLE_OAUTH_ACCESS_TOKEN"


def _env_token_provider() -> str:
    """Default token provider — read ``GOOGLE_OAUTH_ACCESS_TOKEN``.

    Production deployments should replace this by passing a custom
    ``token_provider`` to :class:`VertexAIEmbeddingAdapter` (typically
    one that uses ``google.auth.transport.requests.Request`` against
    the metadata server to refresh short-lived service-account tokens).
    For local dev / CI ``gcloud auth print-access-token`` produces a
    suitable value.
    """
    return os.environ.get(_TOKEN_ENV_VAR, "")


@lru_cache
def get_embedding_adapter() -> EmbeddingAdapter:
    """Return the configured :class:`EmbeddingAdapter` instance.

    Same graceful-degrade contract as the heritage / LLM factories:
    if a live provider is requested but its required credentials are
    missing, return the mock embedder (with a one-time warning)
    instead of failing boot.
    """
    settings = get_settings()
    if settings.embedding_provider == "mock":
        return MockEmbeddingAdapter(dimension=settings.vertex_embedding_dimension)

    if settings.embedding_provider == "gemini":
        if not settings.gemini_api_key:
            logger.warning(
                "EMBEDDING_PROVIDER=gemini but GEMINI_API_KEY is unset; "
                "falling back to mock embedder",
            )
            return MockEmbeddingAdapter(dimension=settings.vertex_embedding_dimension)
        return GeminiEmbeddingAdapter(
            api_key=settings.gemini_api_key,
            base_url=settings.gemini_base_url,
            dimension=settings.vertex_embedding_dimension,
        )

    if not settings.vertex_project_id:
        logger.warning(
            "EMBEDDING_PROVIDER=live but VERTEX_PROJECT_ID is unset; falling back to mock embedder",
        )
        return MockEmbeddingAdapter(dimension=settings.vertex_embedding_dimension)

    if not _env_token_provider():
        logger.warning(
            "EMBEDDING_PROVIDER=live but %s is unset; falling back to mock "
            "embedder. Set %s to a freshly minted access token or pass a "
            "custom token_provider when constructing VertexAIEmbeddingAdapter.",
            _TOKEN_ENV_VAR,
            _TOKEN_ENV_VAR,
        )
        return MockEmbeddingAdapter(dimension=settings.vertex_embedding_dimension)

    return VertexAIEmbeddingAdapter(
        project_id=settings.vertex_project_id,
        location=settings.vertex_location,
        model=settings.vertex_embedding_model,
        dimension=settings.vertex_embedding_dimension,
        token_provider=_env_token_provider,
    )


__all__ = [
    "EmbeddingAdapter",
    "EmbeddingVector",
    "GeminiEmbeddingAdapter",
    "GeminiEmbeddingAPIError",
    "MockEmbeddingAdapter",
    "VertexAIEmbeddingAdapter",
    "VertexEmbeddingAPIError",
    "get_embedding_adapter",
]
