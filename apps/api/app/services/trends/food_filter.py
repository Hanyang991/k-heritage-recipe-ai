"""Food-domain keyword filter for open-discovery providers.

Open-discovery sources (Google Trends daily top, Naver news headlines) are
inherently broad — they emit politics, celebs, sports, weather, the whole
catalogue. To plug them into a K-heritage-recipe pipeline we have to filter
down to *food* candidates, and aggressively: false negatives (missing a food
keyword) just mean we miss one trend cycle; false positives ("정치인 이름" in
the trends dashboard) are user-visible and embarrassing.

The filter is therefore a **strict allowlist with a denylist veto**:

1. A candidate is rejected unless at least one allowlist pattern matches.
2. Any denylist match overrides the allowlist and rejects the candidate.

Both lists are tuned for Korean food vocabulary: the allowlist favours
suffix matches that strongly indicate food intent (라떼/에이드/차/디저트
endings, 떡 / 한과 / 강정 nouns, traditional ingredient roots), while the
denylist enumerates high-recurrence non-food categories on Google daily.

This module is provider-agnostic — PR #14 (Naver News) reuses it verbatim.
"""

from __future__ import annotations

import re

# Word-internal patterns ("substring matches"). Anchors are intentional —
# food suffixes are very high precision but only at end-of-word, and food
# prefixes / ingredient roots are typically at start-of-word.
#
# Patterns are matched via ``re.search`` against the keyword (whitespace
# stripped), so the regex itself anchors as needed.

_FOOD_ALLOWLIST_PATTERNS: tuple[str, ...] = (
    # Food category roots — unanchored. Korean compound nouns almost always
    # preserve food semantics ("디저트가게", "라떼맛집"), and the denylist
    # already vetoes ambiguous prefixes like 자동차 / 차량 separately.
    r"라떼",
    r"에이드",
    r"스무디",
    r"쥬스",
    r"음료",
    r"드링크",
    r"밀크티",
    r"버블티",
    r"커피",
    r"디저트",
    r"케이크",
    r"쿠키",
    r"빙수",
    r"마카롱",
    r"타르트",
    r"푸딩",
    r"아이스크림",
    r"젤라또",
    r"파이",
    r"티라미수",
    r"베이커리",
    r"브런치",
    r"카스테라",
    r"크로와상",
    r"식빵",
    # 차 — short bare words like 녹차/헛개차/결명자차 (max 3 hangul + 차);
    # plain "차$" is too permissive (자동차/차량) so anchored against length.
    r"녹차|홍차|보이차|우롱차|허브차|한방차|전통차|민트차|보리차|메밀차|쌍화차",
    r"^[가-힣]{1,3}차$",
    # 빵 — anchored to suffix; ``빵맛집`` etc. pass via the ``맛집`` pattern.
    r"빵$",
    # 크림 — anchored to end ("흑임자크림") to avoid news headlines like
    # "○○크림코리아 합병" matching mid-word
    r"크림$",
    # 전통 한식 / 전통과자 — ingredient or form names, unanchored
    r"인절미",
    r"미숫가루",
    r"흑임자",
    r"송편|절편|찰떡|시루떡|백설기|쑥떡|콩떡|약식|가래떡|모찌떡",
    r"한과|약과|강정|다식|정과|매작과|율란|산자",
    r"식혜|수정과|오미자|매실청?",
    r"누룽지",
    r"단호박|호박죽",
    r"유자청?|모과|대추|생강",
    r"콩가루",
    r"곶감",
    r"인삼|홍삼",
    # 카테고리 키워드 — high precision endings
    r"맛집",
    r"카페",
    r"신메뉴",
    r"한식디저트?",
    r"전통병과|전통과자|전통빵|전통찻집",
    r"레시피",
    r"요리법",
)

# Definite non-food categories. Match anywhere in the keyword.
_FOOD_DENYLIST_PATTERNS: tuple[str, ...] = (
    # 사람 / 연예
    r"배우|아이돌|연예인|가수|MC|진행자",
    r"드라마|영화|콘서트|뮤지컬|예능",
    # 정치
    r"대통령|국회|장관|정치|선거|후보|정부|국정감사|국방",
    # 스포츠
    r"축구|야구|농구|배구|골프|올림픽|월드컵|아시안게임|K리그|KBO|EPL",
    # 사고 / 재난 / 사건
    r"사고|화재|폭우|태풍|지진|사망|사건|범죄|체포|구속",
    # 차량 / 교통
    r"자동차|버스|지하철|기차|항공|비행기|선박",
    # 부동산 / 금융
    r"아파트|분양|부동산|주식|코스피|환율|금리",
    # 디지털 / IT 일반
    r"갤럭시|아이폰|삼성전자|LG전자|네이버|카카오|구글|애플",
    # 게임 / IP
    r"리그오브레전드|롤챔스|배틀그라운드|메이플|디아블로",
    # 의료 / 보건
    r"코로나|독감|백신|약물|치료제",
)


_ALLOWLIST_RE: re.Pattern[str] = re.compile("|".join(_FOOD_ALLOWLIST_PATTERNS))
_DENYLIST_RE: re.Pattern[str] = re.compile("|".join(_FOOD_DENYLIST_PATTERNS))


def is_food_keyword(keyword: str) -> bool:
    """``True`` iff ``keyword`` matches the food allowlist *and* not the denylist.

    Whitespace inside the keyword is collapsed before matching so multi-word
    queries like "쑥 라떼 추천" still hit the ``라떼$`` pattern via the
    normalised "쑥라떼추천" view (the original keyword is returned verbatim
    by ``filter_food_keywords``).
    """
    if not keyword:
        return False
    normalised = "".join(keyword.split())
    if _DENYLIST_RE.search(normalised):
        return False
    return bool(_ALLOWLIST_RE.search(normalised))


def filter_food_keywords(keywords: list[str]) -> list[str]:
    """Return the subset of ``keywords`` that pass ``is_food_keyword``, order preserved."""
    return [k for k in keywords if is_food_keyword(k)]
