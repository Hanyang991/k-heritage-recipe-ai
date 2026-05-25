"""Hybrid heritage retrieval: keyword + semantic vector search blend.

``HybridHeritageAdapter`` wraps an existing keyword
:class:`HeritageAdapter` (typically :class:`MultiSourceHeritageAdapter`
over the four live sources) **and** a :class:`HeritageIndexer` driven
by Vertex AI Vector Search.  At query time both layers run, their
results are merged with weighted scoring, and the top-K is returned —
so recipe-generate can ground on docs that match the user's keyword
*and* on semantically related docs the keyword adapter would never
surface (e.g. "전통 음료" → 오미자 / 식혜 records that don't literally
contain "음료").

Why both? They fail on opposite ends of the recall/precision tradeoff:

* The keyword adapter (live APIs like 장서각 / 한국학자료포털 / NLK)
  has **high precision but low recall** — it finds exact title /
  abstract hits but misses synonyms, related concepts, and OCR
  variants.
* The semantic side has **high recall but variable precision** —
  it surfaces concept neighbours regardless of vocabulary, but can
  drift onto loosely related material.

Blending the two takes the best of both: documents that match
keyword *and* semantic intent rank highest, then strong single-side
hits, then weaker hits.  The blend weight is a settings knob
(``HERITAGE_HYBRID_KEYWORD_WEIGHT`` — default 0.6, so keyword
precision dominates by default but semantic recall still
contributes).

Resilience contract (matches :class:`MultiSourceHeritageAdapter`):

* Either layer failing in isolation is **not** fatal — the surviving
  layer's results pass through.  Only when **both** raise do we
  escalate to the keyword adapter's existing mock fallback so
  recipe-generate stays available.
* Empty results from both layers return ``[]`` honestly — we don't
  invent seeded matches just because the index isn't populated yet.

Index population is **not** the hybrid adapter's responsibility.
Either the operator runs a backfill job (todo.md §1.3 follow-up) or
the index stays empty in which case the semantic side contributes
nothing and the adapter degenerates to keyword-only.  Either way
recipe-generate keeps working.
"""

from __future__ import annotations

import logging

from app.services.heritage.base import DocumentMatch, HeritageAdapter, HeritageDoc
from app.services.heritage.multi_source import _normalise_title_for_dedupe
from app.services.vector_search.base import VectorIndexNotConfiguredError
from app.services.vector_search.indexer import (
    HeritageIndexer,
    vector_match_to_heritage_doc,
)

logger = logging.getLogger(__name__)


