"""Tests for ``NaverNewsCandidateProvider``."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx

from app.services.trends.naver_news import (
    DEFAULT_SEED_QUERIES,
    NaverNewsCandidateProvider,
    _extract_token_counts,
)


def _mock_response(status: int, body: dict | str) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    if isinstance(body, str):
        resp.text = body
        resp.json = MagicMock(side_effect=ValueError("not json"))
    else:
        resp.text = json.dumps(body)
        resp.json = MagicMock(return_value=body)
    return resp


def _payload(items: list[dict]) -> dict:
    return {"lastBuildDate": "...", "total": len(items), "start": 1, "items": items}


def _item(title: str, description: str = "") -> dict:
    return {
        "title": title,
        "description": description,
        "originallink": "https://example.com",
        "link": "https://example.com",
        "pubDate": "Sat, 23 May 2026 09:00:00 +0900",
    }


# ---------------------------------------------------------------------------
# Token extraction (the heart of the provider)
# ---------------------------------------------------------------------------


def test_extract_token_counts_pulls_hangul_compound_nouns() -> None:
    counts = _extract_token_counts(
        [
            _item("강남 카페서 인기 두바이쫀득쿠키 등장"),
            _item("두바이쫀득쿠키 후기 모음"),
        ]
    )
    assert counts["두바이쫀득쿠키"] == 2
    assert counts["강남"] == 1
    assert counts["카페서"] == 1


def test_extract_token_counts_strips_b_highlight_markup() -> None:
    counts = _extract_token_counts(
        [_item("이번 여름 <b>신상</b> 디저트로 떠오른 <b>두바이쫀득쿠키</b>")]
    )
    assert counts["두바이쫀득쿠키"] == 1
    assert "b" not in counts
    assert "/b" not in counts


def test_extract_token_counts_decodes_html_entities() -> None:
    counts = _extract_token_counts([_item("&quot;흑임자라떼&quot;는 신메뉴, &amp; 더해 인기")])
    assert counts["흑임자라떼"] == 1
    assert counts["신메뉴"] == 1


def test_extract_token_counts_ignores_single_char_and_long_runs() -> None:
    # 가 (1 char, particle), and a 13-char run should both be dropped.
    counts = _extract_token_counts([_item("가 쿠키 가나다라마바사아자차카타파하")])
    assert "가" not in counts
    assert "쿠키" in counts
    # 13-char hangul run exceeds the 12-char ceiling.
    assert "가나다라마바사아자차카타파하" not in counts


def test_extract_token_counts_includes_description() -> None:
    counts = _extract_token_counts(
        [_item("짧은 제목", description="본문에는 두바이쫀득쿠키 두바이쫀득쿠키 또 등장")]
    )
    assert counts["두바이쫀득쿠키"] == 2


def test_extract_token_counts_handles_missing_fields() -> None:
    counts = _extract_token_counts([{"title": "쿠키", "other": "ignored"}, {}])
    assert counts["쿠키"] == 1


# ---------------------------------------------------------------------------
# Provider end-to-end (mocked httpx)
# ---------------------------------------------------------------------------


def test_provider_name() -> None:
    p = NaverNewsCandidateProvider(client_id="id", client_secret="secret")
    assert p.name == "naver_news"


def test_provider_returns_empty_without_credentials() -> None:
    p = NaverNewsCandidateProvider(client_id="", client_secret="")
    with patch("httpx.Client.get") as get:
        assert p.discover_candidates() == []
    # Confirm no network call was attempted.
    assert get.call_count == 0


def test_provider_aggregates_across_seed_queries() -> None:
    p = NaverNewsCandidateProvider(
        client_id="id",
        client_secret="secret",
        seed_queries=("디저트 신상", "트렌드 음료"),
    )
    responses = {
        "디저트 신상": _payload(
            [
                _item("두바이쫀득쿠키 인기"),
                _item("두바이쫀득쿠키 후기"),
            ]
        ),
        "트렌드 음료": _payload([_item("흑임자라떼 매장 확대")]),
    }
    with patch("httpx.Client.get") as get:
        get.side_effect = lambda url, **kwargs: _mock_response(
            200, responses[kwargs["params"]["query"]]
        )
        out = p.discover_candidates()
    assert "두바이쫀득쿠키" in out
    assert "흑임자라떼" in out
    # Most-common keyword is first.
    assert out[0] == "두바이쫀득쿠키"


def test_provider_filters_via_food_filter() -> None:
    p = NaverNewsCandidateProvider(
        client_id="id", client_secret="secret", seed_queries=("디저트 신상",)
    )
    with patch("httpx.Client.get") as get:
        get.return_value = _mock_response(
            200,
            _payload(
                [
                    _item("쑥라떼 인기"),
                    _item("BTS 컴백 소식"),
                    _item("두산 야구 우승"),
                    _item("태풍 카눈 북상"),
                ]
            ),
        )
        out = p.discover_candidates()
    # Food-adjacent passes; denylist matches are stripped.
    assert "쑥라떼" in out
    assert all(token not in out for token in ("컴백", "야구", "우승", "카눈", "태풍"))


def test_provider_sends_auth_headers_and_query_params() -> None:
    p = NaverNewsCandidateProvider(
        client_id="id-xyz",
        client_secret="secret-xyz",
        seed_queries=("디저트 신상",),
        display_per_query=42,
    )
    with patch("httpx.Client.get") as get:
        get.return_value = _mock_response(200, _payload([]))
        p.discover_candidates()
        kwargs = get.call_args.kwargs
        assert kwargs["headers"]["X-Naver-Client-Id"] == "id-xyz"
        assert kwargs["headers"]["X-Naver-Client-Secret"] == "secret-xyz"
        assert kwargs["params"]["query"] == "디저트 신상"
        assert kwargs["params"]["display"] == "42"
        assert kwargs["params"]["sort"] == "date"


def test_provider_respects_limit() -> None:
    p = NaverNewsCandidateProvider(client_id="id", client_secret="secret", seed_queries=("seed",))
    with patch("httpx.Client.get") as get:
        get.return_value = _mock_response(
            200,
            _payload(
                [
                    _item("쑥라떼 흑임자라떼 두바이쫀득쿠키 약과아이스크림 헛개차"),
                ]
            ),
        )
        out = p.discover_candidates(limit=2)
    assert len(out) == 2


def test_provider_returns_empty_on_http_error() -> None:
    p = NaverNewsCandidateProvider(client_id="id", client_secret="secret", seed_queries=("seed",))
    with patch("httpx.Client.get", side_effect=httpx.ConnectError("boom")):
        assert p.discover_candidates() == []


def test_provider_returns_empty_on_non_200() -> None:
    p = NaverNewsCandidateProvider(client_id="id", client_secret="secret", seed_queries=("seed",))
    with patch("httpx.Client.get") as get:
        get.return_value = _mock_response(429, "rate limited")
        assert p.discover_candidates() == []


def test_provider_returns_empty_on_invalid_json() -> None:
    p = NaverNewsCandidateProvider(client_id="id", client_secret="secret", seed_queries=("seed",))
    with patch("httpx.Client.get") as get:
        get.return_value = _mock_response(200, "not-a-json-body")
        assert p.discover_candidates() == []


def test_provider_continues_after_partial_query_failure() -> None:
    """One bad seed query shouldn't kill the whole batch."""
    p = NaverNewsCandidateProvider(
        client_id="id",
        client_secret="secret",
        seed_queries=("query_ok", "query_500"),
    )
    responses = {
        "query_ok": _mock_response(200, _payload([_item("쑥라떼 인기")])),
        "query_500": _mock_response(500, "server error"),
    }
    with patch("httpx.Client.get") as get:
        get.side_effect = lambda url, **kwargs: responses[kwargs["params"]["query"]]
        out = p.discover_candidates()
    assert "쑥라떼" in out


