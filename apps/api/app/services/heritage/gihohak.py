"""기호유학 고문헌 통합정보시스템 Open API client (충남대 / giho.cnu.ac.kr).

Endpoint (per the official `Open API 이용안내` page):
    ``GET http://giho.cnu.ac.kr/api/literature/search.do``
Documentation: http://giho.cnu.ac.kr/apiInfo.do
Operator: 충남대학교 도서관 / 한자문화연구소.

Why this source
---------------
기호유학 (畿湖儒學) = the Confucian school of the Gihoyuhak region (충청도
and the broader Han River basin). 충남대 has built a national-DB project
to digitise the regional archives. This is the **specialised regional
counterpart** to the more general-purpose sources already wired in:

* 장서각 (PR #33) — 한국학중앙연구원 royal-archive (왕실) materials.
* 한국학자료포털 (PR #35) — 한국학중앙연구원 다지역 high-resolution.
* NLK (PR #36) — national-scale KORCIS standard bibliographic data.
* **기호유학 (this module)** — 충청권 가문/서원 소장 고서/고문서/금석문 +
  인물 network metadata.

The regional + lineage focus is what's distinctive — searches for foods
or rituals tied to specific 가문/서원 (e.g. 송시열 / 권상하 line) surface
materials the other three archives lack.

Surface (documented in apiInfo.do, verified via Wayback snapshot)
-----------------------------------------------------------------
* Path: ``/api/literature/search.do`` (this module focuses on literature;
  ``/api/person/{search,detail}.do`` are a future enhancement).
* Auth: none (no API key, no header)
* Parameters:
    - ``type`` (str): ``OB`` 고서 (육서심원 포함) / ``OD`` 고문서 (금석문
      포함). Omit for person searches. We default to ``OB`` (고서) since
      classical books carry more food/ritual content than legal/contract
      documents.
    - ``target`` (str): ``all`` / ``title`` / ``creator`` / ``abstract``.
      Default ``all`` for broad recall — the kostma/장서각 adapters do
      the same cross-field search.
    - ``keyword`` (str, required): UTF-8 query
    - ``page`` (int, default 1): 1-based page index
    - ``pageSize`` (int, default 10): items per page

Response shape (XML, observed live via Wayback snapshot)
--------------------------------------------------------
::

    <?xml version="1.0" encoding="utf-8"?>
    <gihoConfucianism>
      <searchInfo>
        <total>3772</total>
        <type>OD</type>
        <target>all</target>
        <keyword>간찰</keyword>
        <page>1</page>
        <pageSize>10</pageSize>
      </searchInfo>
      <searchResult>
        <literature>
          <identifier>OD_20131231000002_68</identifier>
          <dataType>OD</dataType>
          <dataTypeNm>고문서</dataTypeNm>
          <mainTitle><![CDATA[...한글명칭...]]></mainTitle>
          <alternativeTitle><![CDATA[簡札]]></alternativeTitle>
          <mainCreator><![CDATA[이인조[李寅祖]]]></mainCreator>
          <created>미상</created>   <!-- string: "미상" OR integer year -->
          <relationDate><![CDATA[미상]]></relationDate>
          <recomFg>N</recomFg>
          <classFullNm>서간통고류>서간류>간찰</classFullNm>
          <uci><![CDATA[G001+KR03-7001144.131231.D0.OD_20131231000002_68]]></uci>
          <url><![CDATA[http://giho.cnu.ac.kr/shr/gihoSearchUserDetail.do?...]]></url>
          <abstract><![CDATA[...해제...]]></abstract>
        </literature>
        ...
      </searchResult>
    </gihoConfucianism>

The ``<created>`` field violates its own docs — the documented type is
``integer (0 for 미상)`` but live data returns the literal string
``"미상"`` for unknown years. The parser handles both shapes.

Failure mode
------------
:class:`GihohakAPIError` is raised for any non-2xx response, network
transport error, unparseable XML body, or unexpected root element.
Callers (the live adapter) wrap this to fall back to the mock matcher —
identical resilience contract to the 장서각 / 한국학자료포털 / NLK
adapters.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from xml.etree import ElementTree as ET

import httpx

logger = logging.getLogger(__name__)

# The docs and live responses use plain HTTP (the cnu.ac.kr TLS cert chain
# has historically been incomplete). We default to HTTP and let operators
# override with HTTPS if the upstream rolls out a valid cert. Both work.
GIHOHAK_DEFAULT_BASE_URL = "http://giho.cnu.ac.kr"
GIHOHAK_INSTITUTION_CODE = "gihohak"
"""Stable institution identifier used in ``HeritageDoc.institution``.

