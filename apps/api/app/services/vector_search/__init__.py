"""Vector-search adapter factory.

Mock vs Postgres vs Vertex is selected by
:attr:`Settings.vector_search_provider`:

* ``mock`` (default) — :class:`MockVectorSearchAdapter`. No network
  I/O, deterministic. Used for tests, local dev, and as the
  graceful-degrade target when ``live`` / ``pgvector`` are requested
  but their backing resources aren't available.
* ``pgvector`` — :class:`PgVectorSearchAdapter` storing embeddings
  in the project's existing Postgres database (no new infrastructure
  required). The **free** path — use this alongside
  ``EMBEDDING_PROVIDER=gemini`` for a zero-cost hybrid retrieval
  stack. See ``app/services/vector_search/pgvector.py``.
* ``live`` — :class:`VertexAIVectorSearchAdapter` using the REST
  endpoints documented in
  :mod:`app.services.vector_search.vertex`. Each source maps to its
  own Vertex AI index (see :class:`VectorIndexConfig`), so the
  per-source namespace contract is preserved end-to-end.

Configuration is settings-driven via
``VERTEX_VECTOR_NAMESPACES`` (comma-separated source names) and the
following per-namespace env vars:

    VERTEX_VECTOR_INDEX_ID_<NAMESPACE>            (index resource id)
    VERTEX_VECTOR_DEPLOYED_INDEX_ID_<NAMESPACE>   (deployedIndexId)
    VERTEX_VECTOR_INDEX_ENDPOINT_ID_<NAMESPACE>   (endpoint resource id)
    VERTEX_VECTOR_INDEX_ENDPOINT_HOST_<NAMESPACE> (endpoint public domain)

If any namespace is missing **any** of those four values, it is
skipped at boot with a warning. If every namespace is filtered out
the factory falls back to the mock adapter so recipe-generate stays
available.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache

from app.config import Settings, get_settings
from app.services.vector_search.base import (
    VectorDatapoint,
    VectorIndexNotConfiguredError,
    VectorMatch,
    VectorSearchAdapter,
)
from app.services.vector_search.indexer import (
    CrossSourceMatch,
    HeritageIndexer,
    IndexResult,
    heritage_doc_id,
    heritage_doc_metadata,
    heritage_doc_restricts,
    heritage_doc_text,
    vector_match_to_heritage_doc,
)
from app.services.vector_search.mock import MockVectorSearchAdapter
from app.services.vector_search.pgvector import PgVectorSearchAdapter
from app.services.vector_search.vertex import (
    VectorIndexConfig,
    VertexAIVectorSearchAdapter,
    VertexVectorSearchAPIError,
)

logger = logging.getLogger(__name__)

_TOKEN_ENV_VAR = "GOOGLE_OAUTH_ACCESS_TOKEN"


def _env_token_provider() -> str:
    return os.environ.get(_TOKEN_ENV_VAR, "")


def _resolve_index_configs(settings: Settings) -> dict[str, VectorIndexConfig]:
    """Resolve per-namespace :class:`VectorIndexConfig` from env vars.

    Namespaces missing any of the four required env vars are dropped
    with a warning — operators see the missing-var name in the log so
    fixing the config is straightforward.
    """
    configs: dict[str, VectorIndexConfig] = {}
    for namespace in settings.vertex_vector_namespaces_list:
        upper = namespace.upper()
        index_id = os.environ.get(f"VERTEX_VECTOR_INDEX_ID_{upper}", "")
        deployed = os.environ.get(f"VERTEX_VECTOR_DEPLOYED_INDEX_ID_{upper}", "")
        endpoint_id = os.environ.get(f"VERTEX_VECTOR_INDEX_ENDPOINT_ID_{upper}", "")
        endpoint_host = os.environ.get(f"VERTEX_VECTOR_INDEX_ENDPOINT_HOST_{upper}", "")
        missing = [
            name
            for name, value in (
                (f"VERTEX_VECTOR_INDEX_ID_{upper}", index_id),
                (f"VERTEX_VECTOR_DEPLOYED_INDEX_ID_{upper}", deployed),
                (f"VERTEX_VECTOR_INDEX_ENDPOINT_ID_{upper}", endpoint_id),
                (f"VERTEX_VECTOR_INDEX_ENDPOINT_HOST_{upper}", endpoint_host),
            )
            if not value
        ]
        if missing:
            logger.warning(
                "vector_search: namespace %r missing env vars %r; skipping",
                namespace,
                missing,
            )
            continue
        configs[namespace] = VectorIndexConfig(
            index_id=index_id,
            deployed_index_id=deployed,
            endpoint_id=endpoint_id,
            endpoint_host=endpoint_host,
        )
    return configs


@lru_cache
def get_vector_search_adapter() -> VectorSearchAdapter:
    """Return the configured :class:`VectorSearchAdapter` instance.

    Graceful-degrade contract: ``live`` is requested but cannot be
    fully configured → fall back to the mock adapter populated with
    the declared namespace list (so the indexer + recipe-generate
    surface still behave correctly during local development without
    GCP credentials).
    """
    settings = get_settings()
    namespaces = settings.vertex_vector_namespaces_list
    if not namespaces:
        # Defensive: should never happen given the default settings,
        # but keeps the mock adapter constructor's "at least one
        # namespace" invariant intact under aggressive overrides.
        namespaces = ["jangseogak"]

    if settings.vector_search_provider == "mock":
        return MockVectorSearchAdapter(namespaces=namespaces)

    if settings.vector_search_provider == "pgvector":
        # Import here to avoid pulling SQLAlchemy session machinery into
        # the import graph when the project is configured with
        # ``VECTOR_SEARCH_PROVIDER=mock`` (e.g. tests that don't touch DB).
        from app.db.session import SessionLocal

        return PgVectorSearchAdapter(
            session_factory=SessionLocal,
            namespaces=namespaces,
        )

    if not settings.vertex_project_id:
        logger.warning(
            "VECTOR_SEARCH_PROVIDER=live but VERTEX_PROJECT_ID is unset; "
            "falling back to mock vector store",
        )
        return MockVectorSearchAdapter(namespaces=namespaces)

    if not _env_token_provider():
        logger.warning(
            "VECTOR_SEARCH_PROVIDER=live but %s is unset; falling back to mock vector store",
            _TOKEN_ENV_VAR,
        )
        return MockVectorSearchAdapter(namespaces=namespaces)

    configs = _resolve_index_configs(settings)
    if not configs:
        logger.warning(
            "VECTOR_SEARCH_PROVIDER=live but no namespace has a complete "
            "VERTEX_VECTOR_INDEX_* env-var bundle; falling back to mock "
            "vector store",
        )
        return MockVectorSearchAdapter(namespaces=namespaces)

    return VertexAIVectorSearchAdapter(
        project_id=settings.vertex_project_id,
        location=settings.vertex_location,
        index_configs=configs,
        token_provider=_env_token_provider,
    )


__all__ = [
    "CrossSourceMatch",
    "HeritageIndexer",
    "IndexResult",
    "MockVectorSearchAdapter",
    "PgVectorSearchAdapter",
    "VectorDatapoint",
    "VectorIndexConfig",
    "VectorIndexNotConfiguredError",
    "VectorMatch",
    "VectorSearchAdapter",
    "VertexAIVectorSearchAdapter",
    "VertexVectorSearchAPIError",
    "get_vector_search_adapter",
    "heritage_doc_id",
    "heritage_doc_metadata",
    "heritage_doc_restricts",
    "heritage_doc_text",
    "vector_match_to_heritage_doc",
]
