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
  weather events, games, medical, military, legal proceedings).
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

Known limitations
-----------------
- **Bare proper names not in the maintained denylist.** Category-pattern
  matching catches names paired with role cues (``홍상수 영화감독`` →
  ``감독``; ``손흥민 EPL`` → ``EPL``), and the curated
  ``_BARE_PERSON_NAME_DENYLIST`` below catches the most frequently-leaked
  bare names (Korean film directors / politicians / athletes / foreign
  transliterations). Brand-new names not yet on that list still pass
  through. Blended scoring against the Naver DataLab series already sinks
  most of them, and PR #15's LLM expansion does not surface 한식 변형 for
  bare proper names — the curated list is belt-and-suspenders.
"""

from __future__ import annotations

import re

# Definite non-food categories. Match anywhere in the keyword after
# whitespace normalisation. Bias: be confident before adding — a pattern
# here means *we believe this is never a food trend in Korea*.
#
# Patterns are compiled with ``re.IGNORECASE`` so English abbreviations
# (``FC``, ``EPL``, ``GDP``) match regardless of source casing — Google
# Trends RSS sometimes emits lowercase ``fc`` between Korean tokens.
_FOOD_DENYLIST_PATTERNS: tuple[str, ...] = (
    # 사람 / 연예 — actions and roles rather than bare names (bare names
    # are hard to denylist reliably without a known-person list).
    r"배우|아이돌|연예인|가수|MC|진행자|감독|연출",
    r"드라마|영화|콘서트|뮤지컬|예능|시상식|팬미팅|뮤직비디오|영화제|시사회|예매율",
    # ``신곡`` (new song) but not ``신곡동`` (real Seoul/Goyang neighbourhood
    # that legitimately appears in food trends — "신곡동 맛집").
    r"신곡(?!동)|컴백|데뷔|결혼|이혼|열애|스캔들|논란|폭로|구설",
    # 정치
    r"대통령|총리|장관|국회|의원|정치|선거|대선|총선|지방선거|후보|정부",
    r"외교|국정감사|국방|회담|정상회담|대선후보",
    r"법안|개정안|입법|발의|상정|본회의|법사위|청문회",
    # 법조 / 사법
    r"탄핵|판결|법원|검찰|체포영장|구속영장|공판|소송|불구속|영장기각|개표",
    # 군사 / 전쟁
    r"전쟁|군사|군부|쿠데타|내전|휴전|정전협정|작전",
    r"미사일|드론|폭격|전투기|군용기|장갑차|함정|핵실험|핵무기",
    # 스포츠 — categories and competitions
    r"축구|야구|농구|배구|골프|올림픽|월드컵|아시안게임",
    r"K리그|KBO|EPL|NBA|MLB|NPB|UCL|코파아메리카",
    r"우승|준우승|메달|금메달|은메달|동메달|결승|준결승|예선",
    # 스포츠 — KBO 닉네임 + 구단/경기 운영 어휘. ``FC`` is checked with
    # explicit lookaround so it doesn't trip on Korean characters that
    # happen to neighbour the bigram. ``AFC`` (Asian Football
    # Confederation) is intentionally not matched — the lookbehind on a
    # preceding English letter blocks it, and AFC alone is rare in
    # Korean food trends regardless.
    r"베어스|타이거즈|랜더스|트윈스|위즈|히어로즈|자이언츠|이글스|다이노스|라이온즈|키움|두산|kt위즈|nc다이노스",
    r"구단|구장|승점|득점|선수단|연고팀|연고지|승강전|승부차기|경기일정|시즌권",
    r"(?<![A-Za-z0-9])FC(?![A-Za-z0-9])",
    # 사고 / 재난 / 사건
    r"사고|화재|폭우|태풍|지진|쓰나미|사망|사건|범죄|체포|구속|구조|사상자",
    r"폭염|한파|폭설|장마|우박|황사",
    # 차량 / 교통 — bare ``자동차``/``전기차`` already covers most leaks;
    # add foreign-brand wordmarks (PR #27) so headlines like ``테슬라
    # 모델Y 출시`` get dropped even if neither token matched the bare
    # category. Domestic ``현대차`` stays separate below — bare ``현대``
    # would over-reject (현대상회 식료품 등).
    r"자동차|버스|지하철|기차|항공|비행기|선박|전기차|하이브리드|운전|면허",
    r"테슬라|토요타|혼다|닛산|폭스바겐|벤츠|BMW|아우디|포르쉐|페라리|람보르기니|볼보|렉서스",
    r"사이버트럭|모델Y|모델S|모델3|모델X",
    # 부동산 / 금융
    r"아파트|분양|부동산|매매|청약|입주",
    r"주식|코스피|코스닥|환율|금리|시총|IPO|공모주|상한가|하한가|종가",
    # 암호화폐 / 가상자산 (PR #27) — 한국 트렌드 RSS 의 단골 leak.
    # 식품 어휘와 collision 위험이 거의 없음 (``비트코인 떡볶이`` 같은
    # 컨셉 store 가 없다는 가정 — 생기면 다시 평가).
    r"비트코인|이더리움|도지코인|리플|솔라나|알트코인|스테이블코인",
    r"가상자산|가상화폐|암호화폐|디지털자산|NFT",
    r"업비트|빗썸|코인베이스|바이낸스|크라켄",
    # 경제 / 거시지표 — concrete macro vocabulary, not bare 경제/예산
    # which can leak into food contexts (e.g. ``결혼식 예산``).
    r"가계부채|채무|부채비율|국가부채|적자|흑자|GDP|GNP|물가상승|인플레이션|디플레이션|스태그플레이션",
    r"재정수지|예산안|국가예산|정부예산|경제성장률|실업률|고용률|일자리|법정금리",
    # 정부 지출 / 세제 / 무역 (PR #27) — bare ``수출`` 은 ``김치 수출``
    # 같은 합법 식품 trend 와 collision 위험이 있어 제외. 대신 ``수출액
    # / 무역수지 / 관세인상`` 같은 **macro 형용 + 수출** 형태만 포함.
    r"교부금|지방교부금|특별교부금|보통교부금",
    r"지원금|보조금|장려금|재난지원금|긴급재난지원금",
    r"무역수지|경상수지|무역적자|무역흑자|수출액|수입액|수출입|관세인상|관세협상|관세부과|관세인하",
    r"부가가치세|법인세|소득세|재산세|종합부동산세|종부세|상속세|증여세",
    r"외환보유고|외환위기|외환시장",
    # IT — specific product / category names (NOT bare brand names like
    # "삼성"/"네이버"/"카카오" because those legitimately appear in food
    # contexts: "삼성동 라떼맛집", "네이버 카페 신메뉴").
    r"갤럭시|아이폰|스마트폰|노트북|모니터|이어폰|AirPods|에어팟",
    r"삼성전자|LG전자|SK하이닉스|현대차",
    r"PS5|닌텐도|엑스박스|Xbox",
    r"넷플릭스|디즈니플러스|티빙|웨이브|쿠팡플레이",
    # SNS / 글로벌 IT (PR #27) — 식품 컨텍스트 (``인스타 핫플`` / ``틱톡
    # 인기 음식``) 가 있는 플랫폼은 의도적 제외. 식품 관련성 거의 없는
    # 것만.
    r"트위터|메타플랫폼|페이스북|텔레그램|왓츠앱",
    # 게임 / IP
    r"리그오브레전드|롤챔스|배틀그라운드|메이플|디아블로|스타크래프트|오버워치",
    # 항공우주 (PR #27) — ``로켓`` 단독은 ``로켓샐러드``(루콜라) 와
    # collision 이라 제외. ``발사`` 도 ``발사대 빵집`` 등 placebo
    # collision 가능성 — 합성어만 포함.
    r"누리호|다누리|스페이스X|SpaceX|로켓발사|위성발사|우주왕복선|우주정거장",
    # 의료 / 보건
    r"코로나|독감|백신|치료제|확진|감염",
)


# Bare proper-name denylist — names that historically leaked into the
# open-discovery candidate pool (Google Trends RSS, Naver News) without
# a category cue like ``감독`` / ``의원`` / ``선수`` next to them. Each
# entry is verified to be at least 3 syllables (avoids accidental
# substring collisions like ``푸 + 딩``) and has no overlap with known
# Korean food vocabulary (``홍상수`` does not substring-match ``홍어``;
# ``박찬호`` does not substring-match ``박하``; etc.).
#
# Maintenance: when a new bare-name leak is observed in live RSS, add
# it here. The downstream blended scorer + LLM expansion already filter
# most of these naturally; this list is belt-and-suspenders so the
# merged candidate pool stays clean even before scoring.
#
# Intentionally *not* included:
# * 먹방 유튜버 (쯔양, 햄지 등) — they are legitimately food-adjacent.
# * 2-syllable names — too high collision risk with Korean food words
#   (e.g. ``푸틴`` could feasibly substring-match new compounds).
# * Common Korean surname-only tokens (김, 이, 박 …) — would over-reject
#   김치 / 박하사탕 / 이밥 etc.
_BARE_PERSON_NAME_DENYLIST: tuple[str, ...] = (
    # 영화감독 / 영화인
    "홍상수",
    "박찬욱",
    "봉준호",
    "이창동",
    "김지운",
    "류승완",
    "허진호",
    "장준환",
    "임권택",
    # 가수 / K-pop / 아이돌 (개인 이름 단독으로 자주 등장)
    "지드래곤",
    "박효신",
    "임영웅",
    "성시경",
    "이찬원",
    "장민호",
    "박재범",
    # 정치인 (bare names — 의원/대통령 cue 없이 자주 노출)
    "이재명",
    "한동훈",
    "윤석열",
    "이낙연",
    "추미애",
    "한덕수",
    "원희룡",
    "오세훈",
    "이준석",
    # 야구 선수
    "박찬호",
    "류현진",
    "김광현",
    "양현종",
    "이정후",
    "오타니",
    "김하성",
    # 축구 선수
    "손흥민",
    "이강인",
    "김민재",
    "황희찬",
    "황의조",
    # 골프 / 기타 종목
    "박세리",
    "고진영",
    "김주형",
    # 야구 / 농구 / 축구 감독 — todo.md "홍상수 / 김상식 / 김대호 / 정해영" 사례
    "김상식",
    "김대호",
    "정해영",
    "허정무",
    "신태용",
    "클린스만",
    "유재학",
    "전창진",
    # MC / 예능인 (먹방 진행자는 의도적으로 제외)
    "유재석",
    "강호동",
    "이수근",
    "신동엽",
    "김구라",
    "전현무",
    # 외국 인명 transliteration (Hangul) — PR #20 limitation
    # ``짜라위 분짠`` 의 ``짜라위`` 만 추가하면 됨: ``분짠`` 은 식품 ``분짜``
    # (Vietnamese bún chả) 와 1글자 차이라 substring 위험.
    "짜라위",
    "트럼프",
    "젤렌스키",
    "시진핑",
    "기시다",
    "이시바",
    "네타냐후",
    "에르도안",
    "마크롱",
)


_DENYLIST_RE: re.Pattern[str] = re.compile(
    "|".join((*_FOOD_DENYLIST_PATTERNS, *(re.escape(n) for n in _BARE_PERSON_NAME_DENYLIST))),
    re.IGNORECASE,
)


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
