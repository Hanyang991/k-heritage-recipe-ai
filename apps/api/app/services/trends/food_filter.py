"""Open-discovery candidate filter — denylist-only, novelty-friendly.

Open-discovery sources (Google daily trends, Naver news headlines) are
*open-domain*: politics, celebs, sports, weather, food, all mixed. We need
to keep the food trends and drop the rest — but the product's whole point
is to detect **emerging novelty** (think "두바이쫀득쿠키", "탕후루",
"마라맛", "트러플오일") so that the LLM stage (PR #15) can suggest
modernised traditional Korean variants (두바이강정, 탕후루약과, …).

A strict allowlist of canonical Korean food vocabulary defeats that:
brand-new flavour / region / format trends never appear in the curated
list, so they'd be rejected before they ever reach the LLM. Instead we
apply a **denylist-only filter**:

- Reject keywords that clearly belong to non-food categories (politics,
  sports, celeb gossip, accidents, tech products, real-estate / finance,
  weather events, games, medical).
- Accept everything else as a *candidate* (hence
  ``is_likely_food_adjacent`` — we're saying it's worth considering, not
  asserting it's food). The downstream blended scorer ranks by Naver
  Datalab series so non-novel noise sinks to the bottom anyway, and the
  PR #15 Gemini layer will be the final judge of "can we turn this into a
  traditional Korean dessert?".

Tradeoff: false positives (occasional non-food candidates that escape the
denylist) are acceptable; false negatives (rejecting a genuine novelty
trend like 두바이쫀득쿠키) are not. When in doubt, **let the keyword
through**.

PR #14 (Naver News) and PR #15 (LLM expansion) reuse this filter verbatim.
"""

from __future__ import annotations

import re

# Definite non-food categories. Match anywhere in the keyword after
# whitespace normalisation. Bias: be confident before adding — a pattern
# here means *we believe this is never a food trend in Korea*.
_FOOD_DENYLIST_PATTERNS: tuple[str, ...] = (
    # 사람 / 연예 — actions and roles rather than bare names (bare names
    # are hard to denylist reliably without a known-person list).
    r"배우|아이돌|연예인|가수|MC|진행자|감독|연출",
    r"드라마|영화|콘서트|뮤지컬|예능|시상식|팬미팅|뮤직비디오",
    r"신곡|컴백|데뷔|결혼|이혼|열애|스캔들|논란|폭로|구설",
    # 정치
    r"대통령|총리|장관|국회|의원|정치|선거|대선|총선|지방선거|후보|정부",
    r"외교|국정감사|국방|회담|정상회담|대선후보",
    # 스포츠 — categories and competitions
    r"축구|야구|농구|배구|골프|올림픽|월드컵|아시안게임",
    r"K리그|KBO|EPL|NBA|MLB|NPB|UCL|코파아메리카",
    r"우승|준우승|메달|금메달|은메달|동메달|결승|준결승|예선",
    # 사고 / 재난 / 사건
    r"사고|화재|폭우|태풍|지진|쓰나미|사망|사건|범죄|체포|구속|구조|사상자",
    r"폭염|한파|폭설|장마|우박|황사",
    # 차량 / 교통
    r"자동차|버스|지하철|기차|항공|비행기|선박|전기차|하이브리드|운전|면허",
    # 부동산 / 금융
    r"아파트|분양|부동산|매매|청약|입주",
    r"주식|코스피|코스닥|환율|금리|시총|IPO|공모주|상한가|하한가|종가",
    # IT — specific product / category names (NOT bare brand names like
    # "삼성"/"네이버"/"카카오" because those legitimately appear in food
    # contexts: "삼성동 라떼맛집", "네이버 카페 신메뉴").
    r"갤럭시|아이폰|스마트폰|노트북|모니터|이어폰|AirPods|에어팟",
    r"삼성전자|LG전자|SK하이닉스|현대차",
    r"PS5|닌텐도|엑스박스|Xbox",
    r"넷플릭스|디즈니플러스|티빙|웨이브|쿠팡플레이",
    # 게임 / IP
    r"리그오브레전드|롤챔스|배틀그라운드|메이플|디아블로|스타크래프트|오버워치",
    # 의료 / 보건
    r"코로나|독감|백신|치료제|확진|감염",
)


_DENYLIST_RE: re.Pattern[str] = re.compile("|".join(_FOOD_DENYLIST_PATTERNS))


def is_likely_food_adjacent(keyword: str) -> bool:
    """``True`` iff ``keyword`` doesn't match any non-food denylist pattern.

    *Adjacent* — not strictly *food*. We deliberately let through novelty
    trends like "두바이쫀득쿠키", "탕후루", "마라맛", "트러플오일",
    "흑당버블티" because the downstream Gemini layer (PR #15) needs them
    to propose 한식 변형 (e.g. 두바이강정, 탕후루약과). Only obviously
    non-food categories are vetoed.

    Whitespace inside the keyword is collapsed before matching so multi-
    word queries are checked against their normalised form.
    """
    if not keyword:
        return False
    normalised = "".join(keyword.split())
    if not normalised:
        return False
    return not _DENYLIST_RE.search(normalised)


def filter_food_adjacent(keywords: list[str]) -> list[str]:
    """Return the subset of ``keywords`` that pass ``is_likely_food_adjacent``."""
    return [k for k in keywords if is_likely_food_adjacent(k)]
