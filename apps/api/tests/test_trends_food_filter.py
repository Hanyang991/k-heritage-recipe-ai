"""Tests for the denylist-only open-discovery candidate filter.

Philosophy under test: we want **novelty trends** like 두바이쫀득쿠키,
탕후루, 마라맛, 트러플오일 to pass through so PR #15's Gemini layer can
suggest 한식 변형 (e.g. 두바이강정, 탕후루약과). The filter only rejects
*obviously* non-food categories.
"""

from __future__ import annotations

import pytest

from app.services.trends.food_filter import filter_food_adjacent, is_likely_food_adjacent

# ---------------------------------------------------------------------------
# Novelty / emerging food trends — MUST pass (this is the whole point)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "keyword",
    [
        # 신상 컨셉 — geographic/cultural
        "두바이쫀득쿠키",
        "두바이초콜릿",
        "두바이",
        "이탈리아 디저트",
        "베트남 커피",
        "프랑스 디저트",
        # 신상 컨셉 — flavors / textures
        "탕후루",
        "마라맛",
        "마라탕후루",
        "트러플오일",
        "트러플",
        "흑당버블티",
        "쫀득",
        "꾸덕",
        "바삭",
        # 콜라보 / 시즌
        "스타벅스 신메뉴",
        "한정판 콜라보",
        "신메뉴",
        "챌린지",
        # 기존 watchlist 어휘도 당연히 통과
        "쑥라떼",
        "흑임자라떼",
        "유자에이드",
        "헛개차",
        "약과아이스크림",
        "흑임자빙수",
        "쌀티라미수",
        "송편",
        "백설기",
        "약과",
        "강정",
        "다식",
        "수정과",
        "식혜",
        # 음식 인접한 일반 단어 — 통과 (downstream blended scoring filters noise)
        "한정",
        "콜라보",
        "신상",
    ],
)
def test_passes_novel_and_known_food_concepts(keyword: str) -> None:
    assert is_likely_food_adjacent(keyword), f"expected pass: {keyword!r}"


# ---------------------------------------------------------------------------
# Obviously non-food — MUST be rejected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "keyword",
    [
        # 사람 / 연예 (actions, not bare names — bare names pass through)
        "BTS 컴백",
        "블랙핑크 신곡",
        "○○ 배우 결혼",
        "오징어게임 드라마",
        "팬미팅 일정",
        "데뷔 5주년",
        "열애설 폭로",
        # 정치
        "윤석열 대통령",
        "국회 본회의",
        "총선 후보",
        "한미 정상회담",
        # 스포츠 — match denylist category words (categories, competitions,
        # results). Bare 'name + 골/3루타/포핸드' style queries can still leak
        # past the filter (no allowlist to require positive food evidence);
        # the downstream blended score + PR #15 Gemini are the safety nets.
        "두산 야구",
        "올림픽 메달",
        "K리그 우승",
        "월드컵 결승",
        "박세리 골프",
        "손흥민 EPL",
        # 사고 / 사건 / 날씨
        "강남 사고",
        "산불 화재",
        "태풍 카눈",
        "폭염 경보",
        "폭설 주의",
        # 차량 / 교통
        "테슬라 자동차",
        "공항 항공기",
        "전기차 보조금",
        # 부동산 / 금융
        "강남 아파트",
        "코스피 종가",
        "공모주 청약",
        # IT — specific products (NOT bare brands)
        "갤럭시 S25",
        "아이폰 17",
        "삼성전자 실적",
        "AirPods Pro",
        "PS5 출시",
        "넷플릭스 신작",
        # 게임
        "롤챔스 결승",
        "배틀그라운드 업데이트",
        # 의료
        "코로나 재유행",
        "독감 백신",
    ],
)
def test_rejects_clearly_non_food(keyword: str) -> None:
    assert not is_likely_food_adjacent(keyword), f"expected reject: {keyword!r}"


# ---------------------------------------------------------------------------
# Bare brand names — ambiguous, MUST pass (food contexts exist)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "keyword",
    [
        # Brands are NOT in the denylist because they can appear in food
        # contexts (e.g. "스타벅스 라떼", "네이버 카페", "삼성동 디저트").
        "삼성",
        "삼성동 라떼맛집",
        "네이버",
        "네이버 카페",
        "카카오",
        "카카오 콜라보",
        "스타벅스",
        "스타벅스 콜라보",
    ],
)
def test_bare_brand_names_pass_through(keyword: str) -> None:
    assert is_likely_food_adjacent(keyword)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_rejects_empty_or_whitespace() -> None:
    assert not is_likely_food_adjacent("")
    assert not is_likely_food_adjacent("   ")
    assert not is_likely_food_adjacent("\t\n")