class HybridHeritageAdapter:
    """Blend a keyword :class:`HeritageAdapter` with semantic vector search.

    Drop-in replacement for any :class:`HeritageAdapter` (same
    ``search`` / ``list_seeded`` shape) so the recipe-generate router
    doesn't care which mode it's running in.  The ``keyword_weight``
    parameter controls the blend (0.0 → semantic-only, 1.0 →
    keyword-only); the complement is the semantic weight.

    Documents that appear in **both** layers' results have their
    final score computed as
    ``keyword_weight * keyword_score + semantic_weight * semantic_score``.
    Single-side documents pass through with their side's score
    scaled by the corresponding weight, so a strong keyword hit that
    the index hasn't seen still ranks above a weak both-sides hit.
    """

    def __init__(
        self,
        *,
        keyword_adapter: HeritageAdapter,
        indexer: HeritageIndexer,
        keyword_weight: float = 0.6,
        semantic_top_k: int = 20,
    ) -> None:
        if not 0.0 <= keyword_weight <= 1.0:
            raise ValueError(f"keyword_weight must be in [0, 1], got {keyword_weight}")
        if semantic_top_k <= 0:
            raise ValueError(f"semantic_top_k must be positive, got {semantic_top_k}")
        self._keyword = keyword_adapter
        self._indexer = indexer
        self._keyword_weight = keyword_weight
        self._semantic_weight = 1.0 - keyword_weight
        self._semantic_top_k = semantic_top_k

    @property
    def keyword_weight(self) -> float:
        return self._keyword_weight

    @property
    def semantic_weight(self) -> float:
        return self._semantic_weight

    def search(
        self,
        keyword: str,
        region: str | None = None,
        period: str | None = None,
        limit: int = 10,
    ) -> list[DocumentMatch]:
        """Run both layers, merge, dedupe, and return the top ``limit`` matches.

        Per-layer failures are isolated.  If both layers fail we fall
        back to the keyword adapter's ``search`` again *without* the
        exception-handling wrapper so any operationally meaningful
        error propagates (the keyword adapter itself already has a
        mock-fallback contract via :class:`MultiSourceHeritageAdapter`,
        so this path is rarely hit in practice).
        """
        keyword_matches, keyword_failed = self._run_keyword(
            keyword, region=region, period=period, limit=limit
        )
        semantic_matches, semantic_failed = self._run_semantic(
            keyword, region=region, period=period
        )

        if keyword_failed and semantic_failed:
            logger.warning(
                "hybrid heritage: both keyword and semantic layers failed "
                "for keyword=%r; falling back to keyword adapter",
                keyword,
            )
            # Last-resort: re-call keyword once more without exception
            # suppression so the underlying mock-fallback fires.
            return self._keyword.search(keyword, region=region, period=period, limit=limit)

        merged = self._merge(keyword_matches, semantic_matches)
        if not merged:
            # Both layers returned 0 (no exceptions) — return [] honestly.
            return []
        merged.sort(key=lambda m: (-m.match_score, m.document.title))
        return merged[:limit]

    def list_seeded(self) -> list[HeritageDoc]:
        """Pass-through to the underlying keyword adapter.

        The seed-listing path is used by the DB bootstrap script, which
        doesn't go through Vertex AI — keep it identical to the
        keyword-only behaviour so the DB seeds remain stable.
        """
        return self._keyword.list_seeded()

    def _run_keyword(
        self,
        keyword: str,
        *,
        region: str | None,
        period: str | None,
        limit: int,
    ) -> tuple[list[DocumentMatch], bool]:
        """Call the keyword adapter, isolating any exception.

        Returns ``(matches, failed)`` — ``failed=True`` means the call
        raised; ``failed=False`` with ``matches=[]`` means the adapter
        answered with no hits, which is genuine information (not the
        same as a failure).
        """
        try:
            matches = self._keyword.search(keyword, region=region, period=period, limit=limit)
        except Exception as exc:  # noqa: BLE001 - resilience boundary
            logger.exception(
                "hybrid heritage: keyword layer raised for keyword=%r: %s",
                keyword,
                exc,
            )
            return [], True
        return matches, False

    def _run_semantic(
        self,
        keyword: str,
        *,
        region: str | None,
        period: str | None,
    ) -> tuple[list[DocumentMatch], bool]:
        """Call the vector index, projecting :class:`VectorMatch` → :class:`DocumentMatch`.

        Region / period filters propagate via Vertex AI ``restricts``
        so the semantic side sees the same filters the keyword side
        sees.  Restricts are AND-of-ORs in Vertex AI's contract —
        adding an empty-key entry would always match nothing, so we
        only include the axes the caller actually filtered on.
        """
        restricts: dict[str, list[str]] | None = None
        if region or period:
            restricts = {}
            if region:
                restricts["region"] = [region]
            if period:
                restricts["period"] = [period]

        try:
            cross_matches = self._indexer.query_all_sources(
                keyword,
                top_k=self._semantic_top_k,
                restricts=restricts,
            )
        except VectorIndexNotConfiguredError:
            # Indexer ↔ vector-store namespace mismatch is a real config
            # bug — surface loudly to the operator rather than swallowing.
            raise
        except Exception as exc:  # noqa: BLE001 - resilience boundary
            logger.exception(
                "hybrid heritage: semantic layer raised for keyword=%r: %s",
                keyword,
                exc,
            )
            return [], True

        doc_matches = [
            DocumentMatch(
                document=vector_match_to_heritage_doc(c.namespace, c.match),
                match_score=c.match.score,
            )
            for c in cross_matches
        ]
        return doc_matches, False

    def _merge(
        self,
        keyword_matches: list[DocumentMatch],
        semantic_matches: list[DocumentMatch],
    ) -> list[DocumentMatch]:
        """Blend keyword + semantic results into a single ranked list.

        Two-pass dedupe matching :class:`MultiSourceHeritageAdapter`:

        1. Bucket by ``(institution, external_id)`` — the canonical
           identity key shared between the keyword adapter and the
           vector index (because ``datapoint_id`` is
           ``"{institution}:{external_id}"``).  For docs in both,
           combine scores with the configured weights.  Keyword
           wins ties on the underlying :class:`HeritageDoc`
           because keyword docs carry richer fields
           (``original_text``) that semantic-reconstructed docs
           lack.
        2. Bucket the remaining survivors by normalised title to
           absorb cross-source duplicates (장서각 vs NLK both
           indexing the same 의궤 record).  Higher combined score
           wins.

        Single-side hits pass through scaled by that side's weight so
        a strong keyword-only hit ranks above a weak both-sides hit
        — matching the intuition that keyword precision + index gap
        shouldn't be punished.
        """
        # Pass 1: identity key.
        by_id: dict[tuple[str, str], DocumentMatch] = {}

        for m in keyword_matches:
            key = (m.document.institution, m.document.external_id)
            by_id[key] = DocumentMatch(
                document=m.document,
                match_score=self._keyword_weight * m.match_score,
            )

        for m in semantic_matches:
            key = (m.document.institution, m.document.external_id)
            existing = by_id.get(key)
            if existing is None:
                # Semantic-only hit — keep the reconstructed doc as-is.
                by_id[key] = DocumentMatch(
                    document=m.document,
                    match_score=self._semantic_weight * m.match_score,
                )
                continue
            # Both layers fired — combine scores; keyword's richer
            # document wins on the dataclass payload.
            existing.match_score = existing.match_score + self._semantic_weight * m.match_score

        # Pass 2: normalised-title cross-source dedupe.
        by_title: dict[str, DocumentMatch] = {}
        for m in by_id.values():
            title_key = _normalise_title_for_dedupe(m.document.title)
            if not title_key:
                # Empty / punctuation-only title — keep the identity key
                # bucket as-is (already unique above).
                by_title[f"{m.document.institution}:{m.document.external_id}"] = m
                continue
            existing = by_title.get(title_key)
            if existing is None or m.match_score > existing.match_score:
                by_title[title_key] = m

        return list(by_title.values())
