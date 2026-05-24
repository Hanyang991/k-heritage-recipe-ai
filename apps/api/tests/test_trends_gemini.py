"""Tests for ``LLMExpansionCandidateProvider``."""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock, patch

import httpx

from app.services.trends.gemini_trends import (
    LLMExpansionCandidateProvider,
    _normalise,
    _parse_response,
    build_prompt,
)


def _gemini_payload(keywords: list[str]) -> dict:
    """A well-formed Gemini ``generateContent`` response."""
    return {
        "candidates": [
            {
                "content": {"parts": [{"text": json.dumps(keywords, ensure_ascii=False)}]},
                "finishReason": "STOP",
            }
        ]
    }


def _mock_response(status: int, body: dict | str) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    if isinstance(body, str):
        resp.text = body
        resp.json = MagicMock(side_effect=ValueError("not json"))
    else:
        resp.text = json.dumps(body, ensure_ascii=False)
        resp.json = MagicMock(return_value=body)
    return resp


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


def test_prompt_embeds_year_month_and_target_count() -> None:
    prompt = build_prompt(date(2026, 5, 23), 30)
    assert "2026년 5월" in prompt
    assert "30개" in prompt


def test_prompt_mentions_korean_variant_transformation_intent() -> None:
    prompt = build_prompt(date(2026, 5, 1), 30)
    # The core product intent — 두바이쫀득쿠키 → 두바이강정/약과 — must be in
    # the prompt so Gemini actively generates these variant candidates.
    assert "두바이강정" in prompt
    assert "두바이약과" in prompt


def test_prompt_lists_excluded_categories() -> None:
    prompt = build_prompt(date(2026, 5, 1), 30)
    for category in ("정치", "스포츠", "연예인", "IT 제품", "부동산"):
        assert category in prompt


def test_prompt_asks_for_json_array() -> None:
    prompt = build_prompt(date(2026, 5, 1), 30)
    assert "JSON" in prompt.upper()


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------


def test_parse_response_extracts_keyword_array() -> None:
    payload = _gemini_payload(["두바이강정", "흑임자라떼", "약과아이스크림"])
    assert _parse_response(payload) == ["두바이강정", "흑임자라떼", "약과아이스크림"]


def test_parse_response_skips_non_string_entries() -> None:
    payload = {
        "candidates": [
            {"content": {"parts": [{"text": json.dumps(["good", 42, None, "another"])}]}}
        ]
    }
    assert _parse_response(payload) == ["good", "another"]


def test_parse_response_raises_on_non_array_json() -> None:
    payload = {"candidates": [{"content": {"parts": [{"text": json.dumps({"not": "array"})}]}}]}
    try:
        _parse_response(payload)
    except ValueError as exc:
        assert "JSON array" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_parse_response_raises_on_invalid_json() -> None:
    payload = {"candidates": [{"content": {"parts": [{"text": "not json at all"}]}}]}
    try:
        _parse_response(payload)
    except ValueError as exc:
        assert "JSON" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_parse_response_raises_on_missing_candidates() -> None:
    for payload in ({}, {"candidates": []}, {"candidates": "nope"}):
        try:
            _parse_response(payload)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected ValueError on {payload!r}")


def test_parse_response_raises_on_missing_parts() -> None:
    payload = {"candidates": [{"content": {}}]}
    try:
        _parse_response(payload)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")


def test_parse_response_raises_on_missing_text() -> None:
    payload = {"candidates": [{"content": {"parts": [{"not_text": "x"}]}}]}
    try:
        _parse_response(payload)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def test_normalise_dedupes_and_trims() -> None:
    assert _normalise(["쑥라떼", "  쑥라떼  ", "흑임자라떼"]) == ["쑥라떼", "흑임자라떼"]


def test_normalise_drops_too_short_and_too_long() -> None:
    too_long = "가" * 21
    out = _normalise(["a", "쑥", "쑥라떼", too_long])
    assert "쑥라떼" in out
    assert "쑥" not in out
    assert too_long not in out
    # English single char ("a") is len 1 → dropped.
    assert "a" not in out


def test_normalise_drops_empty_after_strip() -> None:
    assert _normalise(["", "   ", "\t", "쑥라떼"]) == ["쑥라떼"]


# ---------------------------------------------------------------------------
# Provider end-to-end (mocked httpx)
# ---------------------------------------------------------------------------


