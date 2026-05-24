"""장서각 Digital Archive Open API client (한국학중앙연구원).

Endpoint (verified live 2026-05): ``GET https://jsg.aks.ac.kr/api/search``
Documentation: https://jsg.aks.ac.kr/api/help

Notes on the spec mismatch
--------------------------
The tech-spec PDF §3.1/§3.2 lists this endpoint as
``GET /api/v1/documents/search`` with ``q / category / period / page / size``
parameters and an ``API Key`` header. The published help page describes a
*different* surface that the live host actually serves:

* path: ``/api/search`` (no ``/v1`` prefix, no ``/documents``)
* params: ``qw`` (search-field selector), ``q``, ``catePath`` (slash-joined
  category path), ``sortField``, ``sortOrder``, ``startIndex``, ``pageUnit``
  (max 5000)
* auth: **none** — the endpoint is fully open, returning JSON to any GET

This module follows the live surface, since that is what production traffic
will see. The spec PDF is the planning artefact; reality wins for
implementation. The PR description documents the delta so the spec doc
can be refreshed separately.

Response shape (live-verified)
------------------------------
The endpoint returns JSON with a ``header`` summary and a ``results`` array.
Every result row uses Korean field names::

    {
      "id": "JSG_RD01275",
      "자료명": "1903년 고종의 52세 탄일에 올린 음식과 손님에게 내린 사찬발기",
      "저자": "",
      "유형분류": "고문서/의례류/발기(發記)/사찬발기(賜饌發記)",
      "주제분류": "국왕·왕실/의례",
      "수집분류": "왕실/고문서",
      "서비스분류": "왕실고문서",
      "청구기호": "RD01275",
      "MF번호": "MF35-4659",
      "작성시기": "1903(光武 7) ",
      "출처": "장서각",
      "URL": "https://jsg.aks.ac.kr/dir/view?dataId=JSG_RD01275"
    }

The ``작성시기`` field is the most useful extra signal — it usually
contains a 4-digit Common-Era year (sometimes followed by a regnal year in
parentheses like ``光武 7``). We parse it into a ``year`` integer plus
a coarse ``period`` bucket (조선전기 / 조선후기 / 근대) so downstream
filters and the ``HeritageDoc`` schema both stay populated.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

JANGSEOGAK_DEFAULT_BASE_URL = "https://jsg.aks.ac.kr/api"
JANGSEOGAK_INSTITUTION_CODE = "jangseogak"
"""Stable institution identifier used in ``HeritageDoc.institution``."""

_DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_DEFAULT_PAGE_UNIT = 20
_MAX_PAGE_UNIT = 5000  # per /api/help

# Common-Era year pattern. Matches "1903", "1903(光武 7)", "1670 ", etc.
_YEAR_RE = re.compile(r"(\d{4})")

# Period buckets per spec §3.2.1 (조선전기 / 조선후기 / 근대). The boundaries
# follow the canonical historical split: 임진왜란 (1592) divides 조선 into
# 전기 / 후기, and 대한제국 선포 (1897) marks the modern transition.
_PERIOD_LATE_JOSEON_START = 1593
_PERIOD_MODERN_START = 1897


class JangseogakAPIError(Exception):
    """Raised when the 장서각 API returns a non-success response or is unreachable."""


@dataclass(frozen=True)
class JangseogakSearchResult:
    """One row from a 장서각 ``/api/search`` response, normalised."""

    external_id: str
    title: str
    author: str
    type_category: str  # 유형분류 (e.g. "고문서/의례류/발기")
    subject_category: str  # 주제분류 (e.g. "經部/總經類")
    call_number: str  # 청구기호 (e.g. "K2-1")
    mf_number: str  # MF번호
    composition_period_raw: str  # 작성시기 raw text (may contain regnal year)
    year: int | None
    period: str  # 조선전기 / 조선후기 / 근대 / "" if unknown
    detail_url: str  # human-readable viewer URL


@dataclass(frozen=True)
class JangseogakSearchResponse:
    total_count: int
    start_index: int
    page_unit: int
    results: tuple[JangseogakSearchResult, ...]


def derive_year_and_period(raw: str) -> tuple[int | None, str]:
    """Parse ``작성시기`` into (year, period_bucket).

    The field is free-form Korean text. A 4-digit number, when present, is
    nearly always the Common-Era year of composition. The regnal-year suffix
    (e.g. ``光武 7``) is decorative for our purposes — the CE year is what
    drives the period bucket.

    Returns ``(None, "")`` when no year can be extracted.
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


