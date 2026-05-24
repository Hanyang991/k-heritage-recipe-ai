"""``HERITAGE_PROVIDER=live`` adapter (currently 장서각 only).

The full Phase-3 vision (per spec §3.1 / todo.md §1.3) is a fan-in over
three open archives — 장서각, 국립민속박물관, 문화데이터광장. This module
covers the Phase-1 MVP: 장서각 only. The other two adapters land in
follow-up PRs but the routing here is structured so adding them is purely
additive — no call-site changes.

Behaviour today
---------------
* ``search()`` calls the live 장서각 ``/api/search`` endpoint and converts
  each hit into a :class:`HeritageDoc` + :class:`DocumentMatch`. The match
  score is a simple recency-weighted heuristic (top-ranked hit gets the
  highest score, position decay below) — the API itself does not return
  a numeric relevance score, so we use rank as a proxy.
* ``list_seeded()`` delegates to :class:`MockHeritageAdapter`. The seed
  script (``app.db.seed.seed_documents``) uses that to populate the dev
  DB with three curated sample documents; live mode keeps the same
  seed-time behaviour so ``/documents`` doesn't go empty.

Failure mode
------------
If the upstream 장서각 API is unreachable, the adapter logs a warning
and falls back to the mock matcher for that single ``search()`` call —
this keeps recipe generation working in production when the public API
has a brief outage (per spec §3.4 "파이프라인 중단을 방지"). Errors are
**not** swallowed silently: every fallback emits a structured warning.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from app.services.heritage.base import DocumentMatch, HeritageAdapter, HeritageDoc
from app.services.heritage.jangseogak import (
    JANGSEOGAK_INSTITUTION_CODE,
    JangseogakAPIError,
    JangseogakSearchClient,
    JangseogakSearchResult,
)
from app.services.heritage.mock import MockHeritageAdapter

logger = logging.getLogger(__name__)


def _result_to_doc(result: JangseogakSearchResult) -> HeritageDoc:
    """Map one live 장서각 search row into a :class:`HeritageDoc`.

    Fields not present in the search response are left empty rather than
    fabricated — ``original_text`` in particular comes from the document
    detail page (not the search listing) and would require a separate
    fetch + HTML parse to populate. We surface what the search endpoint
    gives us and leave full-text retrieval to a follow-up PR.
    """
    summary_bits: list[str] = []
    if result.type_category:
        summary_bits.append(result.type_category)
    if result.author:
        summary_bits.append(f"저자: {result.author}")
    if result.composition_period_raw:
        summary_bits.append(f"작성시기: {result.composition_period_raw}")
    if result.call_number:
        summary_bits.append(f"청구기호: {result.call_number}")
    summary = " · ".join(summary_bits)

    return HeritageDoc(
        external_id=result.external_id or result.title,
        title=result.title or result.external_id,
        institution=JANGSEOGAK_INSTITUTION_CODE,
        region="",  # 장서각 search API does not expose 지역
        period=result.period,
        category=result.type_category,
        year=result.year,
        original_text="",
        summary=summary,
        license="KOGL-1",
    )


def _rank_score(rank: int, total: int) -> float:
    """Return a [0, 1] score that decays with rank.

    The 장서각 API returns results in relevance order but does not expose
    a numeric score. We approximate one so downstream consumers (mock
    adapter, prompt-grounding, UI ranking display) treat live and mock
    consistently. Top hit ≈ 0.94, then linear decay to 0.40.
    """
    if total <= 0:
        return 0.0
    if total == 1:
        return 0.94
    decay = (0.94 - 0.40) * (rank / max(1, total - 1))
    return round(0.94 - decay, 4)


class LiveHeritageAdapter(HeritageAdapter):
    """Live ``HeritageAdapter`` backed by 장서각's open API.

    The mock fallback isn't just for tests — it's a real production
    feature. When the public API is temporarily down, recipe generation
    still grounds against the seeded documents instead of failing the
    whole request.
    """

    def __init__(
        self,
        client: JangseogakSearchClient | None = None,
        *,
        fallback: HeritageAdapter | None = None,
    ) -> None:
        self._client = client or JangseogakSearchClient()
        self._fallback = fallback or MockHeritageAdapter()

    def search(
        self,
        keyword: str,
        region: str | None = None,
        period: str | None = None,
        limit: int = 10,
    ) -> list[DocumentMatch]:
        kw = (keyword or "").replace("#", "").strip()
        if not kw:
            return []

        try:
            response = self._client.search(query=kw, page_unit=max(limit, 1))
        except JangseogakAPIError as exc:
            logger.warning(
                "장서각 live search failed (keyword=%r); falling back to mock: %s",
                kw,
                exc,
            )
            return self._fallback.search(keyword, region=region, period=period, limit=limit)

        if not response.results:
            # API returned a clean empty set — that is *not* an error.
            # Do not fall back to mock here; an empty result for a real
            # query is genuine information ("the archive has nothing for
            # this keyword") and the recipe-generate flow handles it.
            return []

        filtered = _apply_period_filter(response.results, period)
        ranked = list(filtered)[:limit]
        total = len(ranked)
        return [
            DocumentMatch(document=_result_to_doc(r), match_score=_rank_score(idx, total))
            for idx, r in enumerate(ranked)
        ]

    def list_seeded(self) -> list[HeritageDoc]:
        """Re-export the curated seed pool from the mock adapter.

        Live mode does not change what ``app.db.seed`` writes to the DB —
        the seed script uses :class:`MockHeritageAdapter` directly. We
        still implement this for protocol compliance and so any future
        caller that holds an ``HeritageAdapter`` reference can list the
        seed pool without caring whether mock or live is active.
        """
        return self._fallback.list_seeded()


def _apply_period_filter(
    results: Iterable[JangseogakSearchResult],
    period: str | None,
) -> list[JangseogakSearchResult]:
    """Filter results by spec-style ``period`` bucket.

    ``period=None`` passes everything through. The 장서각 API itself does
    not accept a period filter, so we filter client-side using the bucket
    derived from ``작성시기``. Results whose period bucket is unknown
    (empty string) are kept even when a filter is requested so we don't
    over-prune (the upstream record simply lacked a parseable year).
    """
    if not period:
        return list(results)
    return [r for r in results if not r.period or r.period == period]
