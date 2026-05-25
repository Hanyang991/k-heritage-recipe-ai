"""Deterministic mock :class:`EmbeddingAdapter` for tests and local dev.

Real Vertex AI embeddings are expensive (per-token billing) and slow
(round-trip latency dominates unit-test wall time). The mock embedder
produces L2-normalised vectors derived from a hash of the input text so
the same input always maps to the same vector — both within a process
and across processes — which lets tests assert deterministic similarity
ordering without hitting the network.

Algorithm: feed the input bytes through ``hashlib.sha256`` repeatedly,
each iteration extending the digest stream. We then interpret the
stream as a sequence of little-endian ``int32``s, normalise each to the
``[-1, 1]`` range, and L2-normalise the whole vector so cosine similarity
collapses to a dot product. Output dimension defaults to 768 to match
Vertex AI ``text-embedding-005``; tests can construct a smaller mock
for speed.
"""

from __future__ import annotations

import hashlib
import math
import struct

from app.services.embeddings.base import EmbeddingAdapter, EmbeddingVector

_DEFAULT_DIMENSION = 768


class MockEmbeddingAdapter(EmbeddingAdapter):
    """Deterministic hash-based mock embedder.

    Two contracts unit tests rely on:

    * **Determinism** — ``embed([text])`` returns the same vector on
      every call, in every process, for the same ``text`` and the same
      ``dimension``.
    * **L2-normalised** — every returned vector has unit norm (modulo
      floating-point noise), so dot product == cosine similarity. This
      matches the contract Vertex AI's ``text-embedding-005`` exposes
      with ``autoTruncate=true`` and the default ``OutputDimensionality``.
    """

    def __init__(self, *, dimension: int = _DEFAULT_DIMENSION) -> None:
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: list[str]) -> list[EmbeddingVector]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> EmbeddingVector:
        # Generate ``dimension * 4`` bytes deterministically by hashing
        # the text repeatedly with a counter suffix. Each int32 becomes
        # one vector component, scaled to ``[-1, 1]``.
        needed_bytes = self._dimension * 4
        stream = bytearray()
        counter = 0
        seed = text.encode("utf-8")
        while len(stream) < needed_bytes:
            stream.extend(hashlib.sha256(seed + counter.to_bytes(8, "little")).digest())
            counter += 1
        ints = struct.unpack(f"<{self._dimension}i", bytes(stream[:needed_bytes]))
        # Scale to [-1, 1]. ``int32`` range is roughly [-2**31, 2**31).
        scale = float(1 << 31)
        raw = [v / scale for v in ints]
        norm = math.sqrt(sum(x * x for x in raw)) or 1.0
        values = [x / norm for x in raw]
        return EmbeddingVector(values=values, dimension=self._dimension)
