"""``HERITAGE_LIVE_SOURCE=koreanstudies`` adapter (한국학자료포털 / kostma.aks.ac.kr).

Sibling to :class:`LiveHeritageAdapter` (장서각 / PR #33). Both adapters
expose the same :class:`HeritageAdapter` protocol; the factory in
``app.services.heritage.__init__`` picks which one to activate based on
the ``HERITAGE_LIVE_SOURCE`` env knob.

Behaviour
---------
* ``search()`` calls ``KoreanstudiesSearchClient.search`` and converts each
  hit into a :class:`HeritageDoc` + :class:`DocumentMatch`. Match score is
  the same rank-decay heuristic the 장서각 adapter uses (top hit ≈ 0.94,
  linear decay to 0.40) — the kostma API also returns results in
  relevance order with no exposed numeric score, so the same approximation
  applies.
* ``list_seeded()`` delegates to :class:`MockHeritageAdapter` so the seed
  pool stays consistent regardless of which live source is active.

Failure mode
------------
Any :class:`KoreanstudiesAPIError` (network failure, non-2xx response,
unparseable XML body) triggers a fall-back to the mock matcher for that
single ``search()`` call. Empty result sets are kept as-is — an empty
response is genuine information ("the archive has nothing for this
keyword"), not an error. This is the same resilience contract as the
장서각 adapter (see ``live.py`` docstring).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from app.services.heritage.base import DocumentMatch, HeritageAdapter, HeritageDoc
from app.services.heritage.koreanstudies import (
    KOREANSTUDIES_INSTITUTION_CODE,
    KoreanstudiesAPIError,
    KoreanstudiesSearchClient,
    KoreanstudiesSearchResult,
)
from app.services.heritage.mock import MockHeritageAdapter

logger = logging.getLogger(__name__)


def _result_to_doc(result: KoreanstudiesSearchResult) -> HeritageDoc:
    """Map one live 한국학자료포털 search row into a :class:`HeritageDoc`.

    Region is populated from ``작성지역 @현재주소`` when available — this is
    a richer signal than 장서각 (which doesn't expose 지역 in its search
    response). When 현재주소 is absent we fall back to the historical
    placename (e.g. "한성") rather than leaving it blank.

    Category is the 형식분류 string ("고문서-치부기록류-발기"); the more
    domain-flavoured 내용분류 ("국왕/왕실-의례-발기") is folded into the
    summary so prompt-grounding gets both signals.
    """
    summary_bits: list[str] = []
    if result.content_category:
        summary_bits.append(result.content_category)
    if result.composition_period_raw:
        summary_bits.append(f"작성시기: {result.composition_period_raw}")
    if result.region_historical and result.region_historical != result.region_modern:
        summary_bits.append(f"고지명: {result.region_historical}")
    if result.summary:
        summary_bits.append(result.summary)
    summary = " · ".join(summary_bits)

    return HeritageDoc(
        external_id=result.external_id or result.title,
        title=result.title or result.external_id,
        institution=KOREANSTUDIES_INSTITUTION_CODE,
        region=result.region_modern or result.region_historical,
        period=result.period,
        category=result.type_category,
        year=result.year,
        original_text="",  # detail-page text retrieval is a follow-up PR
        summary=summary,
        license="KOGL-1",
    )


def _rank_score(rank: int, total: int) -> float:
    """Return a [0, 1] score that decays with rank.

    Identical to the 장서각 adapter so multi-source fan-in (planned in
    todo.md §1.3.1) can compare scores across archives without renormalising.
    """
    if total <= 0:
        return 0.0
    if total == 1:
        return 0.94
    decay = (0.94 - 0.40) * (rank / max(1, total - 1))
    return round(0.94 - decay, 4)


class LiveKoreanstudiesAdapter(HeritageAdapter):
    """Live ``HeritageAdapter`` backed by the 한국학자료포털 open API.

    The mock fallback isn't only for tests — it's a production feature.
    When the upstream kostma host is temporarily unreachable, recipe-
    generate still grounds against the seeded documents instead of
    failing the whole request.
    """

    def __init__(
        self,
        client: KoreanstudiesSearchClient | None = None,
        *,
        fallback: HeritageAdapter | None = None,
    ) -> None:
        self._client = client or KoreanstudiesSearchClient()
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
            response = self._client.search(query=kw, ipp=max(limit, 1))
        except KoreanstudiesAPIError as exc:
            logger.warning(
                "한국학자료포털 live search failed (keyword=%r); falling back to mock: %s",
                kw,
                exc,
            )
            return self._fallback.search(keyword, region=region, period=period, limit=limit)

        if not response.results:
            return []

        filtered = _apply_filters(response.results, region=region, period=period)
        ranked = list(filtered)[:limit]
        total = len(ranked)
        return [
            DocumentMatch(document=_result_to_doc(r), match_score=_rank_score(idx, total))
            for idx, r in enumerate(ranked)
        ]

    def list_seeded(self) -> list[HeritageDoc]:
        """Re-export the curated seed pool from the mock adapter.

        Live mode doesn't change ``app.db.seed``'s behaviour — the seed
        script uses :class:`MockHeritageAdapter` directly. This method
        exists for protocol compliance and so any future caller that
        holds an ``HeritageAdapter`` reference can list the seed pool
        without caring which live source is active.
        """
        return self._fallback.list_seeded()


def _apply_filters(
    results: Iterable[KoreanstudiesSearchResult],
    *,
    region: str | None,
    period: str | None,
) -> list[KoreanstudiesSearchResult]:
    """Client-side region + period filter.

    The kostma API supports field-scoped searches via ``subject`` / ``date``
    sub-query parameters, but those switch the API into single-field mode
    and drop the cross-field signal we want from the default ``query``
    surface. Filtering client-side keeps the broad recall and lets us
    treat region/period as additive without sacrificing cross-field
    matches.

    Records whose region or period bucket is unknown (empty string) are
    kept even when a filter is requested — we'd rather over-include than
    silently exclude a record because the archive metadata was sparse.
    """
    out = list(results)
    if region:
        out = [
            r
            for r in out
            if not (r.region_modern or r.region_historical)
            or region in r.region_modern
            or region in r.region_historical
        ]
    if period:
        out = [r for r in out if not r.period or r.period == period]
    return out
