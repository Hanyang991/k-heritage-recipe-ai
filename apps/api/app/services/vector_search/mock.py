"""In-memory mock :class:`VectorSearchAdapter` for tests and local dev.

Stores datapoints in a ``dict[namespace, dict[datapoint_id, VectorDatapoint]]``
and computes cosine similarity by brute force at query time. Two design
choices worth calling out:

1. **Dict keyed by ``datapoint_id``** — guarantees upsert idempotency
   (re-inserting the same id replaces the value), matching Vertex AI's
   ``upsertDatapoints`` semantics.
2. **Stable namespace registration** — namespaces must be declared at
   construction time. Querying an unknown namespace raises
   :class:`VectorIndexNotConfiguredError` rather than silently returning
   an empty list, so callers catch mis-configured sources at request
   time instead of during a much later debugging session.
"""

from __future__ import annotations

import math
from collections import OrderedDict

from app.services.vector_search.base import (
    VectorDatapoint,
    VectorIndexNotConfiguredError,
    VectorMatch,
    VectorSearchAdapter,
)


class MockVectorSearchAdapter(VectorSearchAdapter):
    """Brute-force cosine-similarity vector index keyed by namespace."""

    def __init__(self, namespaces: list[str]) -> None:
        if not namespaces:
            raise ValueError("MockVectorSearchAdapter requires at least one namespace")
        # ``OrderedDict`` so ``known_namespaces`` returns insertion order
        # — tests rely on this for deterministic enumeration.
        self._store: OrderedDict[str, dict[str, VectorDatapoint]] = OrderedDict(
            (ns, {}) for ns in namespaces
        )

    def known_namespaces(self) -> list[str]:
        return list(self._store.keys())

    def upsert(self, namespace: str, datapoints: list[VectorDatapoint]) -> None:
        ns_store = self._require_namespace(namespace)
        for dp in datapoints:
            ns_store[dp.datapoint_id] = dp

    def query(
        self,
        namespace: str,
        vector: list[float],
        *,
        top_k: int = 10,
        restricts: dict[str, list[str]] | None = None,
    ) -> list[VectorMatch]:
        ns_store = self._require_namespace(namespace)
        if top_k <= 0:
            return []
        results: list[VectorMatch] = []
        for dp in ns_store.values():
            if not _matches_restricts(dp, restricts):
                continue
            score = _cosine_similarity(vector, dp.values)
            # Clamp to [0, 1] — float arithmetic can push a perfect
            # match marginally above 1.0 which surprises downstream
            # code that asserts score ranges.
            if score > 1.0:
                score = 1.0
            elif score < 0.0:
                score = 0.0
            results.append(
                VectorMatch(
                    datapoint_id=dp.datapoint_id,
                    score=score,
                    metadata=dict(dp.metadata),
                )
            )
        # Stable sort: highest score first, ties broken by datapoint_id
        # for deterministic test output.
        results.sort(key=lambda m: (-m.score, m.datapoint_id))
        return results[:top_k]

    def _require_namespace(self, namespace: str) -> dict[str, VectorDatapoint]:
        try:
            return self._store[namespace]
        except KeyError as exc:
            raise VectorIndexNotConfiguredError(
                f"unknown namespace {namespace!r}; known: {list(self._store.keys())!r}"
            ) from exc


def _matches_restricts(
    dp: VectorDatapoint,
    restricts: dict[str, list[str]] | None,
) -> bool:
    """Vertex-AI-compatible AND-of-ORs restrict matching.

    Vertex AI Vector Search's ``restricts`` semantics: a datapoint
    passes when, for **every** filter key in the query, the
    datapoint's allow-list under that key shares at least one value
    with the query's allow-list. Missing keys on the datapoint never
    match. Empty query restricts (``None`` or ``{}``) match everything.
    """
    if not restricts:
        return True
    for key, allowed in restricts.items():
        dp_values = dp.restricts.get(key)
        if not dp_values:
            return False
        if not set(dp_values).intersection(allowed):
            return False
    return True


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        # Guard against caller mistakes — Vertex AI rejects mis-sized
        # vectors at upsert time; the mock matches that contract by
        # surfacing the bug as a clear ValueError instead of silently
        # truncating one side.
        raise ValueError(f"vector dimension mismatch: {len(a)} vs {len(b)}")
    if not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
