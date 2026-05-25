"""Embedding adapter contract.

Embeddings turn a ``HeritageDoc`` (or any free-form text) into a fixed-
length numeric vector that ``VectorSearchAdapter`` can index and query.

Two providers exist behind this protocol (selected by
:attr:`Settings.embedding_provider`):

* ``mock`` — deterministic hash-based embedder for tests / dev. Outputs
  L2-normalised vectors of configurable dimension so the same input
  text always maps to the same vector across processes. No network I/O.
* ``live`` — :class:`VertexAIEmbeddingAdapter` calling Google Vertex AI
  ``text-embedding-005`` (or any compatible Vertex publisher model)
  over the REST surface. Same ``httpx``-direct pattern as
  :class:`GeminiLLMAdapter` so we avoid pulling in the heavy
  ``google-cloud-aiplatform`` SDK.

The protocol intentionally returns a list of vectors (one per input)
even when called with a single string, because Vertex AI's
``:predict`` endpoint batches up to N instances per request and we want
that capability surfaced at the adapter layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class EmbeddingVector:
    """One embedding result paired with the dimension of the vector.

    ``values`` is a python ``list[float]`` so callers can JSON-encode it
    directly into Vertex AI Vector Search ``upsertDatapoints`` payloads
    without going through numpy. ``dimension`` is exposed separately so
    the indexer can sanity-check shapes before sending an upsert that
    would otherwise be rejected by the index's configured ``dimensions``.
    """

    values: list[float]
    dimension: int


class EmbeddingAdapter(Protocol):
    """Protocol for text → vector embedding providers."""

    @property
    def dimension(self) -> int:
        """The fixed dimensionality of every returned vector.

        This must match the ``dimensions`` configured on the Vertex AI
        Vector Search index — Vertex rejects upserts where the datapoint
        vector length differs from the index dimensions.
        """

    def embed(self, texts: list[str]) -> list[EmbeddingVector]:
        """Embed a batch of input strings.

        Implementations MUST return one :class:`EmbeddingVector` per
        input, in the same order. Empty / whitespace-only strings are
        accepted and produce a zero / fallback vector (provider-specific)
        — callers should filter upstream when this matters.
        """
