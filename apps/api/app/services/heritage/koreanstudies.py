"""한국학자료포털 (한국학자료센터) Open API client.

Endpoint (verified live 2026-05): ``GET http://kostma.aks.ac.kr/OpenAPI/request.aspx``
Documentation: https://kostma.aks.ac.kr/OpenAPI/OpenAPI.aspx?hl=ko-KR

Why this source
---------------
This is the sister portal to 장서각 (PR #33) run by the same organisation
(한국학중앙연구원). 장서각 covers the royal-archive (왕실) materials;
이 포털은 전국 각 권역에서 수집된 민간·지역 고문헌까지 폭넓게 다룬다.
todo.md §1.3.1 documents the broader rationale.

Surface (live-verified)
-----------------------
* Path: ``/OpenAPI/request.aspx`` (no API key — fully open like 장서각)
* Parameters:
    - ``query`` (str, required for full-text): cross-field search over
      ``uci`` / ``subject`` / ``creator`` / ``publisher``
    - field-scoped sub-query (any of these overrides ``query``):
      ``uci`` / ``title`` / ``subject`` / ``publisher`` / ``date``
    - ``page`` (int, default 1)
    - ``ipp`` (int, default 10) — items per page
    - ``detail`` (int, 0/1/2): ``0`` → uci+title+url, ``1`` → +기본정보,
      ``2`` → +안내정보. We default to ``1`` to populate 분류 / 작성지역 /
      작성시기 fields in :class:`HeritageDoc`.

Response shape (live-verified)
------------------------------
Every result is XML with Korean tag names. With ``detail=1`` we get::

    <ksm>
      <info>
        <total>5</total>
        <page>1</page>
        <ipp>10</ipp>
      </info>
      <items>
        <item>
          <uci>G002+AKS+KSM-...</uci>
          <title>갑술년 음식 발기(飮食件記)</title>
          <기본정보 UCI="...">
            <분류>
              <분류명 종류="형식분류">고문서-치부기록류-발기</분류명>
              <분류명 종류="내용분류">국왕/왕실-의례-발기</분류명>
            </분류>
            <자료명>갑술년 음식 발기(飮食件記)</자료명>
            <작성지역 현재주소="서울특별시" 고지명ID="DYD_...">한성</작성지역>
            <작성시기 정보원표기="1874(고종 11)" 월일="" .../>
            <비고>출판정보 : 『고문서집성 12』(한국정신문화연구원, 1994)</비고>
          </기본정보>
          <url>http://kostma.aks.ac.kr/inspection/insDirView.aspx?dataUCI=...</url>
        </item>
      </items>
    </ksm>

The 장서각 adapter handled JSON; this one handles XML. Both end up as
:class:`HeritageDoc` instances upstream, so the recipe-generate pipeline
doesn't care which archive the document came from.

Failure mode
------------
:class:`KoreanstudiesAPIError` is raised for any non-2xx response, network
transport error, or unparseable XML body. Callers (the live adapter) wrap
this to fall back to the mock matcher so recipe-generate keeps working
during transient outages — consistent with the 장서각 pattern.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from xml.etree import ElementTree as ET

import httpx

logger = logging.getLogger(__name__)

KOREANSTUDIES_DEFAULT_BASE_URL = "https://kostma.aks.ac.kr"
KOREANSTUDIES_INSTITUTION_CODE = "koreanstudies"
"""Stable institution identifier used in ``HeritageDoc.institution``."""

_SEARCH_PATH = "/OpenAPI/request.aspx"
_DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_DEFAULT_IPP = 20
_MAX_IPP = 100  # not formally documented; 100 is a safe ceiling.

# 4-digit Common-Era year. Identical pattern to 장서각's parser so both
# adapters bucket records into the same period boundaries.
_YEAR_RE = re.compile(r"(\d{4})")

_PERIOD_LATE_JOSEON_START = 1593  # 임진왜란 후
_PERIOD_MODERN_START = 1897  # 대한제국 선포


class KoreanstudiesAPIError(Exception):
    """Raised when the 한국학자료포털 API fails or returns an unparseable body."""


@dataclass(frozen=True)
class KoreanstudiesSearchResult:
    """One row from a 한국학자료포털 ``/OpenAPI/request.aspx`` response, normalised."""

    external_id: str  # uci (full namespaced identifier)
    title: str  # 자료명
    detail_url: str  # human-readable viewer URL
    type_category: str  # 형식분류 (e.g. "고문서-치부기록류-발기")
    content_category: str  # 내용분류 (e.g. "국왕/왕실-의례-발기")
    region_modern: str  # 작성지역 @현재주소 (e.g. "서울특별시")
    region_historical: str  # 작성지역 text content (e.g. "한성")
    composition_period_raw: str  # 작성시기 @정보원표기 (e.g. "1874(고종 11)")
    year: int | None
    period: str  # 조선전기 / 조선후기 / 근대 / "" if unknown
    summary: str  # 비고 + 안내정보 표제어/내용 (when detail=2)


@dataclass(frozen=True)
class KoreanstudiesSearchResponse:
    total_count: int
    page: int
    ipp: int
    results: tuple[KoreanstudiesSearchResult, ...]


def derive_year_and_period(raw: str) -> tuple[int | None, str]:
    """Parse a ``작성시기`` style string into (year, period_bucket).

    Returns ``(None, "")`` when no 4-digit year can be extracted. Boundaries
    match the 장서각 parser so blended search results sort consistently.
    """
    if not raw:
        return None, ""
    match = _YEAR_RE.search(raw)
    if not match:
        return None, ""
    year = int(match.group(1))
    if year < _PERIOD_LATE_JOSEON_START:
        period = "조선전기"
    elif year < _PERIOD_MODERN_START:
        period = "조선후기"
    else:
        period = "근대"
    return year, period


class KoreanstudiesSearchClient:
    """Thin wrapper over ``GET /OpenAPI/request.aspx``.

    Stateless beyond config (base URL, timeout). All network failures,
    non-2xx responses, and unparseable bodies normalise to
    :class:`KoreanstudiesAPIError` — callers don't have to distinguish
    ``httpx.ConnectError``, ``httpx.ReadTimeout``, XML parse failures, or
    HTTP 5xx.
    """

    def __init__(
        self,
        base_url: str = KOREANSTUDIES_DEFAULT_BASE_URL,
        timeout: httpx.Timeout = _DEFAULT_TIMEOUT,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def search(
        self,
        query: str,
        *,
        ipp: int = _DEFAULT_IPP,
        page: int = 1,
        detail: int = 1,
    ) -> KoreanstudiesSearchResponse:
        """Run a search and return the parsed response.

        :param query: required search keyword (현대어 or 한자). Sent as the
            cross-field ``query`` param.
        :param ipp: items per page (default 20, capped at 100)
        :param page: 1-based page number (default 1)
        :param detail: 0 (id+title+url only), 1 (+기본정보), 2 (+안내정보).
            Default 1 gives us 분류 / 지역 / 시기 / 비고 without paying for
            the heavier 안내정보 payload.
        """
        if not query:
            raise ValueError("query is required")
        if ipp > _MAX_IPP:
            ipp = _MAX_IPP
        if detail not in (0, 1, 2):
            raise ValueError(f"detail must be 0, 1, or 2 (got {detail!r})")

        params = {
            "query": query,
            "page": page,
            "ipp": ipp,
            "detail": detail,
        }

        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.get(f"{self._base_url}{_SEARCH_PATH}", params=params)
        except httpx.HTTPError as exc:
            raise KoreanstudiesAPIError(f"한국학자료포털 search request failed: {exc}") from exc

        if resp.status_code == 404:
            raise KoreanstudiesAPIError(
                f"한국학자료포털 search returned 404 — endpoint may have moved "
                f"(base_url={self._base_url})"
            )
        if resp.status_code == 429:
            raise KoreanstudiesAPIError("한국학자료포털 search rate limit exceeded (429)")
        if resp.status_code >= 400:
            raise KoreanstudiesAPIError(
                f"한국학자료포털 search returned {resp.status_code}: {resp.text[:200]}"
            )

        return _parse_response(resp.text)


def _parse_response(xml_text: str) -> KoreanstudiesSearchResponse:
    """Turn the raw XML envelope into a typed :class:`KoreanstudiesSearchResponse`.

    Tolerant by design: missing optional fields default to empty strings so
    a partial schema change at the upstream doesn't break recipe-generate.
    Records that lack both ``uci`` and ``title`` are skipped (matches the
    장서각 parser's policy) and a warning is logged.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise KoreanstudiesAPIError(f"한국학자료포털 returned non-XML body: {exc}") from exc

    if root.tag != "ksm":
        raise KoreanstudiesAPIError(f"unexpected root element <{root.tag}>; expected <ksm>")

    info = root.find("info")
    total = _int_or_default(_text(info, "total") if info is not None else "", 0)
    page = _int_or_default(_text(info, "page") if info is not None else "", 1)
    ipp = _int_or_default(_text(info, "ipp") if info is not None else "", 0)

    parsed: list[KoreanstudiesSearchResult] = []
    items = root.find("items")
    if items is not None:
        for item in items.findall("item"):
            row = _parse_item(item)
            if row is not None:
                parsed.append(row)

    return KoreanstudiesSearchResponse(
        total_count=total,
        page=page,
        ipp=ipp,
        results=tuple(parsed),
    )


def _parse_item(item: ET.Element) -> KoreanstudiesSearchResult | None:
    """Parse one ``<item>`` row. Returns ``None`` if it's too sparse to use."""
    external_id = _text(item, "uci")
    title = _text(item, "title")
    if not external_id and not title:
        logger.warning(
            "skipping 한국학자료포털 result with no uci and no title: %s",
            ET.tostring(item, encoding="unicode")[:200],
        )
        return None

    detail_url = _text(item, "url")

    # 기본정보 — present when detail >= 1. The 자료명 inside 기본정보 is
    # authoritative (matches the top-level <title>); we prefer the top-level
    # <title> for ordering robustness when 기본정보 is absent (detail=0).
    type_category = ""
    content_category = ""
    region_modern = ""
    region_historical = ""
    composition_period_raw = ""
    summary_bits: list[str] = []

    info = item.find("기본정보")
    if info is not None:
        # 분류명 elements, identified by 종류 attribute
        for cls in info.findall("분류/분류명"):
            kind = cls.attrib.get("종류", "")
            text = (cls.text or "").strip()
            if kind == "형식분류":
                type_category = text
            elif kind == "내용분류":
                content_category = text

        # 자료명 inside 기본정보 — fall back to it if top-level title was blank
        if not title:
            title = _text(info, "자료명")

        region_node = info.find("작성지역")
        if region_node is not None:
            region_modern = region_node.attrib.get("현재주소", "").strip()
            region_historical = (region_node.text or "").strip()

        period_node = info.find("작성시기")
        if period_node is not None:
            # The 정보원표기 attribute is the human-readable era string; if
            # missing, fall back to other attrs / element text.
            composition_period_raw = (
                period_node.attrib.get("정보원표기", "").strip()
                or period_node.attrib.get("생산기간", "").strip()
                or (period_node.text or "").strip()
            )

        remarks = _text(info, "비고")
        if remarks:
            summary_bits.append(remarks)

    # 안내정보 (detail=2) — concatenate non-empty 표제어 + 문단 text.
    guide = item.find("안내정보")
    if guide is not None:
        for entry in guide.findall("안내정보자료"):
            head = _text(entry, "표제어")
            if head:
                summary_bits.append(head)
            for paragraph in entry.findall("내용/문단"):
                text = (paragraph.text or "").strip()
                if text:
                    summary_bits.append(text)

    year, period = derive_year_and_period(composition_period_raw)

    return KoreanstudiesSearchResult(
        external_id=external_id,
        title=title,
        detail_url=detail_url,
        type_category=type_category,
        content_category=content_category,
        region_modern=region_modern,
        region_historical=region_historical,
        composition_period_raw=composition_period_raw,
        year=year,
        period=period,
        summary=" · ".join(s for s in summary_bits if s),
    )


def _text(node: ET.Element | None, tag: str) -> str:
    """Return the stripped text content of ``node.find(tag)`` or ``""``."""
    if node is None:
        return ""
    child = node.find(tag)
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def _int_or_default(raw: str, default: int) -> int:
    """Parse ``raw`` as int, returning ``default`` on any failure.

    The kostma API wraps numeric fields in whitespace (``<total>\\n5</total>``)
    so .strip() in ``_text`` already handles it; we keep this helper for
    extra resilience against future format drift.
    """
    try:
        return int((raw or "").strip())
    except (TypeError, ValueError):
        return default
