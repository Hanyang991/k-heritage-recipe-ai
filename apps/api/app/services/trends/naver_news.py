"""Open-discovery candidate source: Naver Search News (source C).

Why
---
Naver Datalab gives series for *known* keywords; Naver Search gives recent
news articles. We use the latter to discover *brand new* keywords that
aren't on ``DEFAULT_WATCHLIST`` yet — by querying a small set of food-domain
seed queries and harvesting hangul-only compound nouns from titles and
descriptions. The harvested keywords feed back into ``MultiSourceDiscovery``
so PR #11's blended-score formula can rank them alongside curated and
Google-trending candidates.

Workflow
--------
1. For each seed query (configurable; defaults to "디저트 신상", "K-디저트",
   "신메뉴 카페", "트렌드 음료", "한식 디저트"), call
   ``openapi.naver.com/v1/search/news.json`` and fetch the most recent
   ``display_per_query`` articles sorted by date.
2. From each article's ``title`` + ``description``, strip the ``<b>...</b>``
   query-match highlight markup and HTML entities, then extract hangul-only
   runs of 2–12 characters. This catches compound nouns like
   "두바이쫀득쿠키" and "흑임자라떼" while dropping 1-char particles,
   English brand names, numbers, and punctuation.
3. Count frequency across all seed queries combined.
4. Apply ``food_filter.filter_food_adjacent`` (denylist-only veto shared
   with PR #13's Google source) to drop the politics/sports/celeb tokens
   that occasionally bleed into food-tagged articles.
5. Return up to ``limit`` candidates ordered by descending frequency.

Auth & graceful degradation
---------------------------
Reuses the same ``NAVER_DATALAB_CLIENT_ID`` / ``..._SECRET`` env vars as
PR #11/#12 — the Naver Developers app just needs the "검색" service enabled
in addition to "데이터랩". When credentials are missing or the API call
fails (network/quota/auth), the provider returns an empty list with a
WARNING log; the trend refresh job keeps running on the other providers.

Token-extraction caveats
------------------------
- We deliberately do NOT strip Korean particles (-이/-가/-을/-를/-의/...)
  because doing so safely requires a morphological analyser (KoNLPy +
  JVM); naive suffix stripping would mangle real words ("유자에이드"
  starts with the particle-shaped "에"). We rely on frequency: in a
  paragraph the bare compound noun appears more often than any single
  particle-suffixed form, so it bubbles to the top.
- Length 2–12 is a pragmatic window that catches realistic compound noun
  trends (2: "쿠키"/"마라", 7: "두바이쫀득쿠키", 12: "흑임자크림브륄레")
  while ignoring single-char particles and sentence fragments.
"""

from __future__ import annotations

import html
import logging
import re
from collections import Counter
from datetime import date
from typing import Any

import httpx

from app.services.trends.food_filter import is_likely_food_adjacent

logger = logging.getLogger(__name__)

_NEWS_SEARCH_PATH = "/v1/search/news.json"

_HANGUL_TOKEN_RE: re.Pattern[str] = re.compile(r"[가-힣]{2,12}")
_HIGHLIGHT_RE: re.Pattern[str] = re.compile(r"</?b>", re.IGNORECASE)

DEFAULT_SEED_QUERIES: tuple[str, ...] = (
    "디저트 신상",
    "K-디저트",
    "신메뉴 카페",
    "트렌드 음료",
    "한식 디저트",
)


class NaverNewsCandidateProvider:
    """``TrendCandidateProvider`` over the Naver Search News API."""

    name = "naver_news"

    def __init__(
        self,
        client_id: str | None,
        client_secret: str | None,
        *,
        seed_queries: tuple[str, ...] = DEFAULT_SEED_QUERIES,
        display_per_query: int = 50,
        base_url: str = "https://openapi.naver.com",
        timeout: float = 10.0,
    ) -> None:
        self._client_id = client_id or ""
        self._client_secret = client_secret or ""
        self._seed_queries = seed_queries
        self._display_per_query = max(1, min(100, display_per_query))
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def discover_candidates(
        self,
        today: date | None = None,  # noqa: ARG002 — API picks its own window
        limit: int = 50,
    ) -> list[str]:
        if not (self._client_id and self._client_secret):
            return []
        if not self._seed_queries:
            return []
        all_items: list[dict[str, Any]] = []
        try:
            with httpx.Client(timeout=self._timeout) as client:
                for query in self._seed_queries:
                    all_items.extend(self._fetch_news(client, query))
        except httpx.HTTPError as exc:
            logger.warning("naver news fetch failed: %s", exc)
            return []
        if not all_items:
            return []
        counts = _extract_token_counts(all_items)
        if not counts:
            return []
        ranked = [kw for kw, _ in counts.most_common() if is_likely_food_adjacent(kw)]
        return ranked[:limit] if limit else ranked

    def _fetch_news(self, client: httpx.Client, query: str) -> list[dict[str, Any]]:
        url = f"{self._base_url}{_NEWS_SEARCH_PATH}"
        headers = {
            "X-Naver-Client-Id": self._client_id,
            "X-Naver-Client-Secret": self._client_secret,
            "Accept": "application/json",
        }
        params = {
            "query": query,
            "display": str(self._display_per_query),
            "sort": "date",
        }
        try:
            resp = client.get(url, params=params, headers=headers)
        except httpx.HTTPError as exc:
            logger.warning("naver news query %r failed: %s", query, exc)
            return []
        if resp.status_code != 200:
            logger.warning("naver news query %r returned %s", query, resp.status_code)
            return []
        try:
            body = resp.json()
        except ValueError:
            logger.warning("naver news query %r returned invalid JSON", query)
            return []
        items = body.get("items") if isinstance(body, dict) else None
        return items if isinstance(items, list) else []


def _extract_token_counts(items: list[dict[str, Any]]) -> Counter[str]:
    """Count hangul compound-noun tokens across each article.

    Headline-level denylist check first: if the title contains a clearly
    non-food signal (태풍, 정상회담, 야구, ...) we skip the whole article so
    its innocent-looking sibling tokens (카눈, 북상, ...) don't bleed in.
    Then per-token food-adjacency is applied by the caller to catch any
    residual noise.
    """
    counts: Counter[str] = Counter()
    for item in items:
        title = item.get("title")
        if isinstance(title, str):
            title_text = _HIGHLIGHT_RE.sub("", html.unescape(title))
            if not is_likely_food_adjacent(title_text):
                continue
        for field in ("title", "description"):
            text = item.get(field)
            if not isinstance(text, str):
                continue
            cleaned = _HIGHLIGHT_RE.sub("", html.unescape(text))
            for token in _HANGUL_TOKEN_RE.findall(cleaned):
                counts[token] += 1
    return counts
