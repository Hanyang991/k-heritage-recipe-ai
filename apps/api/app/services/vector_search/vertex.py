"""Vertex AI Vector Search REST adapter (``VECTOR_SEARCH_PROVIDER=live``).

Uses Vertex AI Vector Search's REST surface directly with ``httpx`` —
same pattern as :class:`VertexAIEmbeddingAdapter` and
:class:`GeminiLLMAdapter`. The heavy ``google-cloud-aiplatform`` SDK
is intentionally NOT pulled in.

Two endpoints are exercised:

* **Upsert** (write path):
  ``POST https://{location}-aiplatform.googleapis.com/v1/projects/{project}
  /locations/{location}/indexes/{index}:upsertDatapoints``

* **Find Neighbors** (read path) — runs against the deployed-index
  endpoint, NOT the index resource itself:
  ``POST https://{endpoint_host}/v1/projects/{project}/locations/{location}
  /indexEndpoints/{endpoint}:findNeighbors``

Per-source namespaces are realised as **one Vertex AI index per
source**: ``index_id`` is keyed by namespace via :class:`VectorIndexConfig`
so upsert routes to the correct backend without code changes. Read
queries hit the same per-source ``deployed_index_id`` on a shared
``IndexEndpoint`` (Vertex's recommended cost-saving topology — one
endpoint, multiple deployed indexes).

Auth: same OAuth bearer-token contract as embeddings — pass a
``token_provider`` callable. The token-acquisition logic lives in
the factory module, so subclassing isn't required.

Failure isolation: any non-200 / parse / schema failure raises
:class:`VertexVectorSearchAPIError`. The factory catches at the call
site and degrades to :class:`MockVectorSearchAdapter` for the affected
operation (write attempts are retried by the indexer's outer loop).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from app.services.vector_search.base import (
    VectorDatapoint,
    VectorIndexNotConfiguredError,
    VectorMatch,
    VectorSearchAdapter,
)

logger = logging.getLogger(__name__)

_DEFAULT_LOCATION = "us-central1"
_DEFAULT_TIMEOUT_SECONDS = 30.0
_DEFAULT_UPSERT_BATCH = 100  # Vertex AI accepts up to 1000 per request.


@dataclass(frozen=True)
class VectorIndexConfig:
    """Per-source Vertex AI Vector Search resource bundle.

    ``index_id`` is the bare numeric / string id of the
    ``projects/.../indexes/{index_id}`` resource — used for
    ``upsertDatapoints``. ``deployed_index_id`` is the
    ``deployedIndexId`` string registered on the index endpoint and
    used at query time. ``endpoint_id`` is the IndexEndpoint resource
    id; ``endpoint_host`` is the per-endpoint public domain
    (``{endpoint_id}.{location}-{project_number}.vdb.vertexai.goog``)
    that ``findNeighbors`` must be POSTed to — Vertex does not accept
    ``findNeighbors`` against the global ``aiplatform.googleapis.com``
    host.
    """

    index_id: str
    deployed_index_id: str
    endpoint_id: str
    endpoint_host: str


class VertexVectorSearchAPIError(RuntimeError):
    """Raised on any Vertex AI Vector Search transport / parse failure."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class VertexAIVectorSearchAdapter(VectorSearchAdapter):
    """Live Vertex AI Vector Search adapter.

    Constructed with a mapping ``namespace → VectorIndexConfig`` plus
    project / location / token provider. The factory builds the mapping
    from settings; tests can construct directly with a minimal map.
    """

    def __init__(
        self,
        project_id: str,
        *,
        location: str = _DEFAULT_LOCATION,
        index_configs: dict[str, VectorIndexConfig],
        token_provider: Callable[[], str],
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
        upsert_batch_size: int = _DEFAULT_UPSERT_BATCH,
    ) -> None:
        if not project_id:
            raise ValueError("VERTEX_PROJECT_ID is required when VECTOR_SEARCH_PROVIDER=live.")
        if not index_configs:
            raise ValueError("VertexAIVectorSearchAdapter requires at least one index_config")
        if upsert_batch_size <= 0:
            raise ValueError("upsert_batch_size must be positive")
        self._project_id = project_id
        self._location = location
        # Sort keys for deterministic ``known_namespaces`` output.
        self._index_configs: dict[str, VectorIndexConfig] = {
            k: index_configs[k] for k in sorted(index_configs.keys())
        }
        self._token_provider = token_provider
        self._timeout = timeout
        self._upsert_batch_size = upsert_batch_size

    def known_namespaces(self) -> list[str]:
        return list(self._index_configs.keys())

    # --------------------------------------------------------------- upsert

    def upsert(self, namespace: str, datapoints: list[VectorDatapoint]) -> None:
        if not datapoints:
            return
        config = self._require_config(namespace)
        url = (
            f"https://{self._location}-aiplatform.googleapis.com/v1/projects/"
            f"{self._project_id}/locations/{self._location}/indexes/"
            f"{config.index_id}:upsertDatapoints"
        )
        for start in range(0, len(datapoints), self._upsert_batch_size):
            chunk = datapoints[start : start + self._upsert_batch_size]
            body = {"datapoints": [_serialize_datapoint(dp) for dp in chunk]}
            self._post(url, body)

    # --------------------------------------------------------------- query

    def query(
        self,
        namespace: str,
        vector: list[float],
        *,
        top_k: int = 10,
        restricts: dict[str, list[str]] | None = None,
    ) -> list[VectorMatch]:
        if top_k <= 0:
            return []
        config = self._require_config(namespace)
        url = (
            f"https://{config.endpoint_host}/v1/projects/{self._project_id}/"
            f"locations/{self._location}/indexEndpoints/"
            f"{config.endpoint_id}:findNeighbors"
        )
        datapoint: dict[str, Any] = {"featureVector": vector}
        if restricts:
            datapoint["restricts"] = [
                {"namespace": key, "allowList": list(values)} for key, values in restricts.items()
            ]
        body = {
            "deployedIndexId": config.deployed_index_id,
            "queries": [{"datapoint": datapoint, "neighborCount": top_k}],
        }
        payload = self._post(url, body)
        return _parse_neighbors(payload)

    # --------------------------------------------------------------- helpers

    def _require_config(self, namespace: str) -> VectorIndexConfig:
        try:
            return self._index_configs[namespace]
        except KeyError as exc:
            raise VectorIndexNotConfiguredError(
                f"unknown namespace {namespace!r}; known: {list(self._index_configs.keys())!r}"
            ) from exc

    def _post(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        token = self._token_provider()
        if not token:
            raise VertexVectorSearchAPIError("token_provider returned empty token")
        headers = {"Authorization": f"Bearer {token}"}
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(url, json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise VertexVectorSearchAPIError(f"transport error: {exc}") from exc
        if resp.status_code != 200:
            raise VertexVectorSearchAPIError(
                f"Vertex AI returned {resp.status_code}: {resp.text[:300]}",
                status_code=resp.status_code,
            )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise VertexVectorSearchAPIError(f"non-JSON Vertex AI response: {exc}") from exc
        if not isinstance(payload, dict):
            raise VertexVectorSearchAPIError("non-object Vertex AI response")
        return payload


def _serialize_datapoint(dp: VectorDatapoint) -> dict[str, Any]:
    """Encode a :class:`VectorDatapoint` for ``upsertDatapoints``.

    Vertex AI's wire format nests restricts as a list of
    ``{"namespace": ..., "allowList": [...]}`` objects. Our
    in-memory representation is a flat dict for ergonomics, so this
    converts at the API boundary.
    """
    body: dict[str, Any] = {
        "datapointId": dp.datapoint_id,
        "featureVector": list(dp.values),
    }
    if dp.restricts:
        body["restricts"] = [
            {"namespace": key, "allowList": list(values)} for key, values in dp.restricts.items()
        ]
    return body


def _parse_neighbors(payload: dict[str, Any]) -> list[VectorMatch]:
    """Extract ``nearestNeighbors[0].neighbors`` from a findNeighbors response.

    Vertex AI returns ``distance`` in ``[0, 2]`` for cosine indexes (0 =
    identical, 2 = opposite). We map that to a ``[0, 1]`` similarity
    score via ``1 - distance / 2`` so the score matches the mock
    adapter's range exactly. Other distance metrics (DOT_PRODUCT,
    L2_SQUARED, etc.) are honoured but only loosely normalised — we
    clamp to ``[0, 1]`` so downstream code never sees out-of-range
    scores.
    """
    nearest = payload.get("nearestNeighbors")
    if not isinstance(nearest, list) or not nearest:
        return []
    first = nearest[0]
    if not isinstance(first, dict):
        raise VertexVectorSearchAPIError("malformed nearestNeighbors[0] in findNeighbors response")
    neighbors = first.get("neighbors")
    if not isinstance(neighbors, list):
        return []
    matches: list[VectorMatch] = []
    for i, n in enumerate(neighbors):
        if not isinstance(n, dict):
            raise VertexVectorSearchAPIError(f"neighbor {i} is not an object")
        datapoint = n.get("datapoint")
        if not isinstance(datapoint, dict):
            raise VertexVectorSearchAPIError(f"neighbor {i} missing 'datapoint' object")
        dp_id = datapoint.get("datapointId")
        if not isinstance(dp_id, str) or not dp_id:
            raise VertexVectorSearchAPIError(f"neighbor {i} missing 'datapoint.datapointId'")
        distance = n.get("distance")
        if distance is None:
            score = 0.0
        else:
            try:
                distance_f = float(distance)
            except (TypeError, ValueError) as exc:
                raise VertexVectorSearchAPIError(
                    f"neighbor {i} non-numeric distance: {exc}"
                ) from exc
            # Cosine distance is in [0, 2]; collapse to similarity in [0, 1].
            score = 1.0 - (distance_f / 2.0)
            score = max(0.0, min(1.0, score))
        matches.append(VectorMatch(datapoint_id=dp_id, score=score))
    # Vertex returns neighbours sorted nearest-first; our score is
    # similarity (higher = better), so re-sort to match the mock's
    # contract. Stable sort with ``datapoint_id`` tie-breaker for
    # deterministic test output.
    matches.sort(key=lambda m: (-m.score, m.datapoint_id))
    return matches
