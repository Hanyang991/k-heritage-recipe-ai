"""Tests for the food-domain keyword filter."""

from __future__ import annotations

import pytest

from app.services.trends.food_filter import filter_food_keywords, is_food_keyword


@pytest.mark.parametrize(
    "keyword",
    [
        # 음료
        "쑥라떼",
        "흑임자라떼",
        "유자에이드",
        "오미자에이드",
        "한방차라떼",
        "헛개차",
        "오미자차",
        "둥굴레차",
        "녹차",
        "한방차",
        # 디저트
        "약과아이스크림",
        "흑임자빙수",
        "쌀티라미수",
        "전통빵",
        "약과쿠키",
        "단호박케이크",
        "흑임자크림",
        "한식디저트",
        # 전통과자 / 떡
        "송편",
        "백설기",
        "흑임자떡",
        "약과",
        "강정",
        "다식",
        "수정과",
        "식혜",
        # 카테고리 키워드
        "디저트맛집",
        "전통찻집",
        "한식 디저트 카페",  # multi-word with spaces
    ],
)
def test_allows_food_keywords(keyword: str) -> None:
    assert is_food_keyword(keyword), f"expected food: {keyword!r}"


@pytest.mark.parametrize(
    "keyword",
    [
        # 사람 / 연예
        "BTS 컴백",
        "블랙핑크 신곡",
        "○○ 배우 결혼",
        "오징어게임 드라마",
        # 정치
        "윤석열 대통령",
        "국회 본회의",
        "총선 후보",
        # 스포츠
        "손흥민 골",
        "두산 야구",
        "올림픽 메달",
        "K리그 우승",
        # 사고 / 사건
        "강남 사고",
        "산불 화재",
        "태풍 카눈",
        # 차량 / 교통
        "테슬라 자동차",
        "공항 항공기",
        # 부동산 / 금융
        "강남 아파트",
        "코스피 종가",
        # 디지털
        "갤럭시 S25",
        "아이폰 17",
        "넷플릭스 신작",
        # 의료
        "독감 백신",
    ],
)
def test_rejects_non_food_keywords(keyword: str) -> None:
    assert not is_food_keyword(keyword), f"expected NOT food: {keyword!r}"


def test_rejects_empty_or_whitespace() -> None:
    assert not is_food_keyword("")
    assert not is_food_keyword("   ")
    assert not is_food_keyword("\t\n")


def test_denylist_overrides_allowlist() -> None:
    """Denylist veto: even if a food pattern matches, deny wins."""
    # "축구선수의 디저트가게" — has 디저트 (allowlist) but 축구 (denylist)
    # should be rejected even though "디저트" pattern matches.
    assert not is_food_keyword("축구 손흥민의 디저트가게")
    # Pure food version passes
    assert is_food_keyword("손민의 디저트가게")  # no athlete name


def test_filter_food_keywords_preserves_order() -> None:
    inputs = ["BTS 신곡", "쑥라떼", "윤석열 발언", "흑임자빙수", "한방차"]
    out = filter_food_keywords(inputs)
    assert out == ["쑥라떼", "흑임자빙수", "한방차"]


def test_filter_food_keywords_handles_empty_list() -> None:
    assert filter_food_keywords([]) == []
