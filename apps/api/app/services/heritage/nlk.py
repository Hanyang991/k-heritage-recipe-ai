"""국립중앙도서관 (National Library of Korea, NLK) Open API client.

Endpoint (live, requires API key):
    ``GET https://www.nl.go.kr/NL/search/openApi/search.do``
Documentation: https://www.nl.go.kr/NL/contents/N31101030700.do?hl=ko-KR
Key registration: https://www.nl.go.kr/NL/contents/N31101030500.do (인증키 신청/관리)

Why this source
---------------
국립중앙도서관 is the largest 표준 서지 데이터 (standardised bibliographic
metadata) source in Korea and is the canonical operator of:

* **KORCIS** (한국고문헌종합목록) — federated catalogue of 고전적 (classical
  manuscripts) across every Korean institution. Records here include
  ``control_no`` values that are *stable across institutions*, making
  this the natural dedupe anchor for the planned ``MultiSourceHeritageAdapter``
  (todo.md §1.3.1).
* **KOLIS-NET** (국가자료종합목록) — integrated catalogue of every public
  library's holdings.

장서각 (PR #33) and 한국학자료포털 (PR #35) cover the 한국학중앙연구원
collections directly; NLK adds national-scale coverage plus the
standardised IDs needed to merge results without double-counting.

Surface (per docs page, verified 2026-05)
-----------------------------------------
* Path: ``/NL/search/openApi/search.do``
* Auth: ``key=<발급키>`` query parameter (required — the endpoint returns
  ``<error_code>011</error_code>`` if missing or invalid)
* Search parameters:
    - ``kwd`` (str): keyword (URL-encoded)
    - ``srchTarget`` (str): search target; ``total`` for cross-field
    - ``pageNum`` (int, required): 1-based page index
    - ``pageSize`` (int, required, default 10): items per page
    - ``category`` (str): ``도서`` / ``고문헌`` / ``학위논문`` / ``잡지/학술지``
      / ``신문`` / ``기사`` / ``멀티미디어`` / ``장애인자료`` / ``외부연계자료``
      / ``웹사이트`` / ``수집`` / ``기타`` / ``해외한국관련자료``. We default
      to ``고문헌`` since this is a heritage adapter.
    - ``systemType`` (str): ``오프라인자료`` (소장정보) or ``온라인자료``
      (디지털화자료)
    - ``apiType`` (str): ``xml`` (default here) or ``json``
    - ``sort`` / ``order`` — sort field + direction
* Limit: searches past the 500-result mark return ``error_code=012``;
  the client doesn't enforce this since recipe-generate only ever asks
  for ``limit<=10``.

Response shape (XML)
--------------------
Per the NLK Open API guide::

    <channel>
      <kwd>토지</kwd>
      <total>1234</total>
      <pageNum>1</pageNum>
      <pageSize>10</pageSize>
      <list>
        <item>
          <title_info>...</title_info>
          <author_info>...</author_info>
          <pub_info>...</pub_info>
          <pub_year_info>2012</pub_year_info>
          <type_name>도서</type_name>
          <type_code>11</type_code>
          <control_no>KMO201234567890</control_no>
          <call_no>...</call_no>
          <isbn>...</isbn>
          <doc_yn>N</doc_yn>
          <org_link></org_link>
          <detail_link>/NL/contents/...</detail_link>
          <id>...</id>
          <kdc_code_1s>800</kdc_code_1s>
          <kdc_name_1s>문학</kdc_name_1s>
          <lic_yn>L</lic_yn>
          <lic_text>...</lic_text>
          <reg_date>20120101</reg_date>
        </item>
      </list>
    </channel>

Error responses come back as ``<error><error_code>NNN</error_code>
<msg>...</msg></error>`` — the client detects the root tag and raises
:class:`NlkAPIError` with the upstream message preserved.

Failure mode
------------
:class:`NlkAPIError` is raised for missing key, non-2xx HTTP status,
upstream-error envelopes (``<error>...``), network transport failures, or
unparseable XML bodies. Callers (the live adapter) wrap this to fall back
to the mock matcher — same resilience contract as the 장서각 and
한국학자료포털 adapters.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from xml.etree import ElementTree as ET

import httpx

logger = logging.getLogger(__name__)

NLK_DEFAULT_BASE_URL = "https://www.nl.go.kr"
NLK_INSTITUTION_CODE = "nlk"
"""Stable institution identifier used in ``HeritageDoc.institution``."""

_SEARCH_PATH = "/NL/search/openApi/search.do"
_DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_DEFAULT_PAGE_SIZE = 10
# NLK enforces a 500-record window (error_code=012). recipe-generate only
# asks for limit<=10 so we just guard against silly oversized requests.
_MAX_PAGE_SIZE = 500

# 4-digit Common-Era year. Same regex as 장서각 / 한국학자료포털 so all three
# sources bucket records into identical period boundaries.
_YEAR_RE = re.compile(r"(\d{4})")
_PERIOD_LATE_JOSEON_START = 1593
_PERIOD_MODERN_START = 1897


class NlkAPIError(Exception):
    """Raised when the 국립중앙도서관 API fails or returns an unparseable body.

    The upstream ``error_code`` (when available) is exposed as
    :attr:`error_code` so callers can distinguish auth issues (``010`` /
    ``011``) from parameter problems (``013`` / ``014``) — useful for
    triggering a one-time "please set NLK_API_KEY" warning vs. a generic
    transient-failure fallback.
    """

    def __init__(self, message: str, *, error_code: str | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True)
class NlkSearchResult:
    """One row from a NLK ``/openApi/search.do`` response, normalised."""

    external_id: str  # control_no (KORCIS-stable when present, else id)
    title: str  # title_info
    author: str  # author_info
    publisher: str  # pub_info
    pub_year_raw: str  # pub_year_info ("2012", "201201", or "순조 14년(1814)")
    year: int | None
    period: str  # 조선전기 / 조선후기 / 근대 / "" if no year
    type_name: str  # 자료유형 ("도서", "고문헌", ...)
    call_number: str  # call_no
    isbn: str
    detail_url: str  # absolute URL into nl.go.kr
    has_original_text: bool  # doc_yn == "Y"
    original_text_url: str  # org_link
    kdc_code: str  # kdc_code_1s ("800")
    kdc_name: str  # kdc_name_1s ("문학")
    license_code: str  # lic_yn ("L", "Y", "N", ...)
    license_text: str  # lic_text


@dataclass(frozen=True)
class NlkSearchResponse:
    total_count: int
    page_num: int
    page_size: int
    results: tuple[NlkSearchResult, ...]


def derive_year_and_period(raw: str) -> tuple[int | None, str]:
    """Parse a ``pub_year_info`` style string into ``(year, period_bucket)``.

    Handles three shapes seen in the wild:

    * ``"2012"`` — modern publication year
    * ``"201201"`` — YYYYMM (extracts YYYY)
    * ``"순조 14년(1814년)"`` — 고문헌 with embedded CE year in parentheses

    Returns ``(None, "")`` when no 4-digit year can be extracted. Boundaries
    match 장서각 + 한국학자료포털 so a future blended ranking can sort
    cross-source results without renormalising.
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


