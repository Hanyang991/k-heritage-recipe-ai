"""``HERITAGE_LIVE_SOURCE=gihohak`` adapter (기호유학 고문헌 통합정보시스템 / 충남대).

Sibling to:

* :class:`LiveHeritageAdapter` (장서각 / PR #33)
* :class:`LiveKoreanstudiesAdapter` (한국학자료포털 / PR #35)
* :class:`LiveNlkAdapter` (국립중앙도서관 / PR #36)

All four adapters expose the same :class:`HeritageAdapter` protocol; the
factory in ``app.services.heritage.__init__`` picks which one to
activate based on the ``HERITAGE_LIVE_SOURCE`` env knob.

Behaviour
---------
* ``search()`` calls :meth:`GihohakSearchClient.search` and converts each
  hit into a :class:`HeritageDoc` + :class:`DocumentMatch`. Match score
  uses the same rank-decay heuristic the other three adapters use (top
  hit ≈ 0.94, linear decay to 0.40) so multi-source fan-in (planned in
  todo.md §1.3.1) can compare scores across archives without
  renormalising.
* ``list_seeded()`` delegates to :class:`MockHeritageAdapter` so the seed
  pool stays consistent regardless of which live source is active.

Failure mode
------------
Any :class:`GihohakAPIError` (network failure, non-2xx response,
unparseable XML body, unexpected root element) triggers a fall-back to
the mock matcher for that single ``search()`` call. Empty result sets
are kept as-is — an empty response is genuine information, not an error.
Same resilience contract as the other three live adapters.

Authentication
--------------
None. The 기호유학 Open API is fully open (no key, no header) — same
as 장서각 and 한국학자료포털. NLK is the only source in this stack that
requires a key.

Region handling
---------------
The 기호유학 search response doesn't expose a region field, but the
materials are by definition 충청권 가문/서원 holdings. We populate
:attr:`HeritageDoc.region` with the static label ``"충청"`` so
cross-source region filters can still surface 기호유학 records when the
caller asks for 충청 (or its hanja variant). The other adapters don't
do this because their datasets span multiple regions.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from app.services.heritage.base import DocumentMatch, HeritageAdapter, HeritageDoc
from app.services.heritage.gihohak import (
    GIHOHAK_INSTITUTION_CODE,
    GihohakAPIError,
    GihohakSearchClient,
    GihohakSearchResult,
)
from app.services.heritage.mock import MockHeritageAdapter

logger = logging.getLogger(__name__)

GIHOHAK_REGION_LABEL = "충청"
"""Static region label.

Every 기호유학 record is by curation scope a 충청권 (충청도 + 한강 유역
일부) holding, so we attach a fixed region label rather than parsing it
out of each record. This makes ``region="충청"`` queries route into 기호유학
through the multi-source fan-in (planned), while still leaving region-free
queries unaffected.
"""


def _result_to_doc(result: GihohakSearchResult) -> HeritageDoc:
    """Map one live 기호유학 search row into a :class:`HeritageDoc`.

    ``mainTitle`` (한글명칭) is the canonical title; ``alternativeTitle``
    (한자명칭) is folded into the summary so prompts can still see the
    original 한자 form. The angle-bracket-separated ``classFullNm``
    hierarchy (e.g. ``서간통고류>서간류>간찰``) goes into both
    ``category`` and the summary — recipe-generate uses category for
    routing while the summary surfaces the full lineage.
    """
    summary_bits: list[str] = []
    if result.creator:
        summary_bits.append(result.creator)
    if result.alt_title and result.alt_title != result.title:
        summary_bits.append(f"한자명: {result.alt_title}")
    if result.created_raw:
        summary_bits.append(f"생성년도: {result.created_raw}")
    if result.relation_date and result.relation_date != result.created_raw:
        summary_bits.append(f"간지: {result.relation_date}")
    if result.class_full_name:
        summary_bits.append(f"분류: {result.class_full_name}")
    if result.data_type_name:
        summary_bits.append(f"유형: {result.data_type_name}")
    if result.uci:
        summary_bits.append(f"UCI: {result.uci}")
    if result.recommended:
        summary_bits.append("추천 자료")
    if result.abstract:
        summary_bits.append(result.abstract)
    summary = " · ".join(summary_bits)

    # The detail URL coming back is already absolute (e.g.
    # http://giho.cnu.ac.kr/shr/...). No normalisation needed.

    return HeritageDoc(
        external_id=result.external_id or result.title,
        title=result.title or result.external_id,
        institution=GIHOHAK_INSTITUTION_CODE,
        region=GIHOHAK_REGION_LABEL,
        period=result.period,
        category=result.class_full_name or result.data_type_name,
        year=result.year,
        original_text="",  # detail-endpoint fetch is a follow-up PR
        summary=summary,
        license="KOGL-1",  # 충남대 / 국가DB사업 의 표준 라이선스
    )


def _rank_score(rank: int, total: int) -> float:
    """Return a [0, 1] score that decays with rank.

    Identical to the 장서각 / 한국학자료포털 / NLK adapters so multi-source
    fan-in can compare scores across archives without renormalising.
    """
    if total <= 0:
        return 0.0
    if total == 1:
        return 0.94
    decay = (0.94 - 0.40) * (rank / max(1, total - 1))
    return round(0.94 - decay, 4)


class LiveGihohakAdapter(HeritageAdapter):
    """Live ``HeritageAdapter`` backed by the 기호유학 Open API.

    The mock fallback isn't only for tests — it's a production feature.
    When 기호유학 is temporarily unreachable (or returns an unexpected
    body shape) recipe-generate still grounds against the seeded
    documents instead of failing the whole request.
    """

    def __init__(
        self,
        client: GihohakSearchClient | None = None,
        *,
        fallback: HeritageAdapter | None = None,
    ) -> None:
        # 기호유학 doesn't require any auth, so unlike NLK we can construct
        # a default client when one isn't supplied — same convenience as
        # the 장서각 / 한국학자료포털 adapters.
        self._client = client or GihohakSearchClient()
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
            response = self._client.search(query=kw, page_size=max(limit, 1))
        except GihohakAPIError as exc:
            logger.warning(
                "기호유학 live search failed (keyword=%r); falling back to mock: %s",
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
        exists for protocol compliance.
        """
        return self._fallback.list_seeded()


def _apply_filters(
    results: Iterable[GihohakSearchResult],
    *,
    region: str | None,
    period: str | None,
) -> list[GihohakSearchResult]:
    """Client-side region + period filters.

    Region filter: 기호유학 records are uniformly labelled with
    :data:`GIHOHAK_REGION_LABEL` (``"충청"``). If the caller requests a
    different region we return an empty list — better than silently
    surfacing irrelevant records. Records with an unknown period are
    kept even when a period filter is requested (same over-include
    policy as the other three live adapters).
    """
    out = list(results)
    if region and region != GIHOHAK_REGION_LABEL:
        return []
    if period:
        out = [r for r in out if not r.period or r.period == period]
    return out