def test_whitespace_inside_keyword_is_collapsed() -> None:
    """Multi-word phrases match denylist after whitespace stripping."""
    assert not is_likely_food_adjacent("자 동 차 신차")
    assert not is_likely_food_adjacent("월 드 컵 결 승")


def test_filter_preserves_order() -> None:
    inputs = ["BTS 신곡", "쑥라떼", "태풍 카눈", "두바이쫀득쿠키", "축구 우승"]
    assert filter_food_adjacent(inputs) == ["쑥라떼", "두바이쫀득쿠키"]


def test_filter_handles_empty_list() -> None:
    assert filter_food_adjacent([]) == []


def test_filter_returns_all_when_nothing_matches_denylist() -> None:
    inputs = ["탕후루", "마라맛", "트러플오일"]
    assert filter_food_adjacent(inputs) == inputs


# ---------------------------------------------------------------------------
# Denylist veto regression — anything containing 자동차 etc. is dead
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "keyword",
    [
        "전기 자동차 보조금",
        "현대차 신차",
        "고급 아파트 청약",
        "코스피 상한가",
    ],
)
def test_denylist_match_inside_compound_rejects(keyword: str) -> None:
    assert not is_likely_food_adjacent(keyword)


# ---------------------------------------------------------------------------
# Noise-cleanup regressions — concrete leaks observed against the live
# Google Trends RSS feed (see todo.md item "Google Trends Daily 비음식
# 토큰 정리"). Each case here represents a real-world top-of-feed entry
# that was bleeding into the merged candidate pool before this PR.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "keyword",
    [
        # 경제 / 거시지표 — bare "경제"/"예산"/"부채" stay through (food contexts
        # exist), but concrete macro vocabulary is dead.
        "가계부채",
        "가계부채 증가",
        "국가부채 사상 최대",
        "부채비율 악화",
        "GDP 성장률",
        "gdp 발표",
        "GNP 회복",
        "실업률 3.5%",
        "고용률 발표",
        "일자리 정책",
        "인플레이션 둔화",
        "디플레이션 우려",
        "스태그플레이션",
        "재정수지 적자",
        "정부예산 편성",
        "예산안 통과",
        "경제성장률 전망",
        "법정금리 인상",
        "코스피 흑자",
        # 스포츠 — K-league FC matches (mixed case from RSS), KBO 닉네임
        "용인 FC 대 충남 아산 FC",
        "용인FC",
        "수원 FC 경기",
        "전북 fc 승점",
        "FC 서울",
        "두산 베어스",
        "LG 트윈스",
        "KIA 타이거즈",
        "SSG 랜더스",
        "키움 히어로즈",
        "한화 이글스",
        "삼성 라이온즈",
        "롯데 자이언츠",
        "kt 위즈",
        "NC 다이노스",
        "승부차기 결과",
        "K3 승강전",
        "승점 자판",
        "구장 일정",
        # 법조 / 정치 확장
        "윤석열 탄핵",
        "탄핵소추안",
        "검찰 압수수색",
        "법원 판결",
        "체포영장 청구",
        "구속영장 발부",
        "본회의 법안",
        "개정안 통과",
        "청문회 일정",
        "영장기각",
        # 군사 / 전쟁
        "우크라이나 전쟁",
        "미사일 발사",
        "드론 공습",
        "전투기 출격",
        "군부 쿠데타",
        "휴전 합의",
        "핵실험 의혹",
        # 영화 / 연예 확장
        "영화제 일정",
        "시사회 후기",
        "예매율 1위",
    ],
)
def test_rejects_noise_leaks_from_live_google_trends(keyword: str) -> None:
    assert not is_likely_food_adjacent(keyword), f"expected reject: {keyword!r}"


@pytest.mark.parametrize(
    "keyword",
    [
        # Words that *contain* a non-food-looking substring but are real
        # food / food-adjacent — must NOT be rejected just because of a
        # naive substring overlap.
        "분짜",  # Vietnamese bún chả (literal food). NOTE: a 1-char diff
        # away from "분짠" — we add ``짜라위`` to the bare-name denylist
        # rather than ``분짠`` itself, precisely to keep this case passing.
        "베트남 분짜",
        "부채살",  # cattle blade — overlaps "부채" but bare "부채" is not denylisted
        "예산 결혼식 비빔밥",  # "예산" alone passes; "결혼" is denylisted via 결혼/이혼/열애 — bug? assert intentionally
        "신곡동 맛집",  # 신곡 is a real Seoul neighbourhood
    ],
)
def test_documented_limitations_and_safe_overlaps(keyword: str) -> None:
    """Either intentionally passes, or known-limitation case.

    Cases marked with the 결혼 substring still get rejected — that's the
    existing denylist behaviour we preserve. Cases without any denylist
    overlap (분짜, 부채살, 신곡동 맛집) demonstrate the filter is surgical,
    not over-broad.
    """
    if "결혼" in keyword or "이혼" in keyword:
        # 결혼/이혼 stays on the celeb denylist — overlap with food
        # phrases is expected and acceptable.
        assert not is_likely_food_adjacent(keyword)
    else:
        assert is_likely_food_adjacent(keyword), f"expected pass: {keyword!r}"


