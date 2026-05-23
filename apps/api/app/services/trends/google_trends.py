"""``GoogleTrendsCandidateProvider`` — open-discovery from Google's daily trends RSS.

Hits ``trends.google.com/trending/rss`` directly with httpx (rather than
depend on the unmaintained ``pytrends`` package or the legacy
``/trends/api/dailytrends`` JSON endpoint Google deprecated to a 404 in
2025). The RSS feed:

- Is the same data the Google Trends homepage shows for ``geo=KR``. Public,
  no auth, no XSSI prefix, plain ``application/rss+xml``.
- Lists ~20–25 trending searches with ``<item><title>`` carrying the
  keyword and ``<ht:approx_traffic>`` an order-of-magnitude volume hint
  ("100+", "1K+", ...). We only need the title for candidate discovery.
- Surfaces *open-domain* trending searches: politics, sports, celebs,
  weather, plus the occasional food trend. Filtering is delegated to
  ``food_filter.filter_food_adjacent`` — a denylist-only filter that keeps
  novel food concepts (탕후루, 마라맛, 두바이쫀득쿠키, …) and drops only
  clearly non-food categories.

The provider is **lenient on failure**: network errors, rate limits, XML
parse errors all log a warning and return an empty candidate list. Open-
discovery providers are by definition optional — a flaky Google response
should not break the entire ``/v1/admin/trends/refresh`` job.
"""

from __future__ import annotations

import logging
from datetime import date
from xml.etree import ElementTree as ET

import httpx

from app.services.trends.food_filter import filter_food_adjacent

logger = logging.getLogger(__name__)

_DAILY_TRENDS_URL = "https://trends.google.com/trending/rss"
_DEFAULT_TIMEOUT = httpx.Timeout(5.0, connect=3.0)


class GoogleTrendsCandidateProvider:
    """Daily trending queries from Google Trends RSS, filtered to food candidates."""

    name = "google_trends_daily"

    def __init__(
        self,
        geo: str = "KR",
        hl: str = "ko-KR",
        tz_offset_minutes: int = -540,
        base_url: str = _DAILY_TRENDS_URL,
        timeout: httpx.Timeout = _DEFAULT_TIMEOUT,
    ) -> None:
        # ``hl`` / ``tz_offset_minutes`` are kept on the constructor for
        # backwards compatibility and so a future swap back to the JSON
        # endpoint (or a different downstream) doesn't change this API —
        # the RSS endpoint itself only takes ``geo``.
        self._geo = geo
        self._hl = hl
        self._tz = tz_offset_minutes
        self._base_url = base_url
        self._timeout = timeout

    def discover_candidates(
        self,
        today: date | None = None,  # noqa: ARG002 — Google picks its own day window
        limit: int = 50,
    ) -> list[str]:
        raw = self._fetch_raw_trending()
        if not raw:
            return []
        adjacent = filter_food_adjacent(raw)
        seen: set[str] = set()
        deduped: list[str] = []
        for kw in adjacent:
            if kw not in seen:
                seen.add(kw)
                deduped.append(kw)
        return deduped[:limit] if limit else deduped

    def _fetch_raw_trending(self) -> list[str]:
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.get(self._base_url, params={"geo": self._geo})
        except httpx.HTTPError as exc:
            logger.warning("Google Trends fetch failed: %s", exc)
            return []
        if resp.status_code != 200:
            logger.warning("Google Trends returned %s: %s", resp.status_code, resp.text[:200])
            return []
        return _parse_daily_trends_rss(resp.text)


def _parse_daily_trends_rss(body: str) -> list[str]:
    """Pull ``<item><title>`` text out of the Google Trends RSS feed.

    Feed shape::

        <rss>
          <channel>
            <item>
              <title>키워드</title>
              <ht:approx_traffic>200+</ht:approx_traffic>
              ...
            </item>
            ...
          </channel>
        </rss>

    Titles are returned in source order; deduplication and limit-trimming
    are the caller's responsibility.
    """
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        logger.warning("Google Trends RSS was not valid XML: %s", exc)
        return []
    out: list[str] = []
    for item in root.iter("item"):
        title = item.find("title")
        if title is None or not title.text:
            continue
        text = title.text.strip()
        if text:
            out.append(text)
    return out
