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

Noise reduction (PR ≥17)
------------------------
Live runs (PR #17 smoke) showed two systematic classes of noise leaking
through the regex+denylist pipeline:

1. **Document-frequency artifacts** — a single highly-repetitive article
   could push a one-off token ("조내기") into the top-N just because the
   reporter repeated it. We now track per-article *document frequency*
   alongside raw token count and apply ``min_article_count`` (default 2):
   a token must appear in at least 2 distinct articles to be kept.
2. **Generic news/marketing vocabulary** — stopword-shape Korean tokens
   ("있다", "더욱", "오늘의"), generic categories that match every
   seed query ("디저트", "카페", "음료", "신메뉴"), and news-business
   meta nouns ("브랜드", "트렌드", "출시", "운영") were dominating the
   top-N even though they convey no trend information.
   ``_KOREAN_NEWS_STOPWORDS`` is a conservative explicit denylist for
   these. Specific food keywords ("아이스크림", "커피", "라떼") are NOT
   in this list — they may be over-general but they are real food signal.
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

# Hangul stopword-shape tokens that contribute no trend information.
# Three categories, kept inline so the rationale is obvious in code:
#
# (a) Generic verbs/adverbs/adjectives that survived compound-noun
#     extraction. Removing them avoids news-prose pollution.
# (b) Time and place words — inherently non-food.
# (c) Generic food-news vocabulary that matches every seed query and so
#     trivially dominates frequency tallies ("디저트", "음료", "카페",
#     "신메뉴") plus marketing/business meta-nouns ("브랜드", "트렌드",
#     "출시"). These are real food-adjacent words but they are not
#     *trends* — they are noise around the trends.
_KOREAN_NEWS_STOPWORDS: frozenset[str] = frozenset(
    {
        # (a) verb/adverb/adjective residue
        "있다",
        "없다",
        "있는",
        "없는",
        "한다",
        "됐다",
        "했다",
        "본다",
        "봤다",
        "갔다",
        "왔다",
        "냈다",
        "새롭게",
        "더욱",
        "같은",
        "같이",
        "함께",
        "통해",
        "위한",
        "대한",
        "모두",
        "가장",
        "정말",
        "매우",
        "오는",
        "넘어",
        "특히",
        "또한",
        "다양",
        "다양한",
        "새로운",
        "만든",
        "만든다",
        # (b) time / place
        "오늘",
        "오늘의",
        "어제",
        "내일",
        "이번",
        "이번주",
        "지난",
        "다음",
        "최근",
        "현재",
        "지금",
        "올해",
        "작년",
        "내년",
        "여름",
        "겨울",
        "가을",
        "현지",
        "국내",
        "해외",
        "전국",
        # (c) generic news/marketing meta-vocabulary + seed-query terms
        "디저트",
        "음료",
        "음식",
        "요리",
        "카페",
        "메뉴",
        "신메뉴",
        "신상",
        "인기",
        "추천",
        "베스트",
        "브랜드",
        "트렌드",
        "출시",
        "발표",
        "공개",
        "진행",
        "운영",
        "매장",
        "가게",
        "제품",
        "회사",
        "업체",
        "이벤트",
        "가격",
        "할인",
        "무료",
        "맛집",
        "경험",
        "체험",
        "시간",
        "동안",
        "이상",
        "계속",
        "투자",
        "소비자",
        # (d) PR #28 — 라이브 뉴스 RSS 에서 잔존한 generic prose tokens.
        # 음식 정보 없이 "한식 디저트 *트렌드가* 바뀌고 있다", "*다이닝*
        # 시장의 *시즌* 메뉴" 같은 헤드라인 구조에서 추출되는 토큰들.
        # 음식 어휘 자체 (``디저트`` / ``음료`` / ``카페``) 는 위 (c) 에서
        # 이미 처리됨. 여기는 카테고리/마케팅 어휘 + 조사가 붙은 형태.
        "다이닝",
        "다이닝의",
        "다이닝과",
        "시즌",
        "시즌의",
        "글로벌",
        "글로벌화",
        "푸드",
        "푸드의",
        "식품",
        "업계",
        "업계의",
        "매출",
        "매출액",
        "관계자",
        "전문",
        "전문가",
        "중심",
        "중심으로",
        "통해서",
        "활용",
        "활용한",
        "대표",
        "대표적",
        "트렌드가",
        "트렌드의",
        "트렌드를",
        "트렌드로",
        "디저트와",
        "디저트의",
        "디저트를",
        "음료와",
        "음료의",
        "음료를",
        "카페와",
        "카페의",
    }
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
        min_article_count: int = 2,
        base_url: str = "https://openapi.naver.com",
        timeout: float = 10.0,
    ) -> None:
        self._client_id = client_id or ""
        self._client_secret = client_secret or ""
        self._seed_queries = seed_queries
        self._display_per_query = max(1, min(100, display_per_query))
        self._min_article_count = max(1, min_article_count)
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
        counts, dfs = _extract_token_counts_and_dfs(all_items)
        if not counts:
            return []
        ranked: list[str] = []
        for kw, _ in counts.most_common():
            if dfs[kw] < self._min_article_count:
                continue
            if kw in _KOREAN_NEWS_STOPWORDS:
                continue
            if not is_likely_food_adjacent(kw):
                continue
            ranked.append(kw)
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


def _extract_token_counts_and_dfs(
    items: list[dict[str, Any]],
) -> tuple[Counter[str], Counter[str]]:
    """Return ``(total_freq, article_df)`` for the given article items.

    ``total_freq`` counts every appearance of a token (title + description
    summed). ``article_df`` counts each item at most once per token, which
    is the figure the provider uses for its ``min_article_count`` cutoff
    — a single ranty article repeating one phrase 20 times should not
    qualify that phrase as "trending".

    Headline-level denylist check first: if the title contains a clearly
    non-food signal (태풍, 정상회담, 야구, ...) we skip the whole article so
    its innocent-looking sibling tokens (카눈, 북상, ...) don't bleed in.
    Per-token food-adjacency + stopword filtering happen at the caller.
    """
    counts: Counter[str] = Counter()
    dfs: Counter[str] = Counter()
    for item in items:
        title = item.get("title")
        if isinstance(title, str):
            title_text = _HIGHLIGHT_RE.sub("", html.unescape(title))
            if not is_likely_food_adjacent(title_text):
                continue
        seen_in_item: set[str] = set()
        for field in ("title", "description"):
            text = item.get(field)
            if not isinstance(text, str):
                continue
            cleaned = _HIGHLIGHT_RE.sub("", html.unescape(text))
            for token in _HANGUL_TOKEN_RE.findall(cleaned):
                counts[token] += 1
                seen_in_item.add(token)
        for token in seen_in_item:
            dfs[token] += 1
    return counts, dfs


def _extract_token_counts(items: list[dict[str, Any]]) -> Counter[str]:
    """Legacy thin wrapper returning only the total-frequency counter.

    Tests assert on this shape; the provider uses
    ``_extract_token_counts_and_dfs`` directly.
    """
    counts, _ = _extract_token_counts_and_dfs(items)
    return counts