Romanisation note: 기호 → ``giho``, 유학 → ``yuhak`` / 학 → ``hak``. The
upstream itself uses ``giho`` in its hostname; we use ``gihohak`` (giho
+ hak) as the institution code so it doesn't collide with the future
person-search namespace if/when we add it.
"""

_SEARCH_PATH = "/api/literature/search.do"
_DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_DEFAULT_PAGE_SIZE = 10
_MAX_PAGE_SIZE = 100  # not formally documented; safe ceiling matching other adapters.

_VALID_TYPES = frozenset({"OB", "OD"})
_VALID_TARGETS = frozenset({"all", "title", "creator", "abstract"})

# 4-digit Common-Era year. Identical regex to 장서각/한국학자료포털/NLK so
# all four sources bucket records into the same period boundaries.
_YEAR_RE = re.compile(r"(\d{4})")
_PERIOD_LATE_JOSEON_START = 1593
_PERIOD_MODERN_START = 1897


class GihohakAPIError(Exception):
    """Raised when the 기호유학 API fails or returns an unparseable body."""


@dataclass(frozen=True)
class GihohakSearchResult:
    """One ``<literature>`` row from the 기호유학 search response, normalised."""

    external_id: str  # identifier (e.g. "OD_20131231000002_68")
    data_type: str  # "OB" (고서) / "OD" (고문서) / "RC" (금석문, returned in detail only)
    data_type_name: str  # "고서" / "고문서" / "금석문"
    title: str  # mainTitle (한글명칭)
    alt_title: str  # alternativeTitle (한자명칭)
    creator: str  # mainCreator
    created_raw: str  # "미상" OR a numeric year as string
    year: int | None
    period: str  # 조선전기 / 조선후기 / 근대 / "" if unknown
    relation_date: str  # 간지연도 (e.g. "신묘", "을사" — Sexagenary cycle marker)
    recommended: bool  # recomFg=="Y"
    class_full_name: str  # 분류체계명, ">"-separated hierarchy
    uci: str
    detail_url: str  # human-readable viewer URL
    abstract: str  # 해제 (descriptive summary)


@dataclass(frozen=True)
class GihohakSearchResponse:
    total_count: int
    type_filter: str  # the ``type`` echoed in <searchInfo>
    target: str
    keyword: str
    page: int
    page_size: int
    results: tuple[GihohakSearchResult, ...]


def derive_year_and_period(raw: str) -> tuple[int | None, str]:
    """Parse a ``<created>`` value into ``(year, period_bucket)``.

    Handles four shapes seen in the wild / documented:

    * ``""`` / ``None`` — returns ``(None, "")``
    * ``"미상"`` — explicit unknown marker; returns ``(None, "")``
    * ``"0"`` — documented sentinel for unknown; returns ``(None, "")``
    * ``"1631"`` etc. — 4-digit CE year; returns the parsed year + period

    Boundaries (1592 / 1897) match 장서각 / 한국학자료포털 / NLK exactly
    so cross-source ranking can compare scores without renormalising.
    """
    if not raw:
        return None, ""
    if raw.strip() in {"미상", "0"}:
        return None, ""
    match = _YEAR_RE.search(raw)
    if not match:
        return None, ""
    year = int(match.group(1))
    if year <= 0:
        return None, ""
    if year < _PERIOD_LATE_JOSEON_START:
        period = "조선전기"
    elif year < _PERIOD_MODERN_START:
        period = "조선후기"
    else:
        period = "근대"
    return year, period


class GihohakSearchClient:
    """Thin wrapper over ``GET /api/literature/search.do``.

    Stateless beyond config (base URL, timeout). All network failures,
    non-2xx responses, and unparseable bodies normalise to
    :class:`GihohakAPIError` — callers don't have to distinguish
    ``httpx.ConnectError``, ``httpx.ReadTimeout``, XML parse failures, or
    HTTP 5xx.
    """

    def __init__(
        self,
        base_url: str = GIHOHAK_DEFAULT_BASE_URL,
        timeout: httpx.Timeout = _DEFAULT_TIMEOUT,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def search(
        self,
        query: str,
        *,
        type_filter: str = "OB",
        target: str = "all",
        page: int = 1,
        page_size: int = _DEFAULT_PAGE_SIZE,
    ) -> GihohakSearchResponse:
        """Run a literature search and return the parsed response.

        :param query: required search keyword. Sent as ``keyword``.
        :param type_filter: ``OB`` (고서, default) or ``OD`` (고문서).
        :param target: ``all`` / ``title`` / ``creator`` / ``abstract``.
            ``all`` (default) for broad cross-field recall.
        :param page: 1-based page number
        :param page_size: items per page (default 10, capped at 100)
        """
        if not query:
            raise ValueError("query is required")
        if type_filter not in _VALID_TYPES:
            raise ValueError(
                f"type_filter must be one of {sorted(_VALID_TYPES)} (got {type_filter!r})"
            )
        if target not in _VALID_TARGETS:
            raise ValueError(f"target must be one of {sorted(_VALID_TARGETS)} (got {target!r})")
        if page_size > _MAX_PAGE_SIZE:
            page_size = _MAX_PAGE_SIZE
        if page < 1:
            page = 1

        params: dict[str, str | int] = {
            "type": type_filter,
            "target": target,
            "keyword": query,
            "page": page,
            "pageSize": page_size,
        }

        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.get(f"{self._base_url}{_SEARCH_PATH}", params=params)
        except httpx.HTTPError as exc:
            raise GihohakAPIError(f"기호유학 search request failed: {exc}") from exc

        if resp.status_code == 404:
            raise GihohakAPIError(
                f"기호유학 search returned 404 — endpoint may have moved "
                f"(base_url={self._base_url})"
            )
        if resp.status_code == 429:
            raise GihohakAPIError("기호유학 search rate limit exceeded (429)")
        if resp.status_code >= 400:
            raise GihohakAPIError(f"기호유학 search returned {resp.status_code}: {resp.text[:200]}")

        return _parse_response(resp.text)


def _parse_response(xml_text: str) -> GihohakSearchResponse:
    """Turn the raw XML envelope into a typed :class:`GihohakSearchResponse`.

    Tolerant by design: missing optional fields default to empty strings so
    partial schema changes don't break recipe-generate. Records that lack
    both ``identifier`` and ``mainTitle`` are skipped (matches the
    장서각 / 한국학자료포털 / NLK parser policy) and a warning is logged.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise GihohakAPIError(f"기호유학 returned non-XML body: {exc}") from exc

    if root.tag != "gihoConfucianism":
        raise GihohakAPIError(f"unexpected root element <{root.tag}>; expected <gihoConfucianism>")

    info = root.find("searchInfo")
    total = _int_or_default(_text(info, "total") if info is not None else "", 0)
    type_filter = _text(info, "type") if info is not None else ""
    target = _text(info, "target") if info is not None else ""
    keyword = _text(info, "keyword") if info is not None else ""
    page = _int_or_default(_text(info, "page") if info is not None else "", 1)
    page_size = _int_or_default(_text(info, "pageSize") if info is not None else "", 0)
    # The upstream encodes a literally-missing keyword as "null" rather
    # than an empty element — normalise that to "" so callers don't have
    # to special-case it.
    if keyword == "null":
        keyword = ""

    parsed: list[GihohakSearchResult] = []
    result_node = root.find("searchResult")
    items = list(result_node.findall("literature")) if result_node is not None else []
    for item in items:
        result = _parse_item(item)
        if result is None:
            continue
        parsed.append(result)

    return GihohakSearchResponse(
        total_count=total,
        type_filter=type_filter,
        target=target,
        keyword=keyword,
        page=page,
        page_size=page_size,
        results=tuple(parsed),
    )