def test_provider_name() -> None:
    p = LLMExpansionCandidateProvider(api_key="key")
    assert p.name == "llm_expansion"


def test_provider_returns_empty_without_api_key() -> None:
    p = LLMExpansionCandidateProvider(api_key="")
    with patch("httpx.Client.post") as post:
        assert p.discover_candidates() == []
    assert post.call_count == 0


def test_provider_returns_filtered_keywords() -> None:
    p = LLMExpansionCandidateProvider(api_key="key")
    payload = _gemini_payload(["쑥라떼", "두바이강정", "흑임자라떼", "BTS 컴백", "태풍 카눈"])
    with patch("httpx.Client.post") as post:
        post.return_value = _mock_response(200, payload)
        out = p.discover_candidates()
    # Food-adjacent passes; denylist matches are stripped.
    assert "쑥라떼" in out
    assert "두바이강정" in out
    assert "흑임자라떼" in out
    assert all(token not in out for token in ("BTS 컴백", "태풍 카눈"))


def test_provider_sends_api_key_as_query_param() -> None:
    p = LLMExpansionCandidateProvider(api_key="abc-123")
    with patch("httpx.Client.post") as post:
        post.return_value = _mock_response(200, _gemini_payload([]))
        p.discover_candidates()
        kwargs = post.call_args.kwargs
        assert kwargs["params"]["key"] == "abc-123"
        body = kwargs["json"]
        # Schema-enforced JSON
        gen = body["generationConfig"]
        assert gen["responseMimeType"] == "application/json"
        assert gen["responseSchema"]["type"] == "ARRAY"
        # Prompt is delivered as a single text part.
        assert "한국" in body["contents"][0]["parts"][0]["text"]


def test_provider_targets_configured_model() -> None:
    p = LLMExpansionCandidateProvider(api_key="key", model="gemini-2.5-pro")
    with patch("httpx.Client.post") as post:
        post.return_value = _mock_response(200, _gemini_payload([]))
        p.discover_candidates()
        url = post.call_args.args[0]
        assert "gemini-2.5-pro:generateContent" in url


def test_provider_passes_today_to_prompt() -> None:
    p = LLMExpansionCandidateProvider(api_key="key")
    with patch("httpx.Client.post") as post:
        post.return_value = _mock_response(200, _gemini_payload([]))
        p.discover_candidates(today=date(2027, 8, 15))
        prompt = post.call_args.kwargs["json"]["contents"][0]["parts"][0]["text"]
        assert "2027년 8월" in prompt


def test_provider_respects_limit() -> None:
    p = LLMExpansionCandidateProvider(api_key="key")
    payload = _gemini_payload(["쑥라떼", "흑임자라떼", "두바이강정", "약과아이스크림"])
    with patch("httpx.Client.post") as post:
        post.return_value = _mock_response(200, payload)
        out = p.discover_candidates(limit=2)
    assert out == ["쑥라떼", "흑임자라떼"]


def test_provider_returns_empty_on_http_error() -> None:
    p = LLMExpansionCandidateProvider(api_key="key")
    with patch("httpx.Client.post", side_effect=httpx.ConnectError("boom")):
        assert p.discover_candidates() == []


def test_provider_returns_empty_on_non_200() -> None:
    p = LLMExpansionCandidateProvider(api_key="key")
    with patch("httpx.Client.post") as post:
        post.return_value = _mock_response(429, "rate limited")
        assert p.discover_candidates() == []


def test_provider_returns_empty_on_malformed_response() -> None:
    p = LLMExpansionCandidateProvider(api_key="key")
    with patch("httpx.Client.post") as post:
        post.return_value = _mock_response(200, {"candidates": []})
        assert p.discover_candidates() == []


def test_provider_returns_empty_when_gemini_returns_object_not_array() -> None:
    p = LLMExpansionCandidateProvider(api_key="key")
    payload = {"candidates": [{"content": {"parts": [{"text": json.dumps({"keywords": ["x"]})}]}}]}
    with patch("httpx.Client.post") as post:
        post.return_value = _mock_response(200, payload)
        assert p.discover_candidates() == []


def test_target_count_is_clamped() -> None:
    too_high = LLMExpansionCandidateProvider(api_key="key", target_count=10_000)
    too_low = LLMExpansionCandidateProvider(api_key="key", target_count=0)
    assert too_high._target_count == 100  # type: ignore[attr-defined]
    assert too_low._target_count == 1  # type: ignore[attr-defined]