class JangseogakSearchClient:
    """Thin wrapper over ``GET /api/search``.

    The client owns no state beyond config (base URL, timeout). One instance
    can be reused across requests. All network errors and non-2xx responses
    are normalised to :class:`JangseogakAPIError` so callers don't have to
    distinguish between ``httpx.ConnectError``, ``httpx.ReadTimeout``, JSON
    decode failures, and HTTP 5xx — they all land in the same branch.
    """

    def __init__(
        self,
        base_url: str = JANGSEOGAK_DEFAULT_BASE_URL,
        timeout: httpx.Timeout = _DEFAULT_TIMEOUT,
    ) -> None:
        # Strip trailing slash so f"{base}/search" never doubles up.
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def search(
        self,
        query: str,
        *,
        search_field: str | None = None,
        category_path: str | None = None,
        start_index: int = 0,
        page_unit: int = _DEFAULT_PAGE_UNIT,
    ) -> JangseogakSearchResponse:
        """Run a search and return the parsed response.

        :param query: required search keyword (현대어 or 한자)
        :param search_field: optional ``qw`` value (``dataName`` / ``author`` /
            ``callNum`` / ``cateType`` / ``cateSubj`` / ``catePur`` /
            ``mfNum`` / ``prodName`` / ``dataId``). ``None`` falls back to
            the API's full-text default.
        :param category_path: optional ``catePath`` e.g. ``유형분류/고문서``
        :param start_index: pagination offset (0-based)
        :param page_unit: page size (capped at 5000 per /api/help)
        """
        if not query:
            raise ValueError("query is required")
        if page_unit > _MAX_PAGE_UNIT:
            page_unit = _MAX_PAGE_UNIT

        params: dict[str, Any] = {
            "q": query,
            "startIndex": start_index,
            "pageUnit": page_unit,
        }
        if search_field:
            params["qw"] = search_field
        if category_path:
            params["catePath"] = category_path

        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.get(f"{self._base_url}/search", params=params)
        except httpx.HTTPError as exc:
            raise JangseogakAPIError(f"장서각 search request failed: {exc}") from exc

        if resp.status_code == 404:
            # The endpoint itself responding with 404 typically means
            # the upstream path was renamed (per spec §3.4 "API
            # endpoint change") — surface explicitly.
            raise JangseogakAPIError(
                f"장서각 search returned 404 — endpoint may have moved (base_url={self._base_url})"
            )
        if resp.status_code == 429:
            # Documented retry-after compliance lives in callers; here we
            # surface it so the trends-style retry / cooldown can react.
            raise JangseogakAPIError("장서각 search rate limit exceeded (429)")
        if resp.status_code >= 400:
            raise JangseogakAPIError(
                f"장서각 search returned {resp.status_code}: {resp.text[:200]}"
            )

        try:
            payload = resp.json()
        except ValueError as exc:
            raise JangseogakAPIError(f"장서각 search returned non-JSON body: {exc}") from exc

        return _parse_response(payload)


def _parse_response(payload: dict[str, Any]) -> JangseogakSearchResponse:
    """Turn the raw JSON envelope into a typed :class:`JangseogakSearchResponse`.

    The parser is intentionally tolerant: missing fields default to empty
    strings rather than raising, so a partial schema change at the upstream
    doesn't break recipe-generate end-to-end. Records that lack both ``id``
    and ``자료명`` are skipped (those two are the bare minimum for a useful
    document reference downstream) and a warning is logged.
    """
    header = payload.get("header") or {}
    try:
        total_count = int(header.get("totalCount", 0))
    except (TypeError, ValueError):
        total_count = 0
    try:
        start_index = int(header.get("startIndex", 0))
    except (TypeError, ValueError):
        start_index = 0
    try:
        page_unit = int(header.get("pageUnit", 0))
    except (TypeError, ValueError):
        page_unit = 0

    parsed: list[JangseogakSearchResult] = []
    for row in payload.get("results", []) or []:
        if not isinstance(row, dict):
            logger.warning("skipping non-dict 장서각 result: %r", row)
            continue
        external_id = str(row.get("id", "")).strip()
        title = str(row.get("자료명", "")).strip()
        if not external_id and not title:
            logger.warning("skipping 장서각 result with no id and no title: %r", row)
            continue
        raw_period = str(row.get("작성시기", "") or "").strip()
        year, period = derive_year_and_period(raw_period)
        parsed.append(
            JangseogakSearchResult(
                external_id=external_id,
                title=title,
                author=str(row.get("저자", "") or "").strip(),
                type_category=str(row.get("유형분류", "") or "").strip(),
                subject_category=str(row.get("주제분류", "") or "").strip(),
                call_number=str(row.get("청구기호", "") or "").strip(),
                mf_number=str(row.get("MF번호", "") or "").strip(),
                composition_period_raw=raw_period,
                year=year,
                period=period,
                detail_url=str(row.get("URL", "") or "").strip(),
            )
        )

    return JangseogakSearchResponse(
        total_count=total_count,
        start_index=start_index,
        page_unit=page_unit,
        results=tuple(parsed),
    )
