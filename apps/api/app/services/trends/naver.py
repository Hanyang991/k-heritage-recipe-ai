"""Naver DataLab 검색어 트렌드 adapter.

Docs: https://developers.naver.com/docs/serviceapi/datalab/search/search.md

Endpoint: ``POST {base_url}/v1/datalab/search``
Auth: ``X-Naver-Client-Id`` + ``X-Naver-Client-Secret`` headers.
Limits: max 5 keywordGroups per request, max 20 keywords per group, 1 000
requests per day per app. We chunk the keyword list into groups of 5 so a
20-keyword watchlist fits in 4 requests.

Region is intentionally NOT a parameter here: the search trend endpoint is
nationwide. Per-region popularity would require the *shopping insight* API,
which is a different surface area and out of scope for this adapter.

Per-chunk resilience
--------------------
Open-pool discovery (PR #13–#16) can hand this adapter 100+ merged
candidates, which fan out to 20+ chunks. A single slow Naver response
should not kill the whole refresh — so we catch ``httpx`` transport errors
and HTTP 5xx per chunk, log a warning, and skip just that chunk. Auth/
quota errors (401/429) are still re-raised because they are not
chunk-local and the entire refresh has to abort anyway.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import httpx

from app.services.trends.base import (
    TimeUnit,
    TrendDataPoint,
    TrendKeywordSeries,
    TrendsAdapterError,
)

logger = logging.getLogger(__name__)

_MAX_GROUPS_PER_REQUEST = 5
_DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class NaverDatalabAdapter:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        base_url: str = "https://openapi.naver.com",
        timeout: httpx.Timeout = _DEFAULT_TIMEOUT,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def fetch_series(
        self,
        keywords: list[str],
        start: date,
        end: date,
        time_unit: TimeUnit = "week",
    ) -> list[TrendKeywordSeries]:
        if not keywords:
            return []
        merged: list[TrendKeywordSeries] = []
        with httpx.Client(timeout=self._timeout) as client:
            for chunk in _chunk(keywords, _MAX_GROUPS_PER_REQUEST):
                try:
                    merged.extend(self._fetch_chunk(client, chunk, start, end, time_unit))
                except _TransientChunkError as exc:
                    logger.warning(
                        "Naver DataLab chunk failed (skipping %d keywords): %s",
                        len(chunk),
                        exc,
                    )
                    continue
        return merged

    def _fetch_chunk(
        self,
        client: httpx.Client,
        keywords: list[str],
        start: date,
        end: date,
        time_unit: TimeUnit,
    ) -> list[TrendKeywordSeries]:
        body: dict[str, Any] = {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "timeUnit": time_unit,
            "keywordGroups": [{"groupName": kw, "keywords": [kw]} for kw in keywords],
        }
        try:
            resp = client.post(
                f"{self._base_url}/v1/datalab/search",
                json=body,
                headers={
                    "X-Naver-Client-Id": self._client_id,
                    "X-Naver-Client-Secret": self._client_secret,
                    "Content-Type": "application/json",
                },
            )
        except httpx.HTTPError as exc:
            # Transport-level error (timeout, connect refused, etc.) — likely
            # transient for one chunk; let the caller swallow + continue.
            raise _TransientChunkError(f"transport error: {exc}") from exc

        if resp.status_code == 401:
            raise TrendsAdapterError("Naver DataLab rejected credentials (401)")
        if resp.status_code == 429:
            raise TrendsAdapterError("Naver DataLab rate limit exceeded (429)")
        if 500 <= resp.status_code < 600:
            raise _TransientChunkError(f"upstream {resp.status_code}: {resp.text[:200]}")
        if resp.status_code >= 400:
            raise TrendsAdapterError(
                f"Naver DataLab returned {resp.status_code}: {resp.text[:200]}"
            )

        return _parse_response(resp.json())


class _TransientChunkError(Exception):
    """Internal marker — a single chunk failed in a way safe to skip."""


def _chunk(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _parse_response(payload: dict[str, Any]) -> list[TrendKeywordSeries]:
    out: list[TrendKeywordSeries] = []
    for entry in payload.get("results", []):
        title = entry.get("title", "")
        data_points: list[TrendDataPoint] = []
        for row in entry.get("data", []):
            period = row.get("period")
            ratio = row.get("ratio")
            if period is None or ratio is None:
                continue
            try:
                data_points.append(
                    TrendDataPoint(period=date.fromisoformat(period), ratio=float(ratio))
                )
            except (TypeError, ValueError):
                logger.warning("skipping malformed datapoint: %r", row)
                continue
        out.append(TrendKeywordSeries(keyword=title, data=tuple(data_points)))
    return out
