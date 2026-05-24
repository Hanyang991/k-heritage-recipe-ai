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


# ---------------------------------------------------------------------------
# Macro / brand 노이즈 (PR #27) — broader categories that historically
# leaked: 정부 지출 (교부금 / 보조금 / 지원금), 무역/세제 (관세인상 /
# 무역수지 / 부가가치세), 외국 자동차 브랜드 (테슬라 / 벤츠 / BMW),
# 암호화폐 (비트코인 / 이더리움 / 업비트), 항공우주 (누리호 / SpaceX).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "keyword",
    [
        # 정부 지출 / 세제 / 무역
        "지방교부금 삭감",
        "특별교부금 편성",
        "보통교부금",
        "긴급재난지원금",
        "재난지원금 지급",
        "보조금 정책",
        "장려금 지원",
        "무역수지 흑자",
        "경상수지 적자",
        "수출액 증가",
        "수입액 감소",
        "수출입 통계",
        "관세인상 발표",
        "관세협상 타결",
        "관세부과 결정",
        "관세인하 영향",
        "부가가치세 인상",
        "법인세 감세",
        "소득세 개편",
        "재산세 인상",
        "종부세 폐지",
        "상속세 개편",
        "외환보유고 축소",
        "외환위기 우려",
        "외환시장 변동성",
        # 외국 자동차 브랜드
        "테슬라 주가",
        "테슬라 모델Y 출시",
        "토요타 신차",
        "혼다 하이브리드",
        "닛산 리콜",
        "폭스바겐 배출가스",
        "벤츠 한국법인",
        "BMW 시승",
        "bmw 신형",
        "아우디 A7",
        "포르쉐 타이칸",
        "페라리 신차",
        "람보르기니 우라칸",
        "볼보 XC90",
        "렉서스 ES",
        "사이버트럭 출시",
        "모델3 가격",
        "모델X 리뷰",
        # 암호화폐 / 가상자산
        "비트코인 가격",
        "이더리움 ETF",
        "도지코인 펌프",
        "리플 SEC",
        "솔라나 폭락",
        "알트코인 시즌",
        "스테이블코인 규제",
        "가상자산 과세",
        "가상화폐 거래소",
        "암호화폐 시장",
        "디지털자산 규제",
        "NFT 발행",
        "업비트 상장",
        "빗썸 점검",
        "코인베이스 IPO",
        "바이낸스 대규모 인출",
        "크라켄 거래소",
        # SNS / 글로벌 IT (식품 컨텍스트 낮은 것만)
        "트위터 인수",
        "메타플랫폼 실적",
        "페이스북 광고",
        "텔레그램 차단",
        "왓츠앱 신기능",
        # 항공우주
        "누리호 발사",
        "다누리 궤도",
        "스페이스X 발사",
        "SpaceX Starship",
        "spacex 발사",
        "로켓발사 일정",
        "위성발사 성공",
        "우주왕복선 컬럼비아",
        "우주정거장 도킹",
    ],
)
def test_rejects_macro_and_brand_noise(keyword: str) -> None:
    """Broader macro/brand noise (PR #27) — gov spending, foreign car brands,
    crypto, space sector all rejected."""
    assert not is_likely_food_adjacent(keyword), f"expected reject: {keyword!r}"