# ---------------------------------------------------------------------------
# Bare proper-name denylist (PR #26) — names that historically leaked into
# the open-discovery candidate pool with no category cue. Documented
# limitation from PR #20 ("Korean person-name leak — passes through") is
# closed for the most frequently-leaked names.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "keyword",
    [
        # 영화감독 — PR #20 docstring's original "홍상수" example
        "홍상수",
        "박찬욱",
        "봉준호",
        "이창동",
        "김지운",
        # 가수 / K-pop solo
        "지드래곤",
        "박효신",
        "임영웅",
        # 정치인 (bare name without cue)
        "이재명",
        "한동훈",
        "윤석열",
        "한덕수",
        # 야구 선수
        "박찬호",
        "류현진",
        "오타니",
        # 축구 선수
        "손흥민",
        "이강인",
        "김민재",
        # 골프
        "박세리",
        "고진영",
        # 감독 — todo.md "홍상수 / 김상식 / 김대호 / 정해영" 사례
        "김상식",
        "김대호",
        "정해영",
        "허정무",
        "클린스만",
        # 예능 / MC
        "유재석",
        "강호동",
        # 외국 인명 transliteration — PR #20 docstring's "짜라위 분짠"
        "짜라위",
        "짜라위 분짠",  # the original limitation example
        "트럼프",
        "푸틴 회담",  # paired with 회담 → denylist hits via 회담 anyway, but verify
        "젤렌스키",
        "시진핑",
        "네타냐후",
    ],
)
def test_rejects_bare_person_names(keyword: str) -> None:
    """Bare names from `_BARE_PERSON_NAME_DENYLIST` (PR #26) are rejected."""
    assert not is_likely_food_adjacent(keyword), f"expected reject: {keyword!r}"


@pytest.mark.parametrize(
    "keyword",
    [
        # Food / location words that *share Korean surname syllables* with
        # denylisted names — must NOT be over-rejected. These collisions
        # are what we designed the 3+ syllable bare-name list around.
        "홍어",  # shares 홍 with 홍상수
        "홍어무침",
        "박하",  # shares 박 with 박찬욱
        "박하사탕",
        "이밥",  # shares 이 with 이재명/이창동
        "조청",  # shares 조 with no name in our list anyway
        "정과",  # shares 정 with 정해영
        "정한수",  # shares 정 with 정해영
        "임실치즈",  # shares 임 with 임영웅
        "강정",  # shares 강 with 강호동
        "최정상의 약과",  # 최정 prefix — 2-char names intentionally excluded
        "한과",  # shares 한 with 한동훈/한덕수
        "한식",
        "김치찌개",  # shares 김 with 김민재/김상식 등
        "김밥",
        "푸딩",  # shares 푸 with 푸틴 — 2-char names excluded for this reason
        "분짜",  # 1 char diff from 분짠 — proves we denylisted 짜라위 not 분짠
        # 호 / 환 surname syllables
        "유자에이드",  # shares 유 with 유재석
        "유자청",
        # Korean compound words that contain a denylisted name as substring
        # MUST be rare and intentional. None of the names we picked appear
        # inside common food/location compounds.
    ],
)
def test_bare_name_denylist_does_not_over_reject_food(keyword: str) -> None:
    """Surname-syllable food words must pass — denylist is exact-name, not surname-prefix."""
    assert is_likely_food_adjacent(keyword), f"expected pass: {keyword!r}"


def test_fc_lookaround_does_not_match_english_compounds() -> None:
    """``FC`` only fires when it is a standalone bigram next to non-English chars.

    This guards against bystander English compounds (UNICEF, MFC, PFC) — they
    contain ``FC`` but should not be treated as football clubs.
    """
    # PFC / MFC / UNICEF: ``FC`` is flanked by English letters → not a match.
    assert is_likely_food_adjacent("PFC 단백질")
    assert is_likely_food_adjacent("UNICEF 캠페인 음식")
    # Korean+FC+Korean: clear K-league match → reject.
    assert not is_likely_food_adjacent("용인FC대충남아산FC")
    assert not is_likely_food_adjacent("FC서울")


def test_ignorecase_flag_catches_lowercase_abbreviations() -> None:
    """RSS sometimes emits lowercase ``fc``/``epl``/``gdp``."""
    assert not is_likely_food_adjacent("용인fc")
    assert not is_likely_food_adjacent("epl 결승")
    assert not is_likely_food_adjacent("gdp 회복")
    assert not is_likely_food_adjacent("mlb 결승")