def _parse_item(item: ET.Element) -> GihohakSearchResult | None:
    """Map one ``<literature>`` element to a :class:`GihohakSearchResult`."""
    identifier = _text(item, "identifier")
    title = _text(item, "mainTitle")
    if not identifier and not title:
        logger.warning("기호유학 item dropped: no identifier and no mainTitle")
        return None

    created_raw = _text(item, "created")
    year, period = derive_year_and_period(created_raw)

    return GihohakSearchResult(
        external_id=identifier,
        data_type=_text(item, "dataType"),
        data_type_name=_text(item, "dataTypeNm"),
        title=title,
        alt_title=_text(item, "alternativeTitle"),
        creator=_text(item, "mainCreator"),
        created_raw=created_raw,
        year=year,
        period=period,
        relation_date=_text(item, "relationDate"),
        recommended=_text(item, "recomFg").upper() == "Y",
        class_full_name=_text(item, "classFullNm"),
        uci=_text(item, "uci"),
        detail_url=_text(item, "url"),
        abstract=_text(item, "abstract"),
    )


def _text(parent: ET.Element | None, tag: str) -> str:
    """Return the trimmed text of ``parent/tag`` or empty string.

    Defensive: works when ``parent`` is ``None`` (missing parent element)
    or when the tag is missing entirely.
    """
    if parent is None:
        return ""
    el = parent.find(tag)
    if el is None or el.text is None:
        return ""
    return el.text.strip()


def _int_or_default(value: str, default: int) -> int:
    """Parse ``value`` as a non-negative int, returning ``default`` on failure."""
    try:
        out = int(value)
    except (TypeError, ValueError):
        return default
    return out if out >= 0 else default