@pytest.mark.parametrize(
    "keyword",
    [
        # 식품 어휘와 collision 가능했던 단어들 — 의도적으로 통과 시키도록
        # 설계됨. 새로 추가된 macro/brand 패턴이 식품을 over-reject 하면
        # 이 테스트가 실패한다.
        #
        # 로켓 → 로켓샐러드 (루콜라) 식품 — bare "로켓" 은 denylist X
        "로켓샐러드",
        "로켓 샐러드",
        "로켓 잎",
        # 애플 → 애플파이 / 애플망고 — bare "애플" 은 denylist X
        "애플파이",
        "애플망고",
        "사과 애플 디저트",
        # 수출 단독은 식품에 합법적으로 등장 — "수출액" 형태만 denylist
        "김치 수출",
        "한국 김치 수출",
        "수출 김치",
        "수출 농산물",
        # 발사 단독은 placebo 충돌 가능 — 합성어 형태만 denylist
        "발사대 빵집",
        "오픈 발사 디저트",
        # 무역 단독은 식품 어휘에 등장 가능 ("무역항 어시장")
        "무역항 어시장",
        # 인스타 / 틱톡 / 유튜브 / 애플 / 아마존 / 구글은 식품 컨텍스트 있어 의도적 제외
        "인스타 핫플",
        "인스타그램 인기 카페",
        "틱톡 인기 음식",
        "틱톡 라떼",
        "유튜브 먹방",
        "구글 검색 떡볶이",
        "아마존 식품",
        # 보조금 / 지원금 자체는 의도적 reject 하지만 카페 보조금은 흔치 않음
        # → 단어 자체에 macro 의도가 있어 reject 됨 (의도된 동작).
        # 대신 단어 안에 보조금/지원금이 substring 으로 들어가지 않는
        # 식품 어휘 (예: 후원, 협찬) 는 통과해야 함.
        "후원 시식회",
        "협찬 카페",
        # 종부세 → 종 substring 충돌 가능: 종이 식초, 종합검진 등
        "종합 디저트 박람회",  # 종합 != 종부세 (다른 substring)
        "종이컵 라떼",
        # 외환 → 외환 외 다른 합성 없음, 별 collision 없음 — 통과 확인
        # 관세 단독 substring → 관세인하 등 합성만 denylist
        "관세청 인근 맛집",  # 관세청 != 관세인상/인하 — but 관세인상 substring 안에 "관세" 있어도 안전
        # NFT 충돌: "NFT" 가 substring 으로 등장하는 식품 단어는 사실상 없음
        # 가상 substring: 가상화폐 만 denylist, 가상 단독은 OK
        "가상 시식회",
    ],
)
def test_macro_brand_denylist_does_not_over_reject_food(keyword: str) -> None:
    """Broader macro/brand additions (PR #27) must not over-reject food/cafe words."""
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


# ---------------------------------------------------------------------------
# PR #28 — Bare 지명 / 산업 / 예능 / 추가 인명 leaks observed in live RSS
# during the multi-source open-discovery refresh. Each block is anchored
# carefully so the new patterns do NOT regress the existing novelty cases
# (``이탈리아 디저트``, ``베트남 커피``, ``프랑스 디저트``, ``두바이쫀득쿠키``).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "keyword",
    [
        # bare 국가/지역명 — RSS 1순위 leaks
        "홍콩",
        "대만",
        "미국",
        "중국",
        "유럽",
        "영국",
        "독일",
        "러시아",
        "이탈리아",
        "베트남",
        "프랑스",
        "일본",
        "싱가포르",
        "호주",
        "캐나다",
        "인도",
        "스페인",
        "튀르키예",
    ],
)
def test_rejects_bare_country_names(keyword: str) -> None:
    """Bare 국가명 (라이브 RSS 에서 leak 된 ``홍콩`` 등) 은 거부.

    ``두바이`` 는 *의도적으로* 이 리스트에서 제외 — ``두바이쫀득쿠키`` 같이
    이 코드베이스의 상징적 novelty trend 라 bare ``두바이`` 도 통과시킨다.
    """
    assert not is_likely_food_adjacent(keyword), f"expected reject: {keyword!r}"


@pytest.mark.parametrize(
    "keyword",
    [
        # 합성 food 컨텍스트는 여전히 통과해야 함 — ``^...$`` 앵커링이 핵심.
        "이탈리아 디저트",
        "베트남 커피",
        "프랑스 디저트",
        "홍콩식 디저트",
        "홍콩 라면",
        "미국식 도넛",
        "중국식 만두",
        "일본 라멘",
        "일본식 카레",
        "독일 빵",
        "이탈리아 파스타",
        "스페인 츄러스",
        # 두바이 + 두바이쫀득쿠키 도 그대로 통과 (의도된 한정 제외)
        "두바이",
        "두바이쫀득쿠키",
        "두바이초콜릿",
        # 인도 카레 등 — bare ``인도`` 는 reject 지만 ``인도 카레`` 는 통과
        "인도 카레",
    ],
)
def test_country_compound_phrases_still_pass(keyword: str) -> None:
    """국가명 + 음식 어휘 합성은 whitespace-strip 후에도 ``^국가명$`` 에 안 걸려 통과."""
    assert is_likely_food_adjacent(keyword), f"expected pass: {keyword!r}"