def test_provider_with_empty_seed_queries_returns_empty() -> None:
    p = NaverNewsCandidateProvider(client_id="id", client_secret="secret", seed_queries=())
    with patch("httpx.Client.get") as get:
        assert p.discover_candidates() == []
    assert get.call_count == 0


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_default_seed_queries_are_food_oriented() -> None:
    # Sanity: every default seed query is non-empty + food-oriented.
    for q in DEFAULT_SEED_QUERIES:
        assert q.strip(), q
    assert any("디저트" in q for q in DEFAULT_SEED_QUERIES)


def test_display_per_query_is_clamped_to_naver_max() -> None:
    p = NaverNewsCandidateProvider(client_id="id", client_secret="secret", display_per_query=10_000)
    with patch("httpx.Client.get") as get:
        get.return_value = _mock_response(200, _payload([]))
        p.discover_candidates()
        assert get.call_args.kwargs["params"]["display"] == "100"


def test_display_per_query_is_clamped_to_min_one() -> None:
    p = NaverNewsCandidateProvider(client_id="id", client_secret="secret", display_per_query=0)
    with patch("httpx.Client.get") as get:
        get.return_value = _mock_response(200, _payload([]))
        p.discover_candidates()
        assert get.call_args.kwargs["params"]["display"] == "1"