class NlkSearchClient:
    """Thin wrapper over ``GET /NL/search/openApi/search.do``.

    Stateless beyond config (API key, base URL, timeout). All network
    failures, non-2xx responses, upstream error envelopes, and unparseable
    bodies normalise to :class:`NlkAPIError` — callers don't have to
    distinguish ``httpx.ConnectError``, ``httpx.ReadTimeout``, XML parse
    failures, HTTP 5xx, or ``<error_code>011</error_code>``.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = NLK_DEFAULT_BASE_URL,
        timeout: httpx.Timeout = _DEFAULT_TIMEOUT,
    ) -> None:
        if not api_key:
            raise ValueError(
                "NLK_API_KEY is required — register at "
                "https://www.nl.go.kr/NL/contents/N31101030500.do"
            )
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def search(
        self,
        query: str,
        *,
        page_num: int = 1,
        page_size: int = _DEFAULT_PAGE_SIZE,
        category: str = "고문헌",
        system_type: str | None = None,
    ) -> NlkSearchResponse:
        """Run a search and return the parsed response.

        :param query: required search keyword (현대어). Sent as ``kwd``.
        :param page_num: 1-based page number (default 1)
        :param page_size: items per page (default 10, capped at 500)
        :param category: NLK 카테고리 filter; default ``고문헌`` since this
            is a heritage adapter. Pass empty string to disable.
        :param system_type: optional ``오프라인자료`` / ``온라인자료`` filter
        """
        if not query:
            raise ValueError("query is required")
        if page_size > _MAX_PAGE_SIZE:
            page_size = _MAX_PAGE_SIZE
        if page_num < 1:
            page_num = 1

        params: dict[str, str | int] = {
            "key": self._api_key,
            "kwd": query,
            "srchTarget": "total",
            "pageNum": page_num,
            "pageSize": page_size,
            "apiType": "xml",
        }
        if category:
            params["category"] = category
        if system_type:
            params["systemType"] = system_type

        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.get(f"{self._base_url}{_SEARCH_PATH}", params=params)
        except httpx.HTTPError as exc:
            raise NlkAPIError(f"NLK search request failed: {exc}") from exc

        if resp.status_code == 404:
            raise NlkAPIError(
                f"NLK search returned 404 — endpoint may have moved (base_url={self._base_url})"
            )
        if resp.status_code == 429:
            raise NlkAPIError("NLK search rate limit exceeded (429)")
        if resp.status_code >= 400:
            raise NlkAPIError(f"NLK search returned {resp.status_code}: {resp.text[:200]}")

        return _parse_response(resp.text)


def _parse_response(xml_text: str) -> NlkSearchResponse:
    """Turn the raw XML envelope into a typed :class:`NlkSearchResponse`.

    Tolerant by design: missing optional fields default to empty strings so
    a partial schema change at the upstream doesn't break recipe-generate.
    Records that lack both ``control_no`` / ``id`` and ``title_info`` are
    skipped (matches the 장서각 / 한국학자료포털 policy) and a warning is
    logged.

    Upstream error envelopes (``<error><error_code>NNN</error_code>...``)
    are detected and re-raised as :class:`NlkAPIError` so the live adapter
    can fall back to the mock matcher.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise NlkAPIError(f"NLK returned non-XML body: {exc}") from exc

    if root.tag == "error":
        code = _text(root, "error_code")
        msg = _text(root, "msg") or "unknown upstream error"
        raise NlkAPIError(f"NLK error_code={code}: {msg}", error_code=code or None)

    if root.tag != "channel":
        raise NlkAPIError(f"unexpected root element <{root.tag}>; expected <channel>")

    total = _int_or_default(_text(root, "total"), 0)
    page_num = _int_or_default(_text(root, "pageNum"), 1)
    page_size = _int_or_default(_text(root, "pageSize"), 0)

    parsed: list[NlkSearchResult] = []
    list_node = root.find("list")
    items = list(list_node.findall("item")) if list_node is not None else []
    # Some NLK queries return items as direct children of <channel> (no
    # wrapping <list>). Stay tolerant.
    if not items:
        items = list(root.findall("item"))
    for item in items:
        result = _parse_item(item)
        if result is None:
            continue
        parsed.append(result)

    return NlkSearchResponse(
        total_count=total,
        page_num=page_num,
        page_size=page_size,
        results=tuple(parsed),
    )


