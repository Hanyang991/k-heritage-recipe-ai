"""``HERITAGE_LIVE_SOURCE=nlk`` adapter (국립중앙도서관 / nl.go.kr).

Sibling to :class:`LiveHeritageAdapter` (장서각 / PR #33) and
:class:`LiveKoreanstudiesAdapter` (한국학자료포털 / PR #35). All three
adapters expose the same :class:`HeritageAdapter` protocol; the factory
in ``app.services.heritage.__init__`` picks which one to activate based
on the ``HERITAGE_LIVE_SOURCE`` env knob.

Behaviour
---------
* ``search()`` calls :meth:`NlkSearchClient.search` and converts each hit
  into a :class:`HeritageDoc` + :class:`DocumentMatch`. Match score uses
  the same rank-decay heuristic the 장서각 / 한국학자료포털 adapters use
  (top hit ≈ 0.94, linear decay to 0.40) so multi-source fan-in (planned
  in todo.md §1.3.1) can compare scores across archives without
  renormalising.
* ``list_seeded()`` delegates to :class:`MockHeritageAdapter` so the seed
  pool stays consistent regardless of which live source is active.

Failure mode
------------
Any :class:`NlkAPIError` (network failure, non-2xx response, upstream
``<error_code>`` envelope, unparseable XML body) triggers a fall-back to
the mock matcher for that single ``search()`` call. Empty result sets
are kept as-is — an empty response is genuine information, not an error.
This is the same resilience contract as the 장서각 / 한국학자료포털
adapters.

Authentication
--------------
NLK is the first source in this stack that *requires* an API key
(장서각 and 한국학자료포털 are fully open). When ``NLK_API_KEY`` is
unset the factory returns the mock adapter directly (see
``app/services/heritage/__init__.py``) — this adapter assumes the key
has already been validated by the factory.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from app.services.heritage.base import DocumentMatch, HeritageAdapter, HeritageDoc
from app.services.heritage.mock import MockHeritageAdapter
from app.services.heritage.nlk import (
    NLK_INSTITUTION_CODE,
    NlkAPIError,
    NlkSearchClient,
    NlkSearchResult,
)

logger = logging.getLogger(__name__)


def _result_to_doc(result: NlkSearchResult) -> HeritageDoc:
    """Map one live NLK search row into a :class:`HeritageDoc`.

    NLK doesn't expose a region field in the search response (unlike
    한국학자료포털's ``작성지역 @현재주소``), so :attr:`HeritageDoc.region`
    is left blank. Cross-source ranking can still filter by region using
    the seeded metadata; recipe-generate's prompt grounding doesn't
    require it.

    ``type_name`` (e.g. "고문헌" / "도서") goes into ``category``. KDC
    classification (``kdc_name``: 동양서분류기호 대분류 명칭) is folded
    into the summary alongside author, publisher, and 발행년도 so the
    prompt has rich grounding context.

    License mapping: NLK ``lic_yn`` codes are facility-access flags
    (``L``: 국립중앙도서관 무료, ``Y``: 협약공공도서관 무료, etc.) — they
    aren't reuse licenses. We surface ``lic_text`` in the summary for
    transparency but flag :attr:`HeritageDoc.license` as ``"KOGL-1"`` since
    NLK Open API service terms grant KOGL-1 reuse for the metadata itself.
    """
    summary_bits: list[str] = []
    if result.author:
        summary_bits.append(result.author)
    if result.publisher:
        summary_bits.append(result.publisher)
    if result.pub_year_raw:
        summary_bits.append(f"발행: {result.pub_year_raw}")
    if result.kdc_name:
        summary_bits.append(f"분류: {result.kdc_name}")
    if result.call_number:
        summary_bits.append(f"청구기호: {result.call_number}")
    if result.isbn:
        summary_bits.append(f"ISBN: {result.isbn}")
    if result.has_original_text and result.original_text_url:
        summary_bits.append("원문 보기 가능")
    if result.license_text:
        summary_bits.append(f"이용방법: {result.license_text}")
    summary = " · ".join(summary_bits)

    return HeritageDoc(
        external_id=result.external_id or result.title,
        title=result.title or result.external_id,
        institution=NLK_INSTITUTION_CODE,
        region="",  # NLK search response has no region field
        period=result.period,
        category=result.type_name,
        year=result.year,
        original_text="",  # full-text retrieval is a follow-up PR
        summary=summary,
        license="KOGL-1",
    )


def _rank_score(rank: int, total: int) -> float:
    """Return a [0, 1] score that decays with rank.

    Identical to the 장서각 / 한국학자료포털 adapters so multi-source
    fan-in can compare scores across archives without renormalising.
    """
    if total <= 0:
        return 0.0
    if total == 1:
        return 0.94
    decay = (0.94 - 0.40) * (rank / max(1, total - 1))
    return round(0.94 - decay, 4)


class LiveNlkAdapter(HeritageAdapter):
    """Live ``HeritageAdapter`` backed by the 국립중앙도서관 open API.

    The mock fallback isn't only for tests — it's a production feature.
    When NLK is temporarily unreachable (or returns an upstream error
    envelope) recipe-generate still grounds against the seeded documents
    instead of failing the whole request.
    """

    def __init__(
        self,
        client: NlkSearchClient,
        *,
        fallback: HeritageAdapter | None = None,
    ) -> None:
        # NLK requires an API key, so unlike the other two adapters we
        # don't construct a default client — the factory is responsible
        # for passing a configured one (or returning mock when the key
        # isn't set).
        self._client = client
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
        except NlkAPIError as exc:
            logger.warning(
                "NLK live search failed (keyword=%r, error_code=%s); falling back to mock: %s",
                kw,
                exc.error_code,
                exc,
            )
            return self._fallback.search(keyword, region=region, period=period, limit=limit)

        if not response.results:
            return []

        filtered = _apply_filters(response.results, period=period)
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
    results: Iterable[NlkSearchResult],
    *,
    period: str | None,
) -> list[NlkSearchResult]:
    """Client-side period filter.

    Region filtering is intentionally a no-op here because NLK's search
    response doesn't include a region field — the only reliable way to
    region-filter NLK records is to look at ``call_no`` prefixes, which
    is too archive-specific to be useful as a generic predicate. Records
    whose period bucket is unknown (empty string) are kept even when a
    filter is requested — same over-include policy as the other adapters.
    """
    out = list(results)
    if period:
        out = [r for r in out if not r.period or r.period == period]
    return out