@pytest.mark.parametrize(
    "keyword",
    [
        # bare 산업/카테고리 — 라이브 RSS leaks (``뷰티`` 가 16위였음)
        "뷰티",
        "패션",
        "명품",
        "화장품",
        "의류",
        "가전",
        "건설",
        "반도체",
        "이차전지",
        "배터리",
        "중소기업",
        "버킨백",
    ],
)
def test_rejects_bare_industry_categories(keyword: str) -> None:
    assert not is_likely_food_adjacent(keyword), f"expected reject: {keyword!r}"


@pytest.mark.parametrize(
    "keyword",
    [
        # 산업명 + 음식 합성은 통과해야 함 (whitespace-strip 후 ``^산업명$`` 에 안 걸림)
        "뷰티 디저트",  # 신선 컨셉
        "패션 카페",
        "명품 디저트",
        # ``김치`` 류 식품은 그대로
        "김치찌개",
        "비빔밥",
        # ``배터리`` 단독 reject 지만 ``배터리`` 가 substring 으로 들어간 식품 어휘
        # 는 사실상 없음 — 안전성 검증
        "에너지 디저트",
        "충전 카페",
    ],
)
def test_industry_compounds_still_pass(keyword: str) -> None:
    assert is_likely_food_adjacent(keyword), f"expected pass: {keyword!r}"


@pytest.mark.parametrize(
    "keyword",
    [
        # 예능 / TV 프로그램 (음식 컨셉 자주 등장하지만 *프로그램명* 자체는 trend 아님)
        "편스토랑",
        "편스토랑 출연",
        "런닝맨",
        "무한도전 레전드",
        "놀면뭐하니",
        "복면가왕",
        "미운우리새끼",
        "아는형님",
        "유퀴즈온더블록",
    ],
)
def test_rejects_tv_program_names(keyword: str) -> None:
    assert not is_likely_food_adjacent(keyword), f"expected reject: {keyword!r}"


@pytest.mark.parametrize(
    "keyword",
    [
        # PR #28 에서 새로 추가된 bare names — 라이브 RSS 에서 leak 됨
        "박형룡",
        "박형룡 신학자",
        "송일국",
        "도경완",
        "이동국",
        "이동국 인터뷰",
    ],
)
def test_rejects_pr28_bare_names(keyword: str) -> None:
    assert not is_likely_food_adjacent(keyword), f"expected reject: {keyword!r}"


@pytest.mark.parametrize(
    "keyword",
    [
        # 새 bare-name 들이 surname syllable / food 어휘를 over-reject 하면 안됨.
        # ``박형룡`` 에 들어간 ``박`` / ``박형`` / ``형룡`` substring 충돌 가능 검증.
        "박하사탕",  # 박 surname share
        "박찬호",  # 이미 denylist 에 있음 → reject 이지만 다른 이유
        "이밥",  # 이 surname share
        "송편",  # 송 surname share with 송일국
        "송편타르트",
        "도라지청",  # 도 surname share with 도경완
        "동치미",  # 동 surname share with 이동국 (substring ``동국`` 없음)
    ],
)
def test_pr28_bare_names_do_not_over_reject(keyword: str) -> None:
    """새로 추가된 bare-name 들이 식품 어휘를 over-reject 하지 않는지."""
    if keyword == "박찬호":
        # 이미 PR #26 denylist 에 있음
        assert not is_likely_food_adjacent(keyword)
    else:
        assert is_likely_food_adjacent(keyword), f"expected pass: {keyword!r}"