def _parse_item(item: ET.Element) -> NlkSearchResult | None:
    """Map one ``<item>`` element to an :class:`NlkSearchResult`.

    Returns ``None`` (and logs a warning) when both the stable id fields
    and the title are blank — there's nothing useful to do with such a row.
    """
    control_no = _text(item, "control_no")
    item_id = _text(item, "id")
    title = _text(item, "title_info")
    if not (control_no or item_id) and not title:
        logger.warning("NLK item dropped: no control_no/id and no title_info")
        return None

    pub_year_raw = _text(item, "pub_year_info")
    year, period = derive_year_and_period(pub_year_raw)

    detail_link = _text(item, "detail_link")
    # detail_link is documented as a path; make it absolute when it starts
    # with "/" so consumers can link to it without re-joining the base.
    if detail_link.startswith("/"):
        detail_link = f"{NLK_DEFAULT_BASE_URL}{detail_link}"

    return NlkSearchResult(
        external_id=control_no or item_id,
        title=title,
        author=_text(item, "author_info"),
        publisher=_text(item, "pub_info"),
        pub_year_raw=pub_year_raw,
        year=year,
        period=period,
        type_name=_text(item, "type_name"),
        call_number=_text(item, "call_no"),
        isbn=_text(item, "isbn"),
        detail_url=detail_link,
        has_original_text=_text(item, "doc_yn").upper() == "Y",
        original_text_url=_text(item, "org_link"),
        kdc_code=_text(item, "kdc_code_1s"),
        kdc_name=_text(item, "kdc_name_1s"),
        license_code=_text(item, "lic_yn"),
        license_text=_text(item, "lic_text"),
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
