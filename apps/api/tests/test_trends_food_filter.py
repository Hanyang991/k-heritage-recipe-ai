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
